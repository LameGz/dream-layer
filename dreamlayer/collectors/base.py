"""采集器协议(C-8):collect() 返回 raw 契约 dict 列表(v0.3 §3.1 的字段形状)。"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class Collector(Protocol):
    """采集器只做搬运,不做业务逻辑;tag_map 交给 contract 层做五值映射。"""

    tag_map: dict

    def collect(self) -> list[dict]: ...
