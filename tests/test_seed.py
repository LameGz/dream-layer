"""demo 种子规格检查(PRD §3)。"""

from __future__ import annotations

import json
from collections import Counter
from datetime import date, timedelta
from pathlib import Path

from conftest import PROJECT_ROOT

SEED_DIR = PROJECT_ROOT / "data" / "seed"


def _items():
    lines = (SEED_DIR / "demo_day.jsonl").read_text(encoding="utf-8").splitlines()
    return [json.loads(ln) for ln in lines if ln.strip()]


def test_seed_exists_with_45_lines():
    items = _items()
    assert len(items) >= 45


def test_seed_feeds_twenty_pairs():
    """FR-G2:34 条今日唯一 + >=6 条历史(90 天窗口) -> 40 候选 -> 满 20 对。"""
    items = _items()
    today_items = [it for it in items if it.get("days_ago", 0) == 0]
    older = [it for it in items if 0 < it.get("days_ago", 0) <= 90]
    unique_today = len({it["content"] for it in today_items})
    assert unique_today + min(6, len(older)) >= 40


def test_seed_at_least_3_origins_and_4_tags():
    items = _items()
    assert len({it["origin"] for it in items}) >= 3
    assert len({it["tag"] for it in items}) >= 4


def test_seed_has_two_overlong_one_with_summary():
    items = _items()
    overs = [it for it in items if len(it["content"]) > 2000]
    assert len(overs) >= 2
    assert any(it.get("summary") for it in overs)
    assert any(not it.get("summary") for it in overs)


def test_seed_cross_time_shared_anchor_over_30_days():
    items = _items()
    today = date.today()
    days = [
        (today - timedelta(days=it["days_ago"])).toordinal()
        for it in items
        if "青鸾计划" in it["content"]
    ]
    gaps = [a - b for a in days for b in days if a > b]
    assert gaps and max(gaps) > 30


def test_seed_has_duplicate_content():
    items = _items()
    counter = Counter(it["content"] for it in items)
    assert counter.most_common(1)[0][1] >= 2


def test_seed_has_sk_key_sample():
    items = _items()
    assert any("sk-" in it["content"] for it in items)


def test_seed_items_survive_redaction_ratio():
    """种子里的每条 content/summary 打码占比必须 <= 0.3,否则会被整条丢弃、IT-01 计数失真。"""
    from dreamlayer.privacy import redact

    patterns = [
        "sk-[A-Za-z0-9]{16,}",
        "AKIA[0-9A-Z]{16}",
        "ghp_[A-Za-z0-9]{30,}",
        r"(?i)(password|passwd|secret|token)\s*[:=]\s*\S{6,}",
    ]
    for it in _items():
        _, r = redact(it["content"], patterns)
        assert r <= 0.3, (it["id"], r)
        if it.get("summary"):
            _, rs = redact(it["summary"], patterns)
            assert rs <= 0.3, (it["id"], rs)


def test_secret_token_log_exists_with_secret():
    f = SEED_DIR / "secret_token.log"
    assert f.exists()
    text = f.read_text(encoding="utf-8")
    assert "token" in text.lower()
    assert "NEVER-READ-MARKER" in text
