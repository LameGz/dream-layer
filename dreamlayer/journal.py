"""梦话日志(C-6)— 模板照抄 v0.3 §10;落盘前过 assert_journal_safe(本地 only)。

P1:waker 给出 verdict 后重写 journal(verdict/observation/open_question 真值,FR-E1);
一夜全 noise -> all_noise=true + note"今夜无梦"(FR-B6)。journal.md 之外另有
data/dreams/YYYY-MM-DD.jsonl(§6 梦话契约的机器可读落盘,wake/confirm 的数据源):
  行 1 = {"record": "night", "date": ..., "meta": {...11 字段...}}
  行 N = {"record": "dream", "dream_id": "YYYY-MM-DD-NN", "pair": [...], "persona": ...,
          "raw": ..., "meta": {temperature, attempts, a, b}, + wake 写回的 verdict 字段}
dream_id 与 journal 的 "## pair NN" 同序号:pair 07 -> dream_id 2026-10-01-07。
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

from .privacy import assert_journal_safe

REASON_NO_MATERIAL = "太累但没东西可梦"
REASON_ALL_NOISE = "今夜无梦"

# C-6 要求的 meta 字段(按此顺序渲染 meta 行)
META_FIELDS = (
    "pool",
    "pairs",
    "history_sampled",
    "late",
    "origin_relaxed",
    "time_relaxed",
    "hard_relaxed",
    "dropped",
    "redacted",
    "all_noise",
    "warnings",
)


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    return str(v)


def _meta_value(meta: dict, key: str):
    if key in meta:
        return meta[key]
    return False if key in ("late", "all_noise") else 0


def _inline(text: str, indent: str = "  ") -> str:
    return str(text).replace("\r\n", "\n").replace("\n", "\n" + indent)


def _dget(d, key, default=None):
    """dream 记录双形态访问:MicroDream 对象或 dict(wake 重写以 dict 为主)。"""
    if isinstance(d, dict):
        return d.get(key, default)
    return getattr(d, key, default)


def _dmeta(d) -> dict:
    m = _dget(d, "meta", {}) or {}
    return m if isinstance(m, dict) else {}


def render_journal(day: date, dreams, meta: dict) -> str:
    lines = [f"# dream_journal · {day.isoformat()}", ""]
    lines.append("meta: " + " ".join(f"{k}={_fmt(_meta_value(meta, k))}" for k in META_FIELDS))

    reason = meta.get("reason")
    if reason:
        lines += ["", f"note: {reason}"]

    for i, d in enumerate(dreams, 1):
        a, b = _dmeta(d).get("a", {}), _dmeta(d).get("b", {})
        verdict = _dget(d, "verdict") or "unwoken"
        observation = _dget(d, "observation") or ""
        open_question = _dget(d, "open_question") or ""
        lines += [
            "",
            f"## pair {i:02d} · [{a.get('tag', '?')} · {a.get('origin', '?')} {a.get('date', '?')}] "
            f"× [{b.get('tag', '?')} · {b.get('origin', '?')} {b.get('date', '?')}]",
            f"persona: {_dget(d, 'persona', '?')}",
            f"raw: {_inline(_dget(d, 'raw', ''))}",
            f"verdict: {verdict}",
            f"observation: {_inline(observation)}" if observation else "observation:",
            f"open_question: {_inline(open_question)}" if open_question else "open_question:",
            f"evidence: [{_dget(d, 'pair')[0]}, {_dget(d, 'pair')[1]}]",
        ]
        attempts = _dmeta(d).get("attempts") or []
        if len(attempts) > 1:
            lines.append("attempts:")
            for at in attempts:
                lines.append(f"  - {_inline(at, '    ')}")

    details = meta.get("warnings_detail") or []
    if details:
        lines += ["", "warnings_detail:"]
        lines += [f"  - {w}" for w in details]

    lines.append("")
    return "\n".join(lines)


def write_journal(day: date, dreams, meta: dict, journal_dir=None) -> Path:
    """落盘前过 assert_journal_safe;云同步目录直接拒绝,不落盘(C-6/IT-10)。"""
    journal_dir = Path(journal_dir) if journal_dir is not None else Path("data/journal")
    target = journal_dir / f"{day.isoformat()}.md"
    if meta.get("journal_local_only", True):
        assert_journal_safe(target)
    journal_dir.mkdir(parents=True, exist_ok=True)
    target.write_text(render_journal(day, dreams, meta), encoding="utf-8")
    return target


# ---------- 梦话契约 jsonl(§6 梦话格式的落盘形态;P1 起 dream/wake/confirm 共用) ----------

def dream_to_dict(d, dream_id: str) -> dict:
    """MicroDream 对象或 dict -> dream 记录(dict 直通,保留 wake 写回的 verdict 字段)。"""
    if isinstance(d, dict):
        out = dict(d)
    else:
        out = {"pair": [d.pair[0], d.pair[1]], "persona": d.persona, "raw": d.raw,
               "meta": dict(d.meta)}
    out["record"] = "dream"
    out["dream_id"] = out.get("dream_id") or dream_id
    out["pair"] = list(out.get("pair") or [])
    return out


def write_dreams(day: date, dreams, meta: dict, dreams_dir=None) -> Path:
    """一夜梦话落盘 data/dreams/YYYY-MM-DD.jsonl(行 1 night meta,其后逐 dream)。"""
    dreams_dir = Path(dreams_dir) if dreams_dir is not None else Path("data/dreams")
    dreams_dir.mkdir(parents=True, exist_ok=True)
    target = dreams_dir / f"{day.isoformat()}.jsonl"
    lines = [json.dumps({"record": "night", "date": day.isoformat(), "meta": dict(meta)},
                        ensure_ascii=False)]
    for i, d in enumerate(dreams, 1):
        lines.append(json.dumps(dream_to_dict(d, f"{day.isoformat()}-{i:02d}"), ensure_ascii=False))
    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


def read_dreams(path) -> tuple[dict | None, list[dict]]:
    """读取一夜梦话:返回 (night meta, [dream 记录]);坏行跳过不停摆(NFR5)。"""
    p = Path(path)
    if not p.exists():
        return None, []
    night: dict | None = None
    dreams: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(obj, dict):
            continue
        if obj.get("record") == "night":
            night = obj.get("meta") or {}
        elif obj.get("record") == "dream" or ("pair" in obj and "dream_id" in obj):
            dreams.append(obj)
    return night, dreams
