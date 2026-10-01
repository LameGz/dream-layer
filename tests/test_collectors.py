"""采集器单测(C-8):读盘 jsonl/log、路径排除先于读取、demo 种子。"""

from __future__ import annotations

import json
import os
from datetime import datetime

from dreamlayer.collectors.demo import DemoCollector
from dreamlayer.collectors.read_disk import ReadDiskCollector

GLOBS = ["**/*secret*", "**/*token*", "**/.env*"]


def test_read_disk_jsonl_fields(tmp_path):
    src = tmp_path / "out"
    src.mkdir()
    (src / "a.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"id": "x1", "text": "内容一", "ts": "2026-10-01T08:00:00",
                            "tag": "drop", "summary": "摘要"}, ensure_ascii=False),
                "not json",  # 坏行跳过
                json.dumps({"text": "无 id 无 tag"}, ensure_ascii=False),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    c = ReadDiskCollector(
        {"name": "t", "origin": "daily-pipeline", "path_glob": str(src / "*.jsonl"),
         "format": "jsonl", "content_field": "text", "time_field": "ts",
         "tag_map": {"drop": "rejected"}, "default_tag": "unknown"},
        exclude_globs=GLOBS,
    )
    items = c.collect()
    assert len(items) == 2
    assert items[0]["content"] == "内容一" and items[0]["time"] == "2026-10-01T08:00:00"
    assert items[0]["tag"] == "drop"  # 原始 tag 透传,映射交给 contract 层
    assert items[0]["id"] == "x1" and items[0]["summary"] == "摘要"
    assert items[1]["tag"] == "unknown" and items[1]["id"] is None
    assert all(it["origin"] == "daily-pipeline" for it in items)
    assert c.tag_map == {"drop": "rejected"}


def test_read_disk_log_lines_mtime_and_override(tmp_path):
    src = tmp_path / "logs"
    src.mkdir()
    f = src / "daily.log"
    f.write_text("第一行日志\n\n第二行日志\n", encoding="utf-8")
    c = ReadDiskCollector(
        {"name": "t", "origin": "logs", "path_glob": str(src / "*.log"), "format": "log",
         "default_tag": "rejected"},
        exclude_globs=GLOBS,
    )
    items = c.collect()
    assert [it["content"] for it in items] == ["第一行日志", "第二行日志"]
    mtime = datetime.fromtimestamp(os.path.getmtime(f))
    assert all(it["time"].date() == mtime.date() for it in items)  # time 取 mtime
    assert all(it["tag"] == "rejected" for it in items)


def test_read_disk_log_time_override(tmp_path):
    src = tmp_path / "logs"
    src.mkdir()
    (src / "d.log").write_text("行\n", encoding="utf-8")
    c = ReadDiskCollector(
        {"origin": "logs", "path_glob": str(src / "*.log"), "format": "log",
         "time": "2026-09-01T06:30:00"},
        exclude_globs=GLOBS,
    )
    items = c.collect()
    assert items[0]["time"] == datetime.fromisoformat("2026-09-01T06:30:00")


def test_excluded_file_never_read(tmp_path):
    # secret_token.log 同时命中 path_glob 与隐私排除 glob:
    # 若被读取,invalid JSON 会抛错 / 标记串会出现在产物里——两者都不发生即证明"未读"
    src = tmp_path / "mix"
    src.mkdir()
    (src / "secret_token.log").write_text("NEVER-READ-MARKER-7f3a91 {{{not json", encoding="utf-8")
    (src / "daily.log").write_text("普通日志行\n", encoding="utf-8")
    c = ReadDiskCollector(
        {"origin": "t", "path_glob": str(src / "*.log"), "format": "log", "default_tag": "rejected"},
        exclude_globs=GLOBS,
    )
    items = c.collect()
    assert len(items) == 1
    assert items[0]["content"] == "普通日志行"
    assert all("NEVER-READ-MARKER-7f3a91" not in it["content"] for it in items)


def test_read_disk_mdfile_whole_note(tmp_path):
    """知识库模式(FR-G1 扩):整篇笔记 = 一条碎片;date 取 front-matter,正文整体保留。"""
    src = tmp_path / "vault"
    src.mkdir()
    (src / "梦的机制.md").write_text(
        "---\n"
        "title: 梦的机制\n"
        "date: 2026-09-20\n"
        "---\n"
        "# 梦的机制\n\n"
        "海马体在 REM 期做片段化重激活。\n\n"
        "皮层负责把激活编织成叙事。\n",
        encoding="utf-8",
    )
    (src / "无日期笔记.md").write_text("只有正文,\n没有 front-matter。\n", encoding="utf-8")
    c = ReadDiskCollector(
        {"name": "vault", "origin": "vault", "path_glob": str(src / "*.md"), "format": "mdfile",
         "default_tag": "unknown"},
        exclude_globs=GLOBS,
    )
    items = c.collect()
    assert len(items) == 2  # 一篇一条,不按行拆
    note = next(it for it in items if "海马体" in it["content"])
    assert note["origin"] == "vault" and note["tag"] == "unknown"
    assert note["time"].startswith("2026-09-20")  # front-matter date
    assert "海马体在 REM 期" in note["content"] and "编织成叙事" in note["content"]  # 整篇保留
    assert note["summary"] is None  # 超长走契约层硬截断,不用标题顶替正文


def test_read_disk_mdfile_mtime_fallback(tmp_path):
    src = tmp_path / "vault"
    src.mkdir()
    f = src / "无日期.md"
    f.write_text("正文而已。\n", encoding="utf-8")
    c = ReadDiskCollector(
        {"origin": "vault", "path_glob": str(f), "format": "mdfile"}, exclude_globs=[]
    )
    items = c.collect()
    assert len(items) == 1
    assert items[0]["content"].strip() == "正文而已。"


def test_demo_collector_resolves_relative_days(tmp_path):
    seed = tmp_path / "demo_day.jsonl"
    seed.write_text(
        "\n".join(
            [
                json.dumps({"id": "a", "days_ago": 0, "clock": "08:30", "tag": "rejected",
                            "origin": "o", "content": "今天"}, ensure_ascii=False),
                json.dumps({"id": "b", "days_ago": 40, "clock": "09:10", "tag": "hesitated",
                            "origin": "o", "content": "四十天前"}, ensure_ascii=False),
                json.dumps({"id": "c", "time": "2026-01-01T10:00:00", "tag": "selected",
                            "origin": "o", "content": "固定时间"}, ensure_ascii=False),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    items = DemoCollector(seed).collect()
    assert len(items) == 3
    today = datetime.now().date()
    t0 = datetime.fromisoformat(items[0]["time"])
    t40 = datetime.fromisoformat(items[1]["time"])
    assert t0.date() == today
    assert (t0.date() - t40.date()).days == 40
    assert items[2]["time"] == "2026-01-01T10:00:00"  # ISO 透传


def test_demo_collector_missing_seed_returns_empty(tmp_path):
    assert DemoCollector(tmp_path / "nope.jsonl").collect() == []
