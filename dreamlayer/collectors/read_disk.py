"""读盘采集器(C-8 / 施工图 §4.6):配置驱动,任何落盘系统通用。

path_glob 枚举 -> path_excluded 过滤(命中即跳过,不读内容,G5)-> 按 format 解析:
  jsonl  :每行一个对象(content_field / time_field 可配);
  log/md :逐行,整行作 content,time 取文件 mtime(source_cfg 可用 time 覆盖);
  mdfile :整篇 Markdown = 一条碎片(知识库接入)——front-matter 的 date 作 time、
          title 仅用于未来追溯,正文整体作 content,超长由契约层硬截断。
"""

from __future__ import annotations

import glob as globlib
import json
import os
import re
from datetime import datetime
from pathlib import Path

from ..contract import parse_time
from ..privacy import path_excluded

_FM_TITLE = re.compile(r"^title:\s*(.+)$", re.M)
_FM_DATE = re.compile(r"^date:\s*(.+)$", re.M)


def read_md_file(path, default_tag, origin) -> list[dict]:
    """整篇笔记 = 一条碎片:knowledge-base 模式。date 取 front-matter,缺省文件 mtime。"""
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    if text.startswith("---"):
        end = text.find("\n---", 3)
        if end != -1:
            fm = text[3:end]
            text = text[end + 4 :].lstrip("\n")
            m = _FM_DATE.search(fm)
            t = parse_time(m.group(1).strip()) if m else None
            if t is None:
                t = datetime.fromtimestamp(os.path.getmtime(path))
    else:
        t = datetime.fromtimestamp(os.path.getmtime(path))
    return [{
        "id": None,
        "content": text,
        "time": t.isoformat(),
        "tag": default_tag,
        "origin": origin,
        "summary": None,  # 整篇保留,超长走契约层硬截断(截头不截意)
    }]


def read_jsonl_file(path, content_field, time_field, default_tag, origin) -> list[dict]:
    """单文件 jsonl 解析(坏行跳过,不让整夜停摆);read_disk 与 drop 采集器共用。"""
    items = []
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue  # 坏行跳过,不让整夜停摆
            if not isinstance(obj, dict):
                continue
            items.append(
                {
                    "id": obj.get("id"),
                    "content": obj.get(content_field),
                    "time": obj.get(time_field),
                    "tag": obj.get("tag", default_tag),
                    "origin": obj.get("origin") or origin,
                    "summary": obj.get("summary"),
                }
            )
    return items


class ReadDiskCollector:
    def __init__(self, source_cfg: dict, exclude_globs: list[str] | None = None):
        self.cfg = dict(source_cfg or {})
        # 路径级排除在读取文件之前生效(G5):globs 来自 privacy.yaml,优先级高于采集源配置
        self.exclude_globs = list(exclude_globs or [])
        self.tag_map = dict(self.cfg.get("tag_map") or {})
        self.origin = self.cfg.get("origin") or self.cfg.get("name") or "unknown"

    def collect(self) -> list[dict]:
        fmt = self.cfg.get("format", "jsonl")
        content_field = self.cfg.get("content_field", "content")
        time_field = self.cfg.get("time_field", "time")
        default_tag = self.cfg.get("default_tag", "unknown")
        out: list[dict] = []
        for f in sorted(globlib.glob(self.cfg["path_glob"], recursive=True)):
            if path_excluded(f, self.exclude_globs):
                continue  # 不读命中文件的内容
            if fmt == "jsonl":
                out.extend(self._read_jsonl(f, content_field, time_field, default_tag))
            elif fmt == "mdfile":
                out.extend(read_md_file(f, default_tag, self.origin))
            else:  # log | md
                out.extend(self._read_lines(f, default_tag))
        return out

    def _read_jsonl(self, path, content_field, time_field, default_tag):
        return read_jsonl_file(path, content_field, time_field, default_tag, self.origin)

    def _read_lines(self, path, default_tag):
        # time 取文件 mtime;source_cfg 可用 time(IS0 字符串或 datetime)覆盖
        t = self.cfg.get("time")
        t = parse_time(t) if t is not None else datetime.fromtimestamp(os.path.getmtime(path))
        items = []
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.rstrip("\r\n")
                if not line.strip():
                    continue
                items.append(
                    {
                        "id": None,
                        "content": line,
                        "time": t,
                        "tag": default_tag,
                        "origin": self.origin,
                        "summary": None,
                    }
                )
        return items
