"""节律(C-7)— run_once 即时完整一夜;run_daemon 内置循环(不是 cron)。

tick:02:30 collect / 03:00 dream / 05:00 wake(P1 起为真醒来:两路筛选 -> 两道闸 -> 晨报)。
补梦:daemon 启动时,昨晚 journal 不存在且 now >= 05:00 -> 立即 run_once 且 meta.late=true。
"""

from __future__ import annotations

import random
import re
import sys
import time
from datetime import date, datetime, time as dtime, timedelta
from pathlib import Path

from . import metrics, reflux, sink
from .config import Cfg
from .contract import build_material
from .dreamer import dream_night
from .engine import FakeEngine, OpenAICompatibleEngine
from .journal import (
    REASON_ALL_NOISE,
    REASON_NO_MATERIAL,
    read_dreams,
    write_dreams,
    write_journal,
)
from .pool import Pool
from .privacy import redact
from .waker import wake

# C-2 契约常数:打码占比 > 0.3 整条丢弃(非权重)
REDACT_RATIO_LIMIT = 0.3
# 补梦判定阈值(纯函数默认参数,非权重)
CATCHUP_AFTER = dtime(5, 0)


# ---------- 运行时构建 ----------

def build_engine(cfg: Cfg, fake: bool):
    """--fake 用 FakeEngine(零网络);真实模式实例化 OpenAI 兼容引擎(密钥走环境变量)。

    红队 D1:privacy.mode=local_only 时,base_url 非本机地址直接拒绝启动——
    默认是云端引擎,素材会离开本机;隐私闭环必须显式可开,不靠默认值的善意。
    """
    if fake:
        return FakeEngine()
    e = cfg.engine
    if cfg.privacy.mode == "local_only":
        from urllib.parse import urlparse

        host = (urlparse(e.base_url).hostname or "").lower()
        if host not in ("localhost", "127.0.0.1", "::1"):
            raise RuntimeError(
                f"privacy.mode=local_only:引擎 base_url 指向 {host!r}(非本机),拒绝启动。"
                f"本地引擎(ollama 等)请把 base_url 指向 127.0.0.1;或显式将 mode 改回 open。"
            )
    return OpenAICompatibleEngine(e.base_url, e.model, e.api_key_env, timeout=e.request_timeout_s)


def build_collectors(cfg: Cfg, data_dir, privacy_globs=None):
    """Demo 采集器 + 读盘采集器 + drop 目录采集器(FR-G3;路径排除在读取文件之前生效)。"""
    from .collectors.demo import DemoCollector
    from .collectors.drop import DropCollector
    from .collectors.read_disk import ReadDiskCollector

    globs = cfg.privacy.exclude_globs if privacy_globs is None else privacy_globs
    ccfg = cfg.rhythm.collectors or {}
    out = []
    seed = (ccfg.get("demo") or {}).get("seed_path")
    seed = Path(seed) if seed else Path(data_dir) / "seed" / "demo_day.jsonl"
    out.append(DemoCollector(seed))
    for src in ccfg.get("drop") or []:
        out.append(DropCollector(src, exclude_globs=globs))
    for src in ccfg.get("read_disk") or []:
        out.append(ReadDiskCollector(src, exclude_globs=globs))
    return out


# ---------- 一夜的两个阶段(02:30 collect / 03:00 dream) ----------

def collect_phase(cfg: Cfg, collectors, data_dir, now=None, pool: Pool | None = None, rng=None):
    """collect -> privacy(路径排除已在采集器内生效;内容脱敏在此,先于入池)-> contract -> pool。

    每晚顺带执行 90 天滚动清理(FR-A8,retention_days 来自 privacy.yaml)。
    """
    rng = rng or random.Random()
    now = now or datetime.now()
    pool = pool if pool is not None else Pool(cfg.weights, data_dir=Path(data_dir) / "pool", rng=rng)
    meta = {"pool": 0, "dropped": 0, "redacted": 0, "warnings_detail": []}
    pruned = pool.prune(now.date() - timedelta(days=cfg.privacy.retention_days))
    if pruned:
        meta["warnings_detail"].append(f"pool_pruned:{pruned}")
    max_chars = cfg.rhythm.content_max_chars
    switches = cfg.privacy.origin_switches or {}
    patterns = cfg.privacy.redact_patterns or []

    for c in collectors:
        for item in c.collect():
            meta["pool"] += 1

            origin = str(item.get("origin") or "unknown")
            if switches.get(origin) is False:
                # origin 级开关:任一 origin 可整体不入梦(v0.3 §8)
                meta["dropped"] += 1
                meta["warnings_detail"].append(f"origin_switched:{origin}")
                continue

            content = item.get("content")
            content = "" if content is None else str(content)
            new_content, ratio = redact(content, patterns)
            if ratio > REDACT_RATIO_LIMIT:
                meta["dropped"] += 1
                meta["redacted"] += 1
                continue

            summary = item.get("summary")
            if summary is not None:
                new_summary, s_ratio = redact(str(summary), patterns)
                if s_ratio > REDACT_RATIO_LIMIT:
                    meta["dropped"] += 1
                    meta["redacted"] += 1
                    continue
                hit = (new_content != content) or (new_summary != str(summary))
                summary = new_summary
            else:
                hit = new_content != content

            if hit:
                meta["redacted"] += 1

            payload = dict(item)
            payload["content"] = new_content
            payload["summary"] = summary
            res = build_material(payload, getattr(c, "tag_map", {}) or {}, max_chars)
            if res.material is None:
                meta["dropped"] += 1
                continue
            if res.warning:
                meta["warnings_detail"].append(res.warning)
            pool.add(res.material)
    return pool, meta


def dream_phase(cfg: Cfg, engine, data_dir, now=None, late=False, collect_meta=None,
                pool: Pool | None = None, rng=None):
    """水位检查 -> quiet 频控 -> 加权候选 -> 约束配对 -> 并行微型梦 -> journal + dreams jsonl 落盘。"""
    now = now or datetime.now()
    today = now.date()
    rng = rng or random.Random()
    data_dir = Path(data_dir)
    pool = pool if pool is not None else Pool(cfg.weights, data_dir=data_dir / "pool", rng=rng)
    meta = dict(collect_meta or {"pool": len(pool), "dropped": 0, "redacted": 0, "warnings_detail": []})
    meta["journal_local_only"] = cfg.privacy.journal_local_only
    meta["late"] = late
    journal_dir = data_dir / "journal"

    def _empty(reason):
        meta.update(
            pairs=0, history_sampled=0, origin_relaxed=0, time_relaxed=0, hard_relaxed=0,
            all_noise=False, warnings=len(meta.get("warnings_detail", [])),
            reason=reason,
        )
        return write_journal(today, [], meta, journal_dir=journal_dir)

    # 水位:当日 < min_pool -> "太累但没东西可梦",当夜结束("没东西可梦"只看水位)
    if pool.count_on(today) < cfg.rhythm.min_pool:
        return _empty(REASON_NO_MATERIAL)

    # quiet_cycle(FR-D4):连续 idle_days 天无有效回流 -> 隔日梦
    skip, qnote = reflux.quiet_skip(cfg.rhythm.quiet_cycle, data_dir, today)
    if skip:
        return _empty(qnote)

    history = pool.sample_history(cfg.weights.history_sample, cfg.weights.history_window_days, today)
    # 红队 C5 对照实验:experiment.ab 开启时交替 A(随机)/ B(锚点+随机);
    # arm 标记进 night meta(dreams jsonl),metrics 按组聚合确认率。
    # 终审问题 1:交替按"已实际做梦的夜数"奇偶,不是日历序数——quiet_cycle 隔日梦
    # 跳过的夜不占 arm 名额,否则静默期会系统性抽空 B 组样本。
    arm = None
    if (cfg.rhythm.experiment or {}).get("ab"):
        dreamed = 0
        dreams_dir = Path(data_dir) / "dreams"
        if dreams_dir.exists():
            from .journal import read_dreams

            for f in dreams_dir.glob("*.jsonl"):
                night, _ = read_dreams(f)
                if (night or {}).get("pairs", 0) > 0:
                    dreamed += 1  # 只数 pairs>0 的夜;静默/水位不足的夜不占 arm 名额
        # 当前夜将排在已有做梦夜之后(若今夜又是同日,其 night meta 已含前次记录)
        arm = "A" if dreamed % 2 == 0 else "B"
    mode = "anchor_mix" if arm == "B" else "random"
    pairs, stats = pool.build_pairs(
        cfg.rhythm.pairs_per_night, today,
        constraints=cfg.rhythm.pair_constraints, history=history, mode=mode,
    )
    for p in pairs:
        pool.record_coverage(p.keys(), today)

    dreams = dream_night(
        pairs, engine, cfg.rhythm.personas,
        temperature=cfg.rhythm.temperature,
        concurrency=cfg.engine.concurrency,
        max_tokens=cfg.rhythm.max_tokens,
        refusal_retry=cfg.engine.refusal_retry,
        rng=rng,
    )
    meta.update(
        pairs=len(pairs),
        history_sampled=len(history),
        origin_relaxed=stats.origin_relaxed,
        time_relaxed=stats.time_relaxed,
        hard_relaxed=stats.hard_relaxed,
        all_noise=False,  # wake 阶段重判(wake 后回写 all_noise 与 verdict)
        warnings=len(meta.get("warnings_detail", [])),
    )
    if arm:
        meta["experiment"] = arm  # C5:写进 night meta(journal meta 行固定 11 字段不加)
    path = write_journal(today, dreams, meta, journal_dir=journal_dir)
    write_dreams(today, dreams, meta, dreams_dir=data_dir / "dreams")  # §6 梦话契约落盘
    return path


# ---------- 05:00 醒来(FR-C/FR-D/FR-I,P1 已建) ----------

_NOTE_RE = re.compile(r"(?m)^note: (.+)$")


def _journal_note(journal_path: Path) -> str | None:
    if not journal_path.exists():
        return None
    m = _NOTE_RE.search(journal_path.read_text(encoding="utf-8"))
    return m.group(1).strip() if m else None


def wake_phase(cfg: Cfg, engine, data_dir, now=None, pool: Pool | None = None):
    """醒来:两路筛选 -> 两道闸 -> journal verdict 重写 -> morning.md -> 保底产物。

    返回 (refluxes, morning_path)。dreams jsonl 缺失(水位不足夜)时只写晨报说明行。
    """
    now = now or datetime.now()
    today = now.date()
    data_dir = Path(data_dir)
    pool = pool if pool is not None else Pool(cfg.weights, data_dir=data_dir / "pool")
    dreams_path = data_dir / "dreams" / f"{today.isoformat()}.jsonl"

    note = None
    refluxes = []
    if dreams_path.exists():
        night_meta, dream_dicts = read_dreams(dreams_path)
        night_meta = dict(night_meta or {})
        refluxes, verdicts, wake_warnings = wake(
            dream_dicts, pool, engine,
            today=today,
            temperature=cfg.rhythm.wake_temperature,
            max_tokens=cfg.rhythm.wake_max_tokens,
            max_reflux=cfg.rhythm.max_reflux_per_day,
        )
        if wake_warnings:
            detail = night_meta.setdefault("warnings_detail", [])
            detail.extend(wake_warnings)
            night_meta["warnings"] = len(detail)
        for d in dream_dicts:
            v = verdicts.get(d.get("dream_id"))
            if v:
                d.update(v)
        if refluxes:
            night_meta["all_noise"] = False
            night_meta.pop("reason", None)
            note = None
        else:
            night_meta["all_noise"] = True
            night_meta["reason"] = REASON_ALL_NOISE
            note = REASON_ALL_NOISE
        # verdict 回写:dreams jsonl + journal 同步为真值(FR-E1)
        write_dreams(today, dream_dicts, night_meta, dreams_dir=data_dir / "dreams")
        write_journal(today, dream_dicts, night_meta, journal_dir=data_dir / "journal")
    else:
        note = _journal_note(data_dir / "journal" / f"{today.isoformat()}.md") or REASON_ALL_NOISE

    morning = sink.render(
        refluxes,
        out_path=data_dir / "morning" / f"{today.isoformat()}.md",
        night_note=note,
        morning_of=today,
    )
    # webhook 推送(FR-D2):URL 只走环境变量;失败只记录,不影响落盘产物
    webhook = None
    env_name = cfg.rhythm.webhook_url_env
    if env_name:
        import os

        webhook = os.environ.get(env_name)
    if webhook:
        ok, detail = sink.push(refluxes, webhook)
        print(f"[dreamlayer] webhook push: {'ok' if ok else detail}", flush=True)
    metrics.write_report(data_dir, today=today)  # 保底产物(FR-I2),独立于梦话是否有用
    return refluxes, morning


# ---------- 入口 ----------

def run_once(cfg: Cfg, collectors, engine, data_dir=Path("data"), late=False,
             now=None, rng=None) -> Path | None:
    """即时完整一夜:collect -> privacy -> contract -> pool -> dream -> wake -> morning(C-7)。

    wake 失败不让整夜失败(NFR5):journal 已落盘,错误打到 stderr 后返回。
    """
    now = now or datetime.now()
    rng = rng or random.Random()
    data_dir = Path(data_dir)
    pool, cmeta = collect_phase(cfg, collectors, data_dir, now=now, rng=rng)
    path = dream_phase(cfg, engine, data_dir, now=now, late=late, collect_meta=cmeta,
                       pool=pool, rng=rng)
    try:
        wake_phase(cfg, engine, data_dir, now=now, pool=pool)
    except Exception as e:
        print(f"[dreamlayer] wake phase failed: {e}", file=sys.stderr, flush=True)
    return path


# ---------- 补梦与常驻 ----------

def should_catchup(last_journal_date: date | None, now: datetime,
                   after: dtime = CATCHUP_AFTER) -> bool:
    """补梦判定(纯函数,C-7):昨晚 journal 不存在且 now >= 05:00 -> True。

    笔记本白天才开机的话,严格遵守 03:00 就永远没梦——开机补梦是唯一的错过例外。
    """
    if now.time() < after:
        return False
    yesterday = now.date() - timedelta(days=1)
    return last_journal_date is None or last_journal_date < yesterday


def last_journal_date(journal_dir) -> date | None:
    d = Path(journal_dir)
    if not d.exists():
        return None
    dates = []
    for f in d.glob("*.md"):
        try:
            dates.append(date.fromisoformat(f.stem))
        except ValueError:
            continue
    return max(dates) if dates else None


def _parse_hm(s: str) -> dtime:
    h, m = str(s).split(":")[:2]
    return dtime(int(h), int(m))


def phase_times(cfg: Cfg) -> list[tuple[dtime, str]]:
    return [
        (_parse_hm(cfg.rhythm.collect_time), "collect"),
        (_parse_hm(cfg.rhythm.dream_time), "dream"),
        (_parse_hm(cfg.rhythm.wake_time), "wake"),
    ]


def next_tick(now: datetime, times) -> tuple[datetime, str]:
    """算下一个 tick(纯函数):今天还有则取最近,否则明天最早。"""
    today_cands = [
        (datetime.combine(now.date(), t), name) for t, name in times if t > now.time()
    ]
    if today_cands:
        return min(today_cands)
    t, name = min(times)
    return datetime.combine(now.date() + timedelta(days=1), t), name


def run_daemon(cfg: Cfg, collectors=None, engine=None, data_dir=Path("data"),
               rng=None, sleep=time.sleep):
    """常驻节律:内置循环,算出下一个 tick 的秒数后 sleep(v0.3 §5 明文:不是外部 cron)。"""
    collectors = collectors if collectors is not None else build_collectors(cfg, data_dir)
    engine = engine if engine is not None else build_engine(cfg, fake=False)

    if should_catchup(last_journal_date(Path(data_dir) / "journal"), datetime.now()):
        run_once(cfg, collectors, engine, data_dir=data_dir, late=True, rng=rng)

    pool: Pool | None = None
    collect_meta = None
    while True:
        now = datetime.now()
        tick_at, phase = next_tick(now, phase_times(cfg))
        sleep(max(0.0, (tick_at - datetime.now()).total_seconds()))
        try:
            if phase == "collect":
                pool, collect_meta = collect_phase(cfg, collectors, data_dir, rng=rng)
            elif phase == "dream":
                dream_phase(cfg, engine, data_dir, collect_meta=collect_meta, pool=pool, rng=rng)
                collect_meta = None  # 一夜结束
            else:
                # 05:00 wake:两路筛选 -> 两道闸 -> morning.md + 保底产物(P1)
                wake_phase(cfg, engine, data_dir=data_dir, pool=pool)
        except Exception as e:  # 熔断-lite:单次异常不杀节律,不重试轰炸(v0.3 §8)
            print(f"[dreamlayer] {phase} phase failed: {e}", flush=True)
            collect_meta = None
