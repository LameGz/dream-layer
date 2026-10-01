"""Demo 采集器(C-8):读 data/seed/demo_day.jsonl——真实管线没接好之前,第一夜就能跑。

种子行支持相对日期:{"days_ago": N, "clock": "HH:MM"} -> 以运行日为"今天"解析,
种子永不失效;也直接支持 "time" 的 ISO 字符串透传。
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path


class DemoCollector:
    tag_map: dict = {}

    def __init__(self, seed_path):
        self.seed_path = Path(seed_path)

    def collect(self) -> list[dict]:
        if not self.seed_path.exists():
            return []
        out = []
        for line in self.seed_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                out.append(self._resolve_time(obj))
        return out

    def _resolve_time(self, obj: dict) -> dict:
        if "days_ago" in obj:
            base = date.today() - timedelta(days=int(obj["days_ago"]))
            hh, mm = str(obj.get("clock", "08:00")).split(":")[:2]
            obj = dict(obj)
            obj["time"] = datetime(base.year, base.month, base.day, int(hh), int(mm)).isoformat()
        return obj
