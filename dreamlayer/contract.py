"""素材契约(C-1)— dream-core 唯一入口的数据形状(v0.3 §3.1)。

core 不懂业务:只做五值校验、时间解析、截断/摘要与幂等键。
连接器负责把自有标签映射到规范五值;映射关系随连接器配置,不进 core。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime

TAGS = ("selected", "rejected", "hesitated", "discarded", "unknown")

DEFAULT_ORIGIN = "unknown"


@dataclass
class Material:
    """入梦素材。字段顺序照抄 C-1。raw 一律等于脱敏后的原文(G5:脱敏发生在入池之前)。"""

    id: str | None
    content: str
    time: datetime
    tag: str
    origin: str
    summary: str | None = None
    truncated: bool = False
    from_summary: bool = False
    raw: str | None = None

    @property
    def key(self) -> str:
        """幂等键(C-3):id 优先,否则 sha256(content.strip())。"""
        if self.id:
            return self.id
        return content_hash(self.content)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "content": self.content,
            "time": self.time.isoformat(),
            "tag": self.tag,
            "origin": self.origin,
            "summary": self.summary,
            "truncated": self.truncated,
            "from_summary": self.from_summary,
            "raw": self.raw,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Material":
        t = d.get("time")
        if not isinstance(t, datetime):
            t = datetime.fromisoformat(str(t))
        return cls(
            id=d.get("id"),
            content=d["content"],
            time=t,
            tag=d["tag"],
            origin=d.get("origin") or DEFAULT_ORIGIN,
            summary=d.get("summary"),
            truncated=bool(d.get("truncated", False)),
            from_summary=bool(d.get("from_summary", False)),
            raw=d.get("raw"),
        )


def content_hash(content: str) -> str:
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()


@dataclass
class BuildResult:
    """build_material 的结果:material 为 None 表示该条被丢弃(调用方计 dropped)。"""

    material: Material | None = None
    warning: str | None = None


def parse_time(value) -> datetime | None:
    """尽量宽 ISO 解析;解析不了返回 None,由调用方丢弃该条。"""
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime(value.year, value.month, value.day)
    if not isinstance(value, str):
        return None
    s = value.strip()
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:-1] + "+00:00" if s.endswith("Z") else s)
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y/%m/%d %H:%M:%S", "%Y/%m/%d %H:%M", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            continue
    return None


def build_material(raw: dict, tag_map: dict[str, str], max_chars: int) -> BuildResult:
    """raw 契约 dict -> Material。

    - tag 不在五值 -> 查 tag_map;仍无 -> unknown 并记 warning(连接器映射错配要能被发现);
    - content 缺失或 time 无法解析 -> material=None(调用方计 dropped);
    - len(content) > max_chars:有 summary -> content=summary 且 from_summary=True;
      无 -> 硬截断且 truncated=True;两种情况 raw 均保留原文(调用方已脱敏)。
    """
    content = raw.get("content")
    if content is None:
        return BuildResult(None, None)
    content = str(content)
    if not content.strip():
        return BuildResult(None, None)

    t = parse_time(raw.get("time"))
    if t is None:
        return BuildResult(None, None)

    tag = raw.get("tag")
    warning = None
    if not tag:
        tag = "unknown"  # v0.3 §3.1:tag 可选,缺省 unknown(非映射错配,不告警)
    elif tag not in TAGS:
        mapped = (tag_map or {}).get(tag)
        if mapped in TAGS:
            tag = mapped
        else:
            tag = "unknown"
            warning = f"tag_unmapped:{raw.get('tag')}"

    origin = str(raw.get("origin") or DEFAULT_ORIGIN)
    summary = raw.get("summary")
    summary = None if summary is None else str(summary)

    raw_text = content
    truncated = from_summary = False
    if len(content) > max_chars:
        if summary:
            content = summary
            from_summary = True
        else:
            content = content[:max_chars]
            truncated = True

    material = Material(
        id=(str(raw["id"]) if raw.get("id") else None),
        content=content,
        time=t,
        tag=tag,
        origin=origin,
        summary=summary,
        truncated=truncated,
        from_summary=from_summary,
        raw=raw_text,
    )
    return BuildResult(material, warning)
