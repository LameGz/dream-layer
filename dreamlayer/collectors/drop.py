"""drop 目录采集器(FR-G3):Codex/ZCode 会话废料投递的 watch 目录,collect 时读入。

投递端(listen,POST 端点)把废料写成 drop 目录下的 *.jsonl;本采集器只负责读:
path 下所有 jsonl -> 路径排除先于读取(G5) -> 与 read_disk 相同的 jsonl 解析。
文件留在原地不去动它:幂等去重由 pool 层按 id / content 哈希保证,重复读无害。
"""

from __future__ import annotations

import glob as globlib
from pathlib import Path

from ..privacy import path_excluded
from .read_disk import read_jsonl_file


class DropCollector:
    def __init__(self, source_cfg: dict, exclude_globs: list[str] | None = None):
        self.cfg = dict(source_cfg or {})
        self.exclude_globs = list(exclude_globs or [])
        self.tag_map = dict(self.cfg.get("tag_map") or {})
        self.origin = self.cfg.get("origin") or self.cfg.get("name") or "drop"
        self.path = str(self.cfg["path"])

    def collect(self) -> list[dict]:
        fmt = self.cfg.get("format", "jsonl")
        content_field = self.cfg.get("content_field", "content")
        time_field = self.cfg.get("time_field", "time")
        default_tag = self.cfg.get("default_tag", "unknown")
        out: list[dict] = []
        for f in sorted(globlib.glob(str(Path(self.path) / "**" / "*.jsonl"), recursive=True)):
            if path_excluded(f, self.exclude_globs):
                continue  # 不读命中文件的内容
            if fmt == "jsonl":
                out.extend(read_jsonl_file(f, content_field, time_field, default_tag, self.origin))
            else:
                continue  # drop 目录只收 jsonl 投递
        return out
