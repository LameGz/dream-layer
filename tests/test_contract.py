"""素材契约单测(C-1),含 IT-04 / IT-09 的契约层断言。"""

from __future__ import annotations

import hashlib

import pytest

from dreamlayer.contract import TAGS, Material, build_material, parse_time

NOW = "2026-10-01T08:00:00"


def test_tags_enum_exact():
    assert TAGS == ("selected", "rejected", "hesitated", "discarded", "unknown")


@pytest.mark.parametrize("tag", TAGS)
def test_canonical_tags_accepted(tag):
    r = build_material({"content": "x", "time": NOW, "tag": tag}, {}, 2000)
    assert r.material.tag == tag and r.warning is None


def test_tag_via_map_no_warning():
    r = build_material({"content": "x", "time": NOW, "tag": "drop"}, {"drop": "rejected"}, 2000)
    assert r.material.tag == "rejected" and r.warning is None


def test_it09_unknown_tag_gets_warning():
    r = build_material({"content": "x", "time": NOW, "tag": "drop"}, {}, 2000)
    assert r.material.tag == "unknown"
    assert r.warning and "drop" in r.warning


def test_missing_tag_defaults_unknown_without_warning():
    r = build_material({"content": "x", "time": NOW}, {}, 2000)
    assert r.material.tag == "unknown" and r.warning is None


def test_missing_content_drops():
    assert build_material({"time": NOW}, {}, 2000).material is None


def test_blank_content_drops():
    assert build_material({"content": "   ", "time": NOW}, {}, 2000).material is None


def test_bad_time_drops():
    assert build_material({"content": "x", "time": "不是时间"}, {}, 2000).material is None


def test_it04_long_with_summary_uses_summary():
    long = "字" * 2500
    r = build_material({"content": long, "time": NOW, "summary": "摘要内容"}, {}, 2000)
    m = r.material
    assert m.content == "摘要内容"
    assert m.from_summary is True and m.truncated is False
    assert m.raw == long  # raw 保留原文(调用方已脱敏)


def test_it04_long_without_summary_hard_truncates():
    long = "字" * 2500
    r = build_material({"content": long, "time": NOW}, {}, 2000)
    m = r.material
    assert m.content == "字" * 2000
    assert m.truncated is True and m.from_summary is False
    assert m.raw == long


def test_short_content_untouched():
    r = build_material({"content": "短文", "time": NOW}, {}, 2000)
    m = r.material
    assert m.content == "短文" and m.truncated is False and m.from_summary is False
    assert m.raw == "短文"


def test_key_prefers_id_else_content_hash():
    a = build_material({"id": "A", "content": "  hello  ", "time": NOW}, {}, 2000).material
    assert a.key == "A"
    b = build_material({"content": "  hello  ", "time": NOW}, {}, 2000).material
    assert b.key == hashlib.sha256("hello".encode("utf-8")).hexdigest()


def test_default_origin():
    r = build_material({"content": "x", "time": NOW}, {}, 2000)
    assert r.material.origin == "unknown"


def test_material_roundtrip():
    m = Material(id="a", content="c", time=parse_time(NOW), tag="rejected", origin="o",
                 summary=None, truncated=False, from_summary=False, raw="c")
    assert Material.from_dict(m.to_dict()) == m


def test_parse_time_variants():
    assert parse_time("2026-10-01T08:00:00") is not None
    assert parse_time("2026-10-01 08:00") is not None
    assert parse_time("2026-10-01") is not None
    assert parse_time("2026-10-01T08:00:00Z") is not None
    assert parse_time(None) is None
    assert parse_time("") is None
