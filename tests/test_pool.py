"""素材池单测(C-3),含 IT-05 / IT-06a / IT-06b / IT-08。"""

from __future__ import annotations

import random
from datetime import date, datetime, timedelta

import pytest

from conftest import make_item
from dreamlayer.config import load_config
from dreamlayer.contract import build_material
from dreamlayer.pool import Pool, time_bucket


@pytest.fixture
def pool(tmp_project, cfg):
    def _make(items, seed=7):
        p = Pool(cfg.weights, data_dir=tmp_project["data"] / "pool", rng=random.Random(seed))
        for it in items:
            r = build_material(it, {}, cfg.rhythm.content_max_chars)
            assert r.material is not None, r.warning
            p.add(r.material)
        return p
    return _make


def test_add_idempotent_same_id(pool):
    p = pool([make_item(1), make_item(1)])
    assert len(p) == 1


def test_it05_dedup_id_vs_no_id_same_content(pool):
    a = make_item(1)
    a["id"] = "A"
    b = dict(a)
    b.pop("id")  # 相同 content,一次带 id 一次不带
    p = pool([a, b])
    assert len(p) == 1


def test_dedup_plain_content_dup(pool):
    a = make_item(1)
    b = dict(a)
    b["id"] = "other-id"  # id 不同但 content 相同
    p = pool([a, b])
    assert len(p) == 1


def test_count_on_buckets(pool):
    today = date.today()
    p = pool([make_item(1), make_item(2), make_item(3, days_ago=0)])
    assert p.count_on(today) == 3
    old = make_item(4)
    old["time"] = (datetime.now() - timedelta(days=5)).isoformat()
    p.add(build_material(old, {}, 2000).material)
    assert p.count_on(today) == 3
    assert len(p) == 4


def test_time_bucket_values(pool):
    today = date.today()

    def mat(days_ago):
        m = build_material(make_item(days_ago, days_ago=days_ago), {}, 2000).material
        return time_bucket(m, today)

    assert mat(0) == "today"
    assert mat(1) == "1-7d"
    assert mat(7) == "1-7d"
    assert mat(8) == "8-30d"
    assert mat(30) == "8-30d"
    assert mat(31) == "31-90d"
    assert mat(90) == "31-90d"


def test_sample_history_window_and_cap(pool):
    items = [make_item(i, days_ago=i + 1) for i in range(5)]  # 1-5 天前,全在窗口内
    old100 = make_item(100, days_ago=100)
    p = pool(items + [old100])
    today = date.today()
    got = p.sample_history(3, 90, today)
    assert len(got) == 3
    assert all(m.time.date() != today for m in got)
    assert all((today - m.time.date()).days <= 90 for m in got)
    got_all = p.sample_history(50, 90, today)
    assert len(got_all) == 5  # 100 天前那条不在窗口内


def _mixed_items(n=45):
    tags = ["selected", "rejected", "hesitated"]
    origins = ["daily-pipeline", "kb", "zcode"]
    return [make_item(i, tag=tags[i % 3], origin=origins[i % 3]) for i in range(n)]


def test_it06a_mixed_pool_respects_hard_counts_soft(pool, cfg):
    p = pool(_mixed_items(45))
    today = date.today()
    pairs, stats = p.build_pairs(20, today, constraints=cfg.rhythm.pair_constraints)
    assert len(pairs) == 20
    assert stats.hard_relaxed == 0
    assert all(pr.a.tag != pr.b.tag for pr in pairs)  # 硬约束(tag 不同)全部满足
    # 软约束 relaxed 计数如实:重算应与 stats 一致
    o_rel = sum(1 for pr in pairs if pr.a.origin == pr.b.origin)
    t_rel = sum(1 for pr in pairs if time_bucket(pr.a, today) == time_bucket(pr.b, today))
    assert stats.origin_relaxed == o_rel
    assert stats.time_relaxed == t_rel


def test_it06b_single_tag_relaxes_hard_never_stalls(pool, cfg):
    items = [make_item(i, tag="rejected") for i in range(45)]
    p = pool(items)
    pairs, stats = p.build_pairs(20, date.today(), constraints=cfg.rhythm.pair_constraints)
    assert len(pairs) == 20
    assert stats.hard_relaxed == 20  # 每对都放宽硬约束并如实计数
    assert all(pr.a.key != pr.b.key for pr in pairs)


def test_single_night_no_material_repeats(pool):
    p = pool(_mixed_items(45))
    pairs, _ = p.build_pairs(20, date.today())
    keys = [k for pr in pairs for k in pr.keys()]
    assert len(keys) == 2 * len(pairs)
    assert len(set(keys)) == len(keys)  # G6:同一素材最多入 1 对


def test_pairs_capped_by_pool_size(pool):
    p = pool([make_item(i) for i in range(5)])
    pairs, _ = p.build_pairs(20, date.today())
    assert len(pairs) == 2  # G6 封顶:floor(5/2)


def test_history_mixed_into_candidates(pool):
    items = [make_item(i) for i in range(25)]
    for j in range(5):  # 5 条历史
        it = make_item(50 + j)
        it["time"] = (datetime.now() - timedelta(days=10 + j)).isoformat()
        items.append(it)
    p = pool(items)
    pairs, stats = p.build_pairs(20, date.today())
    assert stats.history_sampled == 5
    assert len(pairs) == 15  # (25+5)//2


def test_it08_coverage_boost_30_days(pool, cfg):
    p = pool([make_item(1)])
    today = date.today()
    m = p.all_materials()[0]
    base = cfg.weights.tag_weights[m.tag]
    # 刚入梦:无 boost
    p.record_coverage([m.key], today - timedelta(days=1))
    assert p.weight_of(m, today) == pytest.approx(base)
    # 30 天未梦(IT-08):基础权重 ×2.0
    p.record_coverage([m.key], today - timedelta(days=30))
    assert p.weight_of(m, today) == pytest.approx(base * cfg.weights.coverage_boost_factor)
    # 从未入梦:同样 boost
    p2 = pool([make_item(2)])
    m2 = p2.all_materials()[0]
    assert p2.weight_of(m2, today) == pytest.approx(
        cfg.weights.tag_weights[m2.tag] * cfg.weights.coverage_boost_factor
    )


def test_coverage_persisted_to_json(tmp_project, cfg):
    p = Pool(cfg.weights, data_dir=tmp_project["data"] / "pool", rng=random.Random(1))
    m = build_material(make_item(1), {}, 2000).material
    p.add(m)
    p.record_coverage([m.key], date.today())
    import json

    data = json.loads((tmp_project["data"] / "pool" / "coverage.json").read_text(encoding="utf-8"))
    assert m.key in data
    assert data[m.key] == [date.today().isoformat(), 1]


def test_pool_reloads_from_disk(tmp_project, cfg):
    m = build_material(make_item(1), {}, 2000).material
    p1 = Pool(cfg.weights, data_dir=tmp_project["data"] / "pool", rng=random.Random(1))
    p1.add(m)
    p2 = Pool(cfg.weights, data_dir=tmp_project["data"] / "pool", rng=random.Random(1))
    assert len(p2) == 1  # 重启后从 jsonl 恢复
    assert not p2.add(m)  # 幂等:重复投递不再入池


# ---------- FR-A8 滚动清理 ----------

def _mat(i, days_ago):
    t = (datetime.now() - timedelta(days=days_ago)).isoformat()
    r = build_material({"id": f"p-{i}", "content": f"素材 {i}", "time": t, "tag": "rejected",
                        "origin": "x"}, {}, 2000)
    return r.material


def test_prune_removes_old_files_and_coverage(tmp_project, cfg):
    pool = Pool(cfg.weights, data_dir=tmp_project["data"] / "pool")
    old, fresh = _mat(1, 95), _mat(2, 0)
    pool.add(old)
    pool.add(fresh)
    pool.record_coverage([old.key, fresh.key], date.today())
    today = date.today()
    # 清理窗口外:无动作
    assert pool.prune(today - timedelta(days=120)) == 0
    # 90 天窗口:old 被清,fresh 保留
    assert pool.prune(today - timedelta(days=cfg.privacy.retention_days)) == 1
    assert len(pool) == 1
    assert pool.material(old.key) is None
    assert pool.material(fresh.key) is not None
    assert old.key not in pool.coverage
    # 日桶文件被删除,当日桶保留
    assert not (tmp_project["data"] / "pool" / f"{(today - timedelta(days=95)).isoformat()}.jsonl").exists()
    assert (tmp_project["data"] / "pool" / f"{today.isoformat()}.jsonl").exists()
    # 重启后不复活
    assert len(Pool(cfg.weights, data_dir=tmp_project["data"] / "pool")) == 1
