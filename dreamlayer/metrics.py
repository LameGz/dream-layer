"""指标与保底产物(FR-I1 / FR-I2)—— P1 已建。

五指标(前 8 周为基线/目标校准期,不是承诺):
  误杀回收数 / 趋势预警命中 / 跨时关联确认 / 梦产率 / 存在感指标(主观,不设数值)。
保底产物独立于梦话是否有用(FR-I2):读 pool jsonl 即画——
  - 被拒池主题漂移图 drift.svg(rejected+discarded 高频 token 的周频率曲线);
  - 阈值邻近带聚合曲线 band.svg(rejected+hesitated 逐日条数;通用代理:core 不懂业务阈值)。
零依赖:SVG 手拼字符串,不引入 matplotlib(NFR4)。
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

from .reflux import load_log

PALETTE = ("#4e79a7", "#f28e2b", "#e15759", "#76b7b2", "#59a14f", "#edc948", "#b07aa1", "#ff9da7")


# ---------- 池读取 ----------

def _read_pool(pool_dir) -> list[dict]:
    out = []
    d = Path(pool_dir)
    if not d.exists():
        return out
    for f in sorted(d.glob("*.jsonl")):
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict) and obj.get("content"):
                out.append(obj)
    return out


def _week_key(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


# ---------- FR-I2 图表 ----------

def drift_svg(pool_dir, weeks: int = 12, top: int = 8) -> str | None:
    """被拒池主题漂移:rejected+discarded 的 top token 在各周的出现率折线。"""
    from .waker import tokenize

    mats = [m for m in _read_pool(pool_dir) if m.get("tag") in ("rejected", "discarded")]
    if len(mats) < 8:
        return None
    per_week_tokens: dict[str, list[set]] = defaultdict(list)
    df: Counter = Counter()
    for m in mats:
        try:
            wk = _week_key(date.fromisoformat(str(m["time"])[:10]))
        except (ValueError, KeyError):
            continue
        toks = tokenize(str(m["content"]))
        if not toks:
            continue
        per_week_tokens[wk].append(toks)
        df.update(toks)
    if len(per_week_tokens) < 2 or not df:
        return None
    week_keys = sorted(per_week_tokens)[-weeks:]
    top_tokens = [t for t, _ in df.most_common(200) if len(t) >= 2][:top]
    series = {}
    for t in top_tokens:
        ys = []
        for wk in week_keys:
            docs = per_week_tokens[wk]
            ys.append(sum(1 for toks in docs if t in toks) / max(len(docs), 1))
        series[t] = ys
    return _line_chart(week_keys, series, "被拒池主题漂移(rejected+discarded 周出现率)")


def band_svg(pool_dir, days: int = 30) -> str | None:
    """阈值邻近带聚合曲线:rejected+hesitated 逐日条数(通用代理,阈值业务侧自看)。"""
    mats = [m for m in _read_pool(pool_dir) if m.get("tag") in ("rejected", "hesitated")]
    if not mats:
        return None
    today = date.today()
    counts: dict[date, int] = defaultdict(int)
    for m in mats:
        try:
            d = date.fromisoformat(str(m["time"])[:10])
        except (ValueError, KeyError):
            continue
        if today - timedelta(days=days - 1) <= d <= today:
            counts[d] += 1
    if not counts:
        return None
    xs = [today - timedelta(days=days - 1 - i) for i in range(days)]
    series = {"邻近带条数/日(rejected+hesitated)": [counts.get(d, 0) for d in xs]}
    return _line_chart([d.isoformat()[5:] for d in xs], series, "阈值邻近带聚合曲线")


def _line_chart(x_labels: list[str], series: dict[str, list[float]], title: str,
                w: int = 720, h: int = 300) -> str:
    """极简多折线 SVG:x 均分,y 按各自 max 归一(双图共用)。"""
    pad_l, pad_r, pad_t, pad_b = 40, 16, 28, 34
    iw, ih = w - pad_l - pad_r, h - pad_t - pad_b
    n = max(len(x_labels), 2)

    def xy(i: int, v: float, vmax: float) -> tuple[float, float]:
        x = pad_l + iw * i / (n - 1)
        y = pad_t + ih * (1 - (v / vmax if vmax else 0))
        return round(x, 1), round(y, 1)

    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
        f'font-family="sans-serif" font-size="11">',
        f"<text x=\"{pad_l}\" y=\"16\" fill=\"#333\">{title}</text>",
    ]
    vmax_all = max((max(vals) if vals else 0) for vals in series.values()) or 1.0
    for xi in range(0, n, max(n // 8, 1)):
        x, _ = xy(xi, 0, vmax_all)
        parts.append(f'<line x1="{x}" y1="{pad_t}" x2="{x}" y2="{pad_t + ih}" stroke="#eee"/>')
        parts.append(
            f'<text x="{x}" y="{h - 12}" fill="#888" text-anchor="middle">{x_labels[xi]}</text>'
        )
    parts.append(f'<line x1="{pad_l}" y1="{pad_t + ih}" x2="{pad_l + iw}" y2="{pad_t + ih}" stroke="#ccc"/>')
    for k, (color, (name, vals)) in enumerate(zip(PALETTE * 2, series.items())):
        vmax = max(vals) if vals else 1.0
        pts = " ".join(f"{x},{y}" for x, y in (xy(i, v, vmax) for i, v in enumerate(vals)))
        parts.append(f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.8"/>')
        parts.append(
            f'<text x="{pad_l + iw + 2}" y="{pad_t + 12 + k * 14}" fill="{color}">{name}</text>'
        )
    parts.append("</svg>")
    return "\n".join(parts)


# ---------- FR-I1 指标 ----------

def journal_stats(journal_dir) -> dict:
    """入梦夜数 = journal 存在且 pairs>0 的夜;解析 meta 行。"""
    d = Path(journal_dir)
    nights_total = nights_dreamed = pairs_total = 0
    if d.exists():
        for f in sorted(d.glob("*.md")):
            try:
                meta_line = next(
                    ln for ln in f.read_text(encoding="utf-8").splitlines() if ln.startswith("meta:")
                )
            except StopIteration:
                continue
            fields = {}
            for tok in meta_line.split()[1:]:
                k, _, v = tok.partition("=")
                try:
                    v = int(v)
                except ValueError:
                    pass
                fields[k] = v
            nights_total += 1
            if fields.get("pairs", 0) and fields.get("pairs", 0) > 0:
                nights_dreamed += 1
                pairs_total += fields["pairs"]
    return {"nights_total": nights_total, "nights_dreamed": nights_dreamed, "pairs_total": pairs_total}


def reflux_stats(data_dir) -> dict:
    log = load_log(data_dir)
    per = Counter(e.get("verdict") for e in log)
    return {
        "total": len(log),
        "recall": per.get("recall", 0),
        "trend": per.get("trend", 0),
        "cross_time": per.get("cross_time", 0),
    }


def dream_stats(dreams_dir) -> dict:
    """蓝队加固:废话率 / 诚实阀门命中率 / Lane B 配额使用率 / 跨时对占比(读 dreams jsonl)。"""
    from .journal import read_dreams

    d = Path(dreams_dir)
    nights = pairs_total = honest = 0
    lane_b_used = 0
    verdicts_by_lane: Counter = Counter()
    if d.exists():
        for f in sorted(d.glob("*.jsonl")):
            night, dreams = read_dreams(f)
            if night is None:
                continue
            if night.get("pairs", 0):
                nights += 1
            for dr in dreams:
                pairs_total += 1
                raw = dr.get("raw") or ""
                if "没碰出东西" in raw:
                    honest += 1
                lane = dr.get("lane") or ""
                v = dr.get("verdict")
                if lane == "B":
                    lane_b_used += 1
                if v in ("recall", "trend", "cross_time"):
                    verdicts_by_lane[lane or "?"] += 1
    return {
        "nights": nights,
        "pairs_total": pairs_total,
        "honest_valve": honest,
        "honest_ratio": (honest / pairs_total) if pairs_total else 0.0,
        "lane_b_used": lane_b_used,
        "reflux_by_lane": dict(verdicts_by_lane),
    }


def pending_trend_reviews(data_dir, today: date | None = None) -> list[dict]:
    """到期未对账的 trend 预警(红队 C4):due <= today 且 reviewed 未标记。"""
    today = today or date.today()
    out = []
    for e in load_log(data_dir):
        if e.get("verdict") != "trend" or e.get("reviewed"):
            continue
        due = e.get("due")
        if not due:
            continue
        try:
            if date.fromisoformat(str(due)) <= today:
                out.append(e)
        except ValueError:
            continue
    return out


def ab_stats(data_dir) -> dict:
    """红队 C5:对照实验分组确认率——reflux_log 的 dream_id 日期 → 当日 night meta 的 arm。"""
    from .journal import read_dreams

    data_dir = Path(data_dir)
    arms: dict[str, Counter] = {"A": Counter(), "B": Counter()}
    for e in load_log(data_dir):
        did = str(e.get("dream_id") or "")
        day = did.rsplit("-", 1)[0] if did.count("-") >= 3 else ""
        f = data_dir / "dreams" / f"{day}.jsonl"
        if not day or not f.exists():
            continue
        night, _ = read_dreams(f)
        arm = (night or {}).get("experiment")
        if arm in arms:
            arms[arm][e.get("verdict") or "?"] += 1
    return {arm: dict(c) for arm, c in arms.items() if c}


def report_text(data_dir, today: date | None = None) -> str:
    today = today or date.today()
    js = journal_stats(Path(data_dir) / "journal")
    rs = reflux_stats(data_dir)
    ds = dream_stats(Path(data_dir) / "dreams")
    dream_rate = (rs["total"] / js["nights_dreamed"]) if js["nights_dreamed"] else 0.0
    lines = [
        f"# dream metrics · {today.isoformat()}",
        "",
        f"- 入梦夜数:{js['nights_dreamed']}(journal 总数 {js['nights_total']},微型梦累计 {js['pairs_total']} 对)",
        f"- 有效回流:{rs['total']}(recall {rs['recall']} / trend {rs['trend']} / cross_time {rs['cross_time']})",
        f"- 误杀回收数(recall,目标前 8 周 ≥1/月):{rs['recall']}",
        f"- 趋势预警命中(trend;登记后 14 天对账由人工执行):{rs['trend']}",
        f"- 跨时关联确认(cross_time):{rs['cross_time']}",
        f"- 梦产率(有效回流/入梦夜;长期期望值低,诚实展示):{dream_rate:.3f}",
        "- 存在感指标:主观——两周后你是否开始期待早上看晨报?",
        "",
        "## 健康信号(蓝队加固:如实展示,不修饰)",
        "",
        f"- 诚实阀门命中率(引擎直说\"没碰出东西\"的占比;过高说明素材问题,过低说明引擎在硬凑):{ds['honest_ratio']:.1%}({ds['honest_valve']}/{ds['pairs_total']})",
        f"- Lane B 配额使用:{ds['lane_b_used']} 对带稀有锚点(连续打满配额说明锚点过松)",
        f"- 回流按 lane 分组(红队 C5:8 周后看 Lane A/B 各贡献多少确认):{ds['reflux_by_lane'] or '暂无'}",
        "",
    ]
    ab = ab_stats(data_dir)
    if ab:
        lines += ["## 对照实验分组(红队 C5:A=随机配对 / B=锚点+随机)", ""]
        for arm, counts in ab.items():
            total = sum(counts.values())
            lines.append(f"- {arm} 组:{total} 条确认 {counts}")
        lines.append("")
    pending = pending_trend_reviews(data_dir, today)
    if pending:
        lines += ["## 到期未对账的 trend 预警(红队 C4:预言要兑现,不靠人记)", ""]
        for e in pending:
            lines.append(f"- {e['dream_id']}(登记 {str(e.get('confirmed_at', ''))[:10]},到期 {e.get('due')}):{e.get('observation', '')[:60]}")
        lines.append("")
    return "\n".join(lines)


def write_report(data_dir, today: date | None = None) -> Path:
    """指标报告 + 两张保底产物图 -> data/report/。"""
    data_dir = Path(data_dir)
    today = today or date.today()
    out_dir = data_dir / "report"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"metrics-{today.isoformat()}.md").write_text(report_text(data_dir, today), encoding="utf-8")
    drift = drift_svg(data_dir / "pool")
    if drift:
        (out_dir / "drift.svg").write_text(drift, encoding="utf-8")
    band = band_svg(data_dir / "pool")
    if band:
        (out_dir / "band.svg").write_text(band, encoding="utf-8")
    return out_dir
