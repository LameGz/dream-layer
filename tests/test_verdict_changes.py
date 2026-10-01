"""红蓝对抗裁决的新增回归:D1 local_only / C5 对照实验 / C4 due 字段 / D3 豁免行。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from conftest import PRIVACY_YAML, RHYTHM_YAML, make_item, write_configs, write_seed_jsonl
from dreamlayer.config import load_config
from dreamlayer.engine import FakeEngine
from dreamlayer.scheduler import build_engine, dream_phase, collect_phase
from dreamlayer import reflux


# ---------- D1:privacy.mode=local_only 硬开关 ----------

def test_local_only_rejects_cloud_engine(tmp_project):
    p = tmp_project["config"] / "privacy.yaml"
    p.write_text(PRIVACY_YAML + "mode: local_only\n", encoding="utf-8")
    cfg = load_config(tmp_project["config"])
    with pytest.raises(RuntimeError, match="local_only"):
        build_engine(cfg, fake=False)  # 默认 base_url 是云端智谱 -> 拒绝


def test_local_only_allows_localhost_engine(tmp_project, monkeypatch):
    monkeypatch.setenv("DREAM_LLM_API_KEY", "test-key")
    p = tmp_project["config"] / "privacy.yaml"
    p.write_text(PRIVACY_YAML + "mode: local_only\n", encoding="utf-8")
    e = tmp_project["config"] / "engine.yaml"
    from conftest import ENGINE_YAML
    e.write_text(ENGINE_YAML.replace("https://open.bigmodel.cn/api/paas/v4",
                                     "http://127.0.0.1:11434/v1"), encoding="utf-8")
    cfg = load_config(tmp_project["config"])
    engine = build_engine(cfg, fake=False)  # 本机端点放行
    assert engine is not None


def test_open_mode_allows_cloud_engine(tmp_project, monkeypatch):
    monkeypatch.setenv("DREAM_LLM_API_KEY", "test-key")
    cfg = load_config(tmp_project["config"])
    assert cfg.privacy.mode == "open"
    assert build_engine(cfg, fake=False) is not None


def test_fake_engine_never_blocked(tmp_project):
    p = tmp_project["config"] / "privacy.yaml"
    p.write_text(PRIVACY_YAML + "mode: local_only\n", encoding="utf-8")
    cfg = load_config(tmp_project["config"])
    assert isinstance(build_engine(cfg, fake=True), FakeEngine)  # fake 永远放行


def test_bad_privacy_mode_rejected(tmp_project):
    p = tmp_project["config"] / "privacy.yaml"
    p.write_text(PRIVACY_YAML + "mode: bogus\n", encoding="utf-8")
    with pytest.raises(Exception, match="mode"):
        load_config(tmp_project["config"])


# ---------- C5:对照实验旁路 ----------

def _pool_with_anchors(cfg, tmp_project):
    from dreamlayer.contract import build_material
    from dreamlayer.pool import Pool

    pool = Pool(cfg.weights, data_dir=tmp_project["data"] / "pool")
    items = [make_item(i, tag=["rejected", "hesitated", "selected"][i % 3]) for i in range(20)]
    # 两对跨时锚点:共享专名 LX9000 / LX9001;tag 不同才能过硬约束
    items.append(make_item(100, tag="rejected", days_ago=30, content="上周的 LX9000 复盘记录"))
    items.append(make_item(101, tag="hesitated", content="今天的 LX9000 新进展"))
    items.append(make_item(102, tag="selected", days_ago=40, content="LX9001 立项被否"))
    items.append(make_item(103, tag="rejected", content="LX9001 再次出现"))
    for it in items:
        r = build_material(it, {}, 2000)
        assert r.material is not None
        pool.add(r.material)
    return pool


def test_anchor_mix_mode_pairs_anchor_items(cfg, tmp_project):
    pool = _pool_with_anchors(cfg, tmp_project)
    pairs, stats = pool.build_pairs(10, date.today(), mode="anchor_mix")
    keys = {tuple(sorted(pr.keys())) for pr in pairs}
    # 两对锚点对应被优先配出(anchor_n = 10//2 = 5,但只有 2 对锚点组合)
    anchor_keys = [k for pr in pairs for k in pr.keys()]
    assert any("t-100" in pr.keys() and "t-101" in pr.keys() for pr in pairs) or \
           any("t-102" in pr.keys() and "t-103" in pr.keys() for pr in pairs)
    assert len(pairs) >= 4


def test_random_mode_ignores_anchor_mode_side_effects(cfg, tmp_project):
    """默认 random 模式不受锚点逻辑影响(红线:默认路径零改动)。"""
    pool = _pool_with_anchors(cfg, tmp_project)
    pairs, stats = pool.build_pairs(10, date.today())  # 无 mode -> random
    assert len(pairs) == 10


def test_ab_arm_marked_in_dreams_jsonl(tmp_project):
    """experiment.ab 开启时,night meta 按日期序数标 arm A/B。"""
    write_seed_jsonl(tmp_project["data"] / "seed" / "demo_day.jsonl",
                     [make_item(i) for i in range(25)])
    rhythm = RHYTHM_YAML + "experiment: { ab: true }\n"
    write_configs(tmp_project["config"], rhythm_yaml=rhythm)
    cfg = load_config(tmp_project["config"])
    from dreamlayer.scheduler import build_collectors
    cols = build_collectors(cfg, tmp_project["data"])
    pool, cmeta = collect_phase(cfg, cols, tmp_project["data"])
    dream_phase(cfg, FakeEngine(), tmp_project["data"], collect_meta=cmeta, pool=pool)
    from dreamlayer.journal import read_dreams
    night, _ = read_dreams(tmp_project["data"] / "dreams" / f"{date.today().isoformat()}.jsonl")
    assert night["experiment"] in ("A", "B")


def test_experiment_bad_value_rejected(tmp_project):
    p = tmp_project["config"] / "rhythm.yaml"
    # YAML 陷阱:ab: yes 会被解析成 True;必须用字符串值才会被类型校验拦下
    p.write_text(RHYTHM_YAML + 'experiment: { ab: "yes" }\n', encoding="utf-8")
    with pytest.raises(Exception, match="experiment"):
        load_config(tmp_project["config"])


def test_ab_arm_alternates_by_dreamed_nights_not_calendar(tmp_project):
    """终审问题 1:arm 交替按"已做梦夜数"奇偶;静默(pairs=0)的夜不占名额。"""
    write_seed_jsonl(tmp_project["data"] / "seed" / "demo_day.jsonl",
                     [make_item(i) for i in range(25)])
    rhythm = RHYTHM_YAML + "experiment: { ab: true }\n"
    write_configs(tmp_project["config"], rhythm_yaml=rhythm)
    cfg = load_config(tmp_project["config"])
    from dreamlayer.journal import write_dreams
    from dreamlayer.scheduler import build_collectors

    today_file = tmp_project["data"] / "dreams" / f"{date.today().isoformat()}.jsonl"

    def run_and_get_arm():
        today_file.unlink(missing_ok=True)  # 清掉上次 run 的当日记录,只看铺好的历史
        cols = build_collectors(cfg, tmp_project["data"])
        pool, cmeta = collect_phase(cfg, cols, tmp_project["data"])
        dream_phase(cfg, FakeEngine(), tmp_project["data"], collect_meta=cmeta, pool=pool)
        from dreamlayer.journal import read_dreams
        night, _ = read_dreams(today_file)
        return night["experiment"]

    # 无历史 -> 第 0 个做梦夜 -> A
    assert run_and_get_arm() == "A"

    # 铺 1 个做梦夜(pairs>0)+ 1 个静默夜(pairs=0):dreamed=1 -> B
    write_dreams(date(2026, 9, 28), [], {"pairs": 10},
                 dreams_dir=tmp_project["data"] / "dreams")
    write_dreams(date(2026, 9, 29), [], {"pairs": 0},
                 dreams_dir=tmp_project["data"] / "dreams")
    assert run_and_get_arm() == "B"

    # 再铺 1 个做梦夜:dreamed=2 -> A(静默夜不参与交替)
    write_dreams(date(2026, 9, 30), [], {"pairs": 12},
                 dreams_dir=tmp_project["data"] / "dreams")
    assert run_and_get_arm() == "A"


# ---------- C4:trend due 字段 ----------

def test_trend_confirm_gets_due_field(tmp_path):
    entry = reflux.append_confirm(tmp_path, "2026-10-01-01", "trend", None)
    due = date.fromisoformat(entry["due"])
    assert due == date.today() + timedelta(days=14)
    assert entry["reviewed"] is False
    # recall/cross_time 不带 due
    entry2 = reflux.append_confirm(tmp_path, "2026-10-01-02", "recall", None)
    assert "due" not in entry2


def test_pending_trend_reviews(tmp_path):
    from dreamlayer.metrics import pending_trend_reviews

    reflux.append_confirm(tmp_path, "2026-10-01-01", "trend", None)
    # 今天未到期(14 天后才到期)
    assert pending_trend_reviews(tmp_path, date.today()) == []
    # 15 天后到期出现
    future = date.today() + timedelta(days=15)
    pending = pending_trend_reviews(tmp_path, future)
    assert len(pending) == 1 and pending[0]["dream_id"] == "2026-10-01-01"
    # reviewed=True 后不再出现
    f = tmp_path / "reflux_log.jsonl"
    lines = [json.loads(ln) for ln in f.read_text(encoding="utf-8").splitlines()]
    lines[0]["reviewed"] = True
    f.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in lines) + "\n", encoding="utf-8")
    assert pending_trend_reviews(tmp_path, future) == []
