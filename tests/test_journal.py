"""journal 单测(C-6),含 IT-07 的 journal 侧断言与 IT-10。"""

from __future__ import annotations

from datetime import date

import pytest

from conftest import parse_meta, parse_pairs
from dreamlayer.dreamer import MicroDream
from dreamlayer.journal import (
    META_FIELDS,
    REASON_NO_MATERIAL,
    render_journal,
    write_dreams,
    write_journal,
    read_dreams,
)
from dreamlayer.privacy import CloudPathError

DAY = date(2026, 10, 1)


def _dream(attempts=None):
    att = attempts or ["梦话一句。"]
    return MicroDream(
        pair=("ka", "kb"),
        persona="审计员的怀疑",
        raw=att[-1],
        meta={
            "temperature": 1.2,
            "attempts": att,
            "a": {"tag": "rejected", "origin": "daily-pipeline", "date": "09-28", "key": "ka"},
            "b": {"tag": "selected", "origin": "kb", "date": "10-01", "key": "kb"},
        },
    )


def _meta(**kw):
    base = {
        "pool": 25, "pairs": 1, "history_sampled": 2, "late": False,
        "origin_relaxed": 0, "time_relaxed": 1, "hard_relaxed": 0,
        "dropped": 0, "redacted": 1, "all_noise": False, "warnings": 0,
        "warnings_detail": [],
    }
    base.update(kw)
    return base


def test_template_fields_complete(tmp_path):
    p = write_journal(DAY, [_dream()], _meta(), journal_dir=tmp_path / "j")
    text = p.read_text(encoding="utf-8")
    assert text.startswith("# dream_journal · 2026-10-01")
    meta = parse_meta(text)
    for field in META_FIELDS:
        assert field in meta, field
    assert meta["late"] is False and meta["all_noise"] is False
    pairs = parse_pairs(text)
    assert len(pairs) == 1
    sec = text.split("## pair 01")[1]
    assert "[rejected · daily-pipeline 09-28]" in sec
    assert "[selected · kb 10-01]" in sec
    for line in (
        "persona: 审计员的怀疑",
        "raw: 梦话一句。",
        "verdict: unwoken",
        "observation:",
        "open_question:",
        "evidence: [ka, kb]",
    ):
        assert line in sec


def test_p0_verdicts_all_unwoken(tmp_path):
    dreams = [_dream(), _dream()]
    text = render_journal(DAY, dreams, _meta(pairs=2))
    assert "verdict: unwoken" in text
    assert text.count("verdict: unwoken") == 2


def test_no_dream_note(tmp_path):
    text = render_journal(DAY, [], _meta(pairs=0, reason=REASON_NO_MATERIAL))
    assert f"note: {REASON_NO_MATERIAL}" in text
    assert "## pair" not in text


def test_it07_attempts_block_rendered(tmp_path):
    refusal = "抱歉,我不能对素材展开联想。"
    good = "这两条碎片像两半被撕开的信。"
    text = render_journal(DAY, [_dream(attempts=[refusal, good])], _meta())
    assert refusal in text  # 第 1 次拒答原文保留在 journal
    assert good in text
    pairs = parse_pairs(text)
    assert pairs[0]["raw"] == good  # raw 为第 2 次结果


def test_it10_cloud_dir_refused(tmp_path):
    with pytest.raises(CloudPathError):
        write_journal(DAY, [], _meta(), journal_dir=tmp_path / "OneDrive" / "j")
    assert not (tmp_path / "OneDrive").exists()  # 不落盘,连目录都不建


def test_local_only_off_allows_any_dir(tmp_path):
    p = write_journal(DAY, [], _meta(journal_local_only=False),
                      journal_dir=tmp_path / "OneDrive" / "j")
    assert p.exists()  # 开关关闭时不再拒绝(P0 默认开)


def test_warnings_detail_rendered(tmp_path):
    meta = _meta(warnings=2, warnings_detail=["tag_unmapped:'drop'", "origin_switched:x"])
    text = render_journal(DAY, [], meta)
    assert "warnings_detail:" in text
    assert "tag_unmapped:'drop'" in text and "origin_switched:x" in text


def test_multiline_raw_rendered(tmp_path):
    d = _dream()
    d.raw = "第一句。\n第二句。"
    text = render_journal(DAY, [d], _meta())
    assert "raw: 第一句。\n  第二句。" in text


# ---------- P1:verdict 真值重写与梦话 jsonl ----------

def test_dict_dream_renders_real_verdict():
    d = {
        "record": "dream", "dream_id": "2026-10-01-01", "pair": ["ka", "kb"],
        "persona": "审计员的怀疑", "raw": "梦话一句。",
        "meta": {"temperature": 1.2, "attempts": ["梦话一句。"],
                 "a": {"tag": "rejected", "origin": "daily-pipeline", "date": "09-28", "key": "ka"},
                 "b": {"tag": "selected", "origin": "kb", "date": "10-01", "key": "kb"}},
        "verdict": "cross_time", "surprise": 0.71, "lane": "B",
        "observation": "两个阶段被放在一起", "open_question": "ka 里的 2.4 后来呢?",
    }
    text = render_journal(DAY, [d], _meta())
    assert "verdict: cross_time" in text
    assert "observation: 两个阶段被放在一起" in text
    assert "open_question: ka 里的 2.4 后来呢?" in text
    assert "verdict: unwoken" not in text


def test_dreams_jsonl_roundtrip(tmp_path):
    write_dreams(DAY, [_dream()], _meta(pairs=1), dreams_dir=tmp_path / "dr")
    night, dreams = read_dreams(tmp_path / "dr" / "2026-10-01.jsonl")
    assert night["pairs"] == 1
    assert len(dreams) == 1
    assert dreams[0]["dream_id"] == "2026-10-01-01"
    assert dreams[0]["meta"]["a"]["key"] == "ka"
    # wake 写回 verdict 后再次落盘,字段保留
    dreams[0]["verdict"] = "noise"
    write_dreams(DAY, dreams, _meta(pairs=1), dreams_dir=tmp_path / "dr")
    _, again = read_dreams(tmp_path / "dr" / "2026-10-01.jsonl")
    assert again[0]["verdict"] == "noise"


def test_read_dreams_missing_file(tmp_path):
    night, dreams = read_dreams(tmp_path / "nope.jsonl")
    assert night is None and dreams == []
