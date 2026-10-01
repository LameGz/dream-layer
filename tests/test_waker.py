"""waker 单测(FR-C):分词 / surprise 公式 / 稀有锚点 / 两道闸 / top3 / 降级路径。"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta

import pytest

from conftest import WakeAwareEngine
from dreamlayer.contract import build_material
from dreamlayer.waker import (
    IMPERATIVE_MARKS,
    build_prompt,
    grounding_ok,
    imperative_ok,
    lane_b_anchor,
    numbers,
    parse_wake_response,
    surprise_of,
    tokenize,
    wake,
)


def mat(i, content, tag="rejected", origin="daily-pipeline", days_ago=0):
    t = (datetime.now() - timedelta(days=days_ago)).isoformat()
    r = build_material({"id": f"w-{i}", "content": content, "time": t, "tag": tag,
                        "origin": origin}, {}, 2000)
    assert r.material is not None
    return r.material


class FakePool:
    """waker 需要的池最小面:all_materials + material。"""

    def __init__(self, mats):
        self.mats = {m.key: m for m in mats}

    def all_materials(self):
        return list(self.mats.values())

    def material(self, key):
        return self.mats.get(key)


def dream(i, key_a, key_b, raw):
    return {"dream_id": f"2026-10-01-{i:02d}", "pair": [key_a, key_b],
            "persona": "审计员的怀疑", "raw": raw, "meta": {}}


# ---------- 分词 ----------

def test_tokenize_bigram_latin_and_stopwords():
    toks = tokenize("Laya 2.4 扩散激活的笔记")
    assert "扩散" in toks and "散激" in toks and "激活" in toks
    assert "laya" in toks
    assert "的" not in toks  # 停用词


def test_surprise_formula_exact():
    a = mat(1, "aa bb", origin="x", days_ago=45)
    b = mat(2, "aa bb", origin="y", days_ago=0)  # Δ45 天 -> time_span 0.5;origin 不同 -> 1.0
    s, o, t, n = surprise_of("aa bb", a, b)  # 梦话词全在素材里 -> novelty 0
    assert (o, round(t, 6), n) == (1.0, 0.5, 0.0)
    assert s == pytest.approx(0.4 * 1.0 + 0.3 * 0.5 + 0.3 * 0.0)
    s2, *_ = surprise_of("aa bb", mat(3, "aa bb", origin="x", days_ago=0), a)  # 同 origin,Δ45 天
    assert s2 == pytest.approx(0.3 * 0.5)


def test_surprise_novelty_counts_new_words():
    a = mat(1, "aa bb", origin="x")
    b = mat(2, "aa bb", origin="x")
    s, _, _, n = surprise_of("aa 新词 cc", a, b)  # 3 词里 2 个新 -> 2/3;同 origin 同日 -> 全靠 novelty
    assert n == pytest.approx(2 / 3)
    assert s == pytest.approx(0.3 * 2 / 3)


# ---------- 稀有锚点 ----------

def test_numbers_anchor_min_digits():
    """红队 C1:"2"不配当锚点;年份/版本号/小数才配。"""
    assert numbers("升级到 2 版和 2.4 与 2026 年") == {"2.4", "2026"}
    assert numbers("有 10 处和 3 处") == set()


def test_lane_b_anchor_numbers_and_proper():
    a = mat(1, "Laya 2.4 的邻近带观察", origin="x")
    b = mat(2, "Laya 2.4 再次出现", origin="y")
    anchor = lane_b_anchor(a, b, df_counts={}, total=2)
    assert "2.4" in anchor["numbers"]
    assert "laya" in anchor["proper"]
    assert anchor["strong"] is True


def test_lane_b_anchor_rare_token_pinned_to_few_sharers():
    """红队 C2:稀有钉死在"恰好少数素材共享";出现次数超 5% 上限的不算稀有。"""
    rare_a = mat(1, "青鸾计划复盘", origin="x")
    rare_b = mat(2, "青鸾计划启动", origin="y")
    # 池子 100 条,cap=5:"青鸾"出现 50 次 -> 不稀有
    counts_common = {"青鸾": 50, "鸾计": 50, "计划": 50}
    assert lane_b_anchor(rare_a, rare_b, counts_common, 100)["rare"] == []
    # 恰好 2 条共享 -> 稀有(弱锚点:无数字/专名时 strong=False)
    counts_rare = {"青鸾": 2, "鸾计": 2, "计划": 2}
    anchor = lane_b_anchor(rare_a, rare_b, counts_rare, 100)
    assert anchor["rare"] and anchor["strong"] is False


# ---------- 两道闸 ----------

def test_imperative_gate():
    for mark in IMPERATIVE_MARKS:
        assert not imperative_ok(f"下一步 {mark}看看")
    # 红队 C3:英文建议同样被拦
    assert not imperative_ok("You should check the pipeline logs.")
    assert not imperative_ok("Next step: verify the token rotation.")
    assert imperative_ok("LX01 那条线后来发生了什么?")


def test_grounding_gate_needs_specific_mention():
    a = mat(1, "Laya 2.4 的邻近带", origin="x")
    b = mat(2, "无关素材", origin="y")
    assert grounding_ok("2.4 之后呢?", a, b, {}, 2)
    assert grounding_ok("laya 的后续?", a, b, {}, 2)
    assert not grounding_ok("泛泛而谈没有任何指称", a, b, {}, 2)


def test_parse_wake_response_shapes():
    ids = {"2026-10-01-01"}
    assert parse_wake_response('[{"id": "2026-10-01-01", "observation": "o", "open_question": "q"}]', ids)
    assert parse_wake_response('前缀文字 [ {"id": "2026-10-01-01", "observation": "o", "open_question": "q"} ] 后缀', ids)
    assert parse_wake_response("完全不是 JSON", ids) is None
    assert parse_wake_response("", ids) is None


def test_build_prompt_starts_with_wake_mark():
    a, b = mat(1, "x", origin="x"), mat(2, "y", origin="y")
    prompt = build_prompt([{"dream_id": "2026-10-01-01", "raw": "梦", "mat_a": a, "mat_b": b}])
    assert prompt.startswith("醒来筛选")
    assert "id=2026-10-01-01" in prompt


# ---------- wake 全流程 ----------

def _lx_pool(n=24):
    mats = [mat(i, f"素材 LX{i:02d} 的独立上下文。", tag=["rejected", "hesitated"][i % 2],
                origin=["x", "y"][i % 2]) for i in range(n)]
    pool = FakePool(mats)
    dreams = [dream(i + 1, mats[2 * i].key, mats[2 * i + 1].key,
                    f"(fake dream #{i}) LX{2 * i:02d} 撞上 LX{2 * i + 1:02d}。")
              for i in range(n // 2)]
    return pool, dreams


def test_wake_top3_reflux_and_overlay():
    from conftest import lx_wake_response

    pool, dreams = _lx_pool()
    engine = WakeAwareEngine(wake_response=lx_wake_response)
    refluxes, verdicts, warnings = wake(dreams, pool, engine, max_reflux=3)
    assert warnings == []
    assert len(refluxes) == 3
    assert all(r.verdict in ("trend", "cross_time") for r in refluxes)
    assert all(r.observation and r.open_question for r in refluxes)
    assert len(verdicts) == len(dreams)  # 全量 overlay
    refluxed_ids = {r.dream_id for r in refluxes}
    assert all(verdicts[d["dream_id"]]["verdict"] == "noise"
               for d in dreams if d["dream_id"] not in refluxed_ids)


def test_wake_parse_failure_degrades_to_all_noise():
    pool, dreams = _lx_pool(8)
    refluxes, verdicts, warnings = wake(dreams, pool, WakeAwareEngine(wake_response="不是 JSON"))
    assert refluxes == []
    assert all(v["verdict"] == "noise" for v in verdicts.values())
    assert "wake_parse_failed" in warnings


def test_wake_missing_material_marks_noise():
    pool, dreams = _lx_pool(4)
    dreams[0]["pair"] = ["no-such-key", dreams[0]["pair"][1]]
    refluxes, verdicts, warnings = wake(
        dreams, pool, WakeAwareEngine(wake_response="也不是 JSON"))
    assert refluxes == []
    assert "wake_missing_material:2026-10-01-01" in "".join(warnings)


def test_wake_imperative_answer_gated():
    pool, dreams = _lx_pool(4)
    resp = json.dumps([
        {"id": d["dream_id"], "observation": "观察", "open_question": "建议你先看 LX。"}
        for d in dreams
    ], ensure_ascii=False)
    refluxes, verdicts, _ = wake(dreams, pool, WakeAwareEngine(wake_response=resp))
    assert refluxes == []  # 全部命中祈使 -> 降 noise


def test_wake_grounded_answer_passes():
    pool, dreams = _lx_pool(2)
    resp = json.dumps([
        {"id": d["dream_id"], "observation": "观察", "open_question": "LX00 那条线后来发生了什么?"}
        for d in dreams
    ], ensure_ascii=False)
    refluxes, verdicts, _ = wake(dreams, pool, WakeAwareEngine(wake_response=resp))
    assert len(refluxes) == 1
    # LX00 是强锚点(拉丁专名)→ Lane B 直通,verdict 锁 cross_time;最终判定属于人
    assert refluxes[0].verdict == "cross_time"


def test_wake_lane_b_cross_time_locked():
    # 两条素材共享数字锚点 -> Lane B 直通,verdict 锁 cross_time
    a = mat(1, "Laya 2.4 邻近带观察", origin="x", days_ago=40)
    b = mat(2, "Laya 2.4 又出现了", origin="x", days_ago=0)
    pool = FakePool([a, b, mat(3, "无关内容甲", origin="y"), mat(4, "无关内容乙", origin="y")])
    dreams = [dream(1, a.key, b.key, "两条都指向 2.4。")]
    refluxes, verdicts, _ = wake(
        dreams, pool, WakeAwareEngine(wake_response="无法解析"))
    assert refluxes == []  # 解析失败仍降 noise,但……
    # 换可解析响应:cross_time 锁定不依赖 Lane A surprise
    resp = json.dumps([{"id": "2026-10-01-01", "observation": "2.4 的两阶段",
                        "open_question": "2.4 这次为什么会再出现?"}], ensure_ascii=False)
    refluxes, verdicts, _ = wake(dreams, pool, WakeAwareEngine(wake_response=resp))
    assert len(refluxes) == 1 and refluxes[0].verdict == "cross_time"
    assert refluxes[0].lane == "B"
