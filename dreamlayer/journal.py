"""梦话日志(C-6)— 模板照抄 v0.3 §10;落盘前过 assert_journal_safe(本地 only)。

P1:waker 给出 verdict 后重写 journal(verdict/observation/open_question 真值,FR-E1);
一夜全 noise -> all_noise=true + note"今夜无梦"(FR-B6)。journal.md 之外另有
data/dreams/YYYY-MM-DD.jsonl(§6 梦话契约的机器可读落盘,wake/confirm 的数据源):
  行 1 = {"record": "night", "date": ..., "meta": {...11 字段...}}
  行 N = {"record": "dream", "dream_id": "YYYY-MM-DD-attempt-NN", "pair": [...], "persona": ...,
          "raw": ..., "meta": {temperature, attempts, a, b}, + wake 写回的 verdict 字段}
dream_id 中 attempt 是每次运行的 12 位随机标识;兼容读取旧的 YYYY-MM-DD-NN。
逐次记录保存在 dreams/attempts/<date>/ 下,日期文件是最近一次运行的兼容视图。
"""

from __future__ import annotations

import json
import os
import re
import tempfile
import threading
import uuid
from datetime import date
from pathlib import Path

from .privacy import assert_journal_safe

REASON_NO_MATERIAL = "太累但没东西可梦"
REASON_ALL_NOISE = "今夜无梦"
_WRITE_LOCK = threading.RLock()


def atomic_text(path: Path, text: str):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + '.', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def parse_dream_id(ident: str):
    match = re.fullmatch(r'(\d{4}-\d{2}-\d{2})(?:-([a-f0-9]{12}))?-(\d{2,})', ident)
    if not match:
        return None
    try:
        date.fromisoformat(match[1])
    except ValueError:
        return None
    return match[1], match[2], match[3]


def dream_file(data_dir, dream_id):
    parsed = parse_dream_id(dream_id)
    if not parsed:
        return None
    day, attempt, _ = parsed
    root = Path(data_dir) / 'dreams'
    archive = root / 'attempts' / day / f'{attempt or "legacy"}.jsonl'
    return archive if archive.is_file() else root / f'{day}.jsonl'

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
    text = render_journal(day, dreams, meta)
    if meta.get('attempt_id'):
        atomic_text(journal_dir / 'attempts' / day.isoformat() / (meta['attempt_id'] + '.md'), text)
    atomic_text(target, text)
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
    with _WRITE_LOCK:
        root = Path(dreams_dir) if dreams_dir is not None else Path('data/dreams')
        latest = root / f'{day.isoformat()}.jsonl'
        meta = dict(meta)
        records = list(dreams)
        identities = [_dget(d, 'dream_id') for d in records]
        attempt = meta.get('attempt_id')
        if not attempt and identities and all(identities):
            parsed = parse_dream_id(identities[0])
            attempt = parsed[1] if parsed else None
        elif not attempt:
            attempt = uuid.uuid4().hex[:12]
        if attempt:
            if not re.fullmatch(r'[a-f0-9]{12}', attempt):
                raise ValueError('Invalid attempt_id')
            meta['attempt_id'] = attempt
        archive = root / 'attempts' / day.isoformat() / f'{attempt or "legacy"}.jsonl'
        is_new = not archive.exists()
        # Preserve old date-NN records before advancing the compatibility view.
        if latest.is_file():
            old_meta, _ = read_dreams(latest)
            legacy = root / 'attempts' / day.isoformat() / 'legacy.jsonl'
            if not (old_meta or {}).get('attempt_id') and not legacy.exists():
                atomic_text(legacy, latest.read_text(encoding='utf-8'))
        _, previous = read_dreams(archive)
        by_id = {d['dream_id']: d for d in previous}
        prefix = day.isoformat() + (f'-{attempt}' if attempt else '')
        out = []
        for i, dream in enumerate(records, 1):
            record = dream_to_dict(dream, f'{prefix}-{i:02d}')
            before = by_id.get(record['dream_id'])
            if before:
                if any(record.get(k) != before.get(k) for k in ('pair', 'raw')):
                    raise ValueError('Dream identity cannot be reused for different content')
                if before.get('confirmed'):
                    record['confirmed'] = True
            out.append(record)
        lines = [json.dumps({'record': 'night', 'date': day.isoformat(), 'meta': meta}, ensure_ascii=False)]
        lines.extend(json.dumps(d, ensure_ascii=False) for d in out)
        text = '\n'.join(lines) + '\n'
        atomic_text(archive, text)
        latest_meta, _ = read_dreams(latest)
        if is_new or not latest.exists() or (latest_meta or {}).get('attempt_id') == attempt:
            atomic_text(latest, text)
        return archive


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
