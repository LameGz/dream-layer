"""入梦引擎单测(C-5),含 IT-07 / IT-12。FakeEngine,零网络(G4)。"""

from __future__ import annotations

import random
from datetime import datetime

from dreamlayer.contract import build_material
from dreamlayer.dreamer import SKELETON_LINES, MicroDream, build_prompt, dream_night
from dreamlayer.engine import FakeEngine, REFUSAL_PATTERNS, is_refusal

NOW = "2026-10-01T08:00:00"
PERSONAS = ["竞争对手的眼光", "假设十年后回看", "悲观主义者的直觉"]


def mat(idx, content=None, tag="rejected", origin="daily-pipeline"):
    return build_material(
        {"id": f"m-{idx}", "content": content or f"素材{idx}正文", "time": NOW,
         "tag": tag, "origin": origin},
        {}, 2000,
    ).material


def one_pair():
    from dreamlayer.pool import Pair

    return Pair(mat(1), mat(2, tag="selected", origin="kb"))


def test_refusal_patterns_exact():
    assert REFUSAL_PATTERNS == ("我无法", "作为AI", "作为 AI", "抱歉,我不能")


def test_is_refusal_hits_each_pattern():
    for p in REFUSAL_PATTERNS:
        assert is_refusal(f"开头{p}。结尾")
    assert not is_refusal("正常的梦话。")
    assert not is_refusal("")


def test_it12_honest_valve_not_treated_as_refusal():
    eng = FakeEngine("这两条没碰出东西")
    dreams = dream_night([one_pair()], eng, PERSONAS, rng=random.Random(1))
    d = dreams[0]
    assert d.raw == "这两条没碰出东西"
    assert len(d.meta["attempts"]) == 1  # 不重试、不判失败


def test_it07_refusal_retry_keeps_all_attempts():
    refusal = "抱歉,我不能对素材展开联想。"
    good = "这两条碎片像两半被撕开的信。"
    eng = FakeEngine([refusal, good])
    dreams = dream_night([one_pair()], eng, PERSONAS, temperature=1.2, refusal_retry=1,
                         rng=random.Random(1))
    d = dreams[0]
    assert d.raw == good  # raw 为第 2 次结果
    assert d.meta["attempts"] == [refusal, good]  # 每次尝试都保留
    assert d.meta["temperature"] == 1.2
    assert len(eng.calls) == 2


def test_refusal_retry_respects_limit():
    eng = FakeEngine(["抱歉,我不能", "抱歉,我不能", "ok"])  # refusal_retry=1 -> 只两次
    dreams = dream_night([one_pair()], eng, PERSONAS, refusal_retry=1, rng=random.Random(1))
    assert dreams[0].raw == "抱歉,我不能"
    assert len(dreams[0].meta["attempts"]) == 2
    assert len(eng.calls) == 2


def test_retry_swaps_persona():
    eng = FakeEngine(["我无法", "正常的联想"])
    dreams = dream_night([one_pair()], eng, PERSONAS, refusal_retry=1, rng=random.Random(0))
    d = dreams[0]
    assert d.raw == "正常的联想"
    assert d.persona in PERSONAS  # 重试后的 persona 来自人格池


def test_prompt_contains_skeleton_verbatim_and_persona():
    a, b = mat(1), mat(2, tag="selected", origin="kb")
    prompt = build_prompt(a, b, "审计员的怀疑")
    for line in SKELETON_LINES:
        assert line in prompt  # 骨架逐字照抄(含诚实阀门句)
    assert "审计员的怀疑" in prompt
    assert "素材1正文" in prompt and "素材2正文" in prompt
    assert "origin=daily-pipeline" in prompt and "tag=selected" in prompt


def test_prompt_leaks_nothing_beyond_content_and_meta():
    a = build_material({"id": "secret-id-42", "content": "正文A", "time": NOW,
                        "tag": "rejected", "origin": "o", "summary": None}, {}, 2000).material
    a.raw = "这是不该出现在 prompt 里的原始长文"
    b = mat(2, tag="selected", origin="kb")
    prompt = build_prompt(a, b, "x")
    assert "secret-id-42" not in prompt
    assert "原始长文" not in prompt


def test_dream_night_passes_temperature_and_max_tokens():
    eng = FakeEngine()
    dream_night([one_pair()], eng, PERSONAS, temperature=1.2, max_tokens=300,
                concurrency=1, rng=random.Random(1))
    call = eng.calls[0]
    assert call["temperature"] == 1.2
    assert call["max_tokens"] == 300


def test_dream_night_parallel_preserves_order_and_pair_keys():
    pairs = [one_pair(), one_pair().__class__(mat(3), mat(4, tag="selected", origin="zcode"))]
    eng = FakeEngine()
    dreams = dream_night(pairs, eng, PERSONAS, concurrency=2, rng=random.Random(1))
    assert [d.pair for d in dreams] == [p.keys() for p in pairs]
    assert len(eng.calls) == 2


def test_micro_dream_shape():
    d = MicroDream(pair=("a", "b"), persona="x", raw="y", meta={})
    assert d.pair == ("a", "b") and d.meta == {}
