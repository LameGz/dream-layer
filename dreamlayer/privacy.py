"""隐私(C-2)— 两层规则,全部只读 privacy.yaml(G5)。

1. 路径级排除:path_excluded 在读取文件之前生效——命中即跳过,不读内容;
2. 内容级脱敏:redact 在入池之前生效;打码占比 > 0.3 时调用方整条丢弃;
3. journal 本地 only:assert_journal_safe 在落盘之前检查,云同步目录直接拒绝。
"""

from __future__ import annotations

import fnmatch
import re
from functools import lru_cache
from pathlib import Path

REDACTED_PLACEHOLDER = "[REDACTED]"

# 常见云同步目录标记(v0.3 §4.5/§8):journal 永久但仅本地
CLOUD_MARKERS = ("onedrive", "dropbox", "百度网盘", "坚果云", "icloud")


class CloudPathError(RuntimeError):
    """journal 落盘路径位于云同步目录内——拒绝写入。"""


def _posix(path) -> str:
    return str(path).replace("\\", "/")


def path_excluded(path: str, globs: list[str]) -> bool:
    """fnmatch 匹配,posix 风格路径;命中任意一个 glob 即排除。"""
    p = _posix(path)
    for g in globs or []:
        if fnmatch.fnmatch(p, _posix(g)):
            return True
    return False


@lru_cache(maxsize=32)
def _compiled(patterns: tuple[str, ...]) -> tuple[re.Pattern, ...]:
    """FR-H5:同一组 redact_patterns 每夜多次调用,预编译缓存(终审遗留顺手修)。"""
    return tuple(re.compile(p) for p in patterns)


def redact(text: str, patterns: list[str]) -> tuple[str, float]:
    """命中替换为 [REDACTED],返回 (新文本, 打码字符占比)。

    占比 = 命中片段总字符数 / 原文长度;> 0.3 时调用方整条丢弃(C-2)。
    """
    if not text:
        return text, 0.0
    total = 0
    out = text
    for compiled in _compiled(tuple(patterns or [])):

        def _sub(m: re.Match) -> str:
            nonlocal total
            total += len(m.group(0))
            return REDACTED_PLACEHOLDER

        out = compiled.sub(_sub, out)
    ratio = total / max(len(text), 1)
    return out, ratio


def assert_journal_safe(path: Path) -> None:
    """journal 本地 only:路径任一段含云同步标记(大小写不敏感)即 raise,不写文件。"""
    parts = [p.lower() for p in Path(path).parts]
    for marker in CLOUD_MARKERS:
        if any(marker in part for part in parts):
            raise CloudPathError(
                f"journal 落盘路径位于云同步目录(命中标记 {marker!r}),拒绝写入:{path}"
            )
