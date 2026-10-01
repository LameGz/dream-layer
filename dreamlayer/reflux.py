"""有效回流的落点(FR-D4 / FR-I3)。

confirm CLI -> reflux_log.jsonl:人工确认为 recall / trend / cross_time 的回流才算"有效回流";
quiet_cycle(隔日梦)与 metrics(FR-I1)都读它。reflux_log 是追加写;dreams jsonl 中的对应
记录会被打上 confirmed 标记(防重复确认)。
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

REFLUX_VERDICTS = ("recall", "trend", "cross_time")

VALID_VERDICTS = REFLUX_VERDICTS + ("noise",)  # 供 CLI 校验与 dreams 契约引用


def log_path(data_dir) -> Path:
    return Path(data_dir) / "reflux_log.jsonl"


def load_log(data_dir) -> list[dict]:
    p = log_path(data_dir)
    if not p.exists():
        return []
    out = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            out.append(obj)
    return out


def find_dream(data_dir, dream_id: str) -> dict | None:
    """按 dream_id(YYYY-MM-DD-NN)在 data/dreams/ 下定位 dream 记录。"""
    stem = dream_id.rsplit("-", 1)[0]
    if not stem.count("-") == 2:
        return None
    from .journal import read_dreams

    _, dreams = read_dreams(Path(data_dir) / "dreams" / f"{stem}.jsonl")
    for d in dreams:
        if d.get("dream_id") == dream_id:
            return d
    return None


def already_confirmed(log: list[dict], dream_id: str) -> bool:
    return any(e.get("dream_id") == dream_id for e in log)


def append_confirm(data_dir, dream_id: str, verdict: str, dream: dict | None = None) -> dict:
    """登记一条有效回流(追加写);dream 记录可缺(只确认 verdict 最少需要 dream_id)。

    trend 条目带 due 字段(confirmed_at + 14 天,红队 C4:预警要对账,不靠人记)。
    """
    now = datetime.now()
    entry = {
        "dream_id": dream_id,
        "verdict": verdict,
        "confirmed_at": now.isoformat(timespec="seconds"),
        "evidence": list((dream or {}).get("pair") or []),
        "observation": (dream or {}).get("observation", ""),
        "open_question": (dream or {}).get("open_question", ""),
    }
    if verdict == "trend":
        from datetime import timedelta

        entry["due"] = (now + timedelta(days=14)).date().isoformat()
        entry["reviewed"] = False  # 14 天后对账:预言是否被新数据验证
    p = log_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    return entry


def mark_confirmed(data_dir, dream_id: str) -> None:
    """在 dreams jsonl 的对应记录上打 confirmed 标记(幂等;找不到文件则忽略)。"""
    stem = dream_id.rsplit("-", 1)[0]
    f = Path(data_dir) / "dreams" / f"{stem}.jsonl"
    if not f.exists():
        return
    lines_out = []
    changed = False
    for line in f.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            lines_out.append(line)
            continue
        if isinstance(obj, dict) and obj.get("dream_id") == dream_id and not obj.get("confirmed"):
            obj["confirmed"] = True
            changed = True
            lines_out.append(json.dumps(obj, ensure_ascii=False))
        else:
            lines_out.append(line)
    if changed:
        f.write_text("\n".join(lines_out) + "\n", encoding="utf-8")


def confirmed_dates(log: list[dict]) -> list[date]:
    out = []
    for e in log:
        try:
            out.append(datetime.fromisoformat(str(e.get("confirmed_at"))).date())
        except (ValueError, TypeError):
            continue
    return out


def quiet_skip(quiet_cfg: dict | None, data_dir, today: date) -> tuple[bool, str]:
    """quiet_cycle(FR-D4):连续 idle_days 天无有效回流 -> 隔日梦(奇数序数日跳过,纯函数式判定)。

    mode: alternate_days(默认)| off。返回 (是否跳过今夜, journal note)。
    """
    cfg = quiet_cfg or {}
    mode = str(cfg.get("mode", "alternate_days"))
    if mode == "off":
        return False, ""
    idle_days = int(cfg.get("idle_days", 7))
    dates = confirmed_dates(load_log(data_dir))
    recent = [d for d in dates if 0 <= (today - d).days <= idle_days]
    if recent:
        return False, ""
    if today.toordinal() % 2 == 1:
        return True, f"静默节流:连续 {idle_days} 天无有效回流,今夜隔日梦(quiet_cycle)"
    return False, ""


# ---------- 交互过审(FR-D4 的体验面):向导 + 批量 ----------

def load_candidates(data_dir, day: date) -> list[dict]:
    """某天晨报的待过审条目:机器暂定 verdict ∈ 有效回流三值,且未被确认过。"""
    from .journal import read_dreams

    _, dreams = read_dreams(Path(data_dir) / "dreams" / f"{day.isoformat()}.jsonl")
    return [d for d in dreams
            if d.get("verdict") in REFLUX_VERDICTS and not d.get("confirmed")]


def apply_batch(data_dir, specs: list[str]) -> tuple[int, list[str]]:
    """批量登记 "dream_id:verdict"(agent 从对话收集后一次落账)。

    返回 (成功登记数, 警告列表);非法 verdict / 找不到 id / 重复确认都不中断,只警告。
    """
    ok, warns = 0, []
    for spec in specs:
        spec = (spec or "").strip()
        if not spec:
            continue
        did, _, v = spec.partition(":")
        v = v.strip().lower()
        if v not in REFLUX_VERDICTS:
            warns.append(f"非法 verdict(只认 {'/'.join(REFLUX_VERDICTS)}):{spec}")
            continue
        dream = find_dream(data_dir, did.strip())
        if dream is None:
            warns.append(f"找不到 {did.strip()}")
            continue
        if already_confirmed(load_log(data_dir), did.strip()):
            warns.append(f"{did.strip()} 已确认过,跳过")
            continue
        append_confirm(data_dir, did.strip(), v, dream)
        mark_confirmed(data_dir, did.strip())
        ok += 1
    return ok, warns


def run_wizard(candidates: list[dict], data_dir, input_fn=None, echo=print) -> int:
    """逐条过审向导:展示观察/问题/证据,人按 1/2/3 确认,s 跳过,q 结束。返回登记数。

    input_fn 缺省用内置 input(调用时解析,便于测试替换)。
    """
    if not candidates:
        echo("没有待过审的候选(昨夜无回流,或已全部确认)。")
        return 0
    echo(f"晨报过审 · {len(candidates)} 条候选(登记越少,它越安静)")
    keymap = {"1": "recall", "r": "recall", "2": "trend", "t": "trend",
              "3": "cross_time", "c": "cross_time"}
    n = 0
    for i, d in enumerate(candidates, 1):
        meta = d.get("meta") or {}
        a, b = meta.get("a") or {}, meta.get("b") or {}
        echo("─" * 56)
        echo(f"[{i}/{len(candidates)}] {d.get('verdict')} · "
             f"surprise {float(d.get('surprise') or 0):.2f} · {d.get('dream_id')}")
        echo(f"  观察:{d.get('observation') or '(空)'}")
        echo(f"  问题:{d.get('open_question') or '(空)'}")
        echo(f"  证据:{a.get('key', '?')}({a.get('tag', '?')} · {a.get('date', '?')})"
             f" × {b.get('key', '?')}({b.get('tag', '?')} · {b.get('date', '?')})")
        while True:
            try:
                raw = (input_fn or input)("确认有效? [1]recall [2]trend [3]cross_time [s]跳过 [q]结束 > ")
            except (EOFError, KeyboardInterrupt):
                echo(f"\n过审中止:已登记 {n} 条,其余保持未确认。")
                return n
            choice = (raw or "").strip().lower()
            if choice in keymap:
                verdict = keymap[choice]
                append_confirm(data_dir, d.get("dream_id"), verdict, d)
                mark_confirmed(data_dir, d.get("dream_id"))
                echo(f"  ✓ 已登记 {verdict} -> {log_path(data_dir)}")
                n += 1
                break
            if choice in ("s", "skip"):
                echo("  - 跳过(留在晨报里,不算有效回流)")
                break
            if choice in ("q", "quit", "exit"):
                echo(f"过审中止:已登记 {n} 条,其余保持未确认。")
                return n
            echo("  没看懂,请输 1 / 2 / 3 / s / q")
    echo(f"过审完毕:登记 {n} 条。梦产率与频控读 {log_path(data_dir)}")
    return n
