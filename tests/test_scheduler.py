"""节律单测(C-7),含 IT-11。"""

from __future__ import annotations

from datetime import date, datetime, timedelta

from conftest import make_item, parse_meta, run_fake_once, write_seed_jsonl
from dreamlayer.scheduler import (
    last_journal_date,
    next_tick,
    phase_times,
    should_catchup,
)


def test_should_catchup_matrix():
    now0900 = datetime(2026, 10, 1, 9, 0)
    assert should_catchup(None, now0900) is True                      # 从未跑过
    assert should_catchup(date(2026, 9, 30), now0900) is False        # 昨晚有 journal
    assert should_catchup(date(2026, 9, 29), now0900) is True         # 更早缺失 -> 补
    assert should_catchup(date(2026, 10, 1), now0900) is False        # 今天已有
    assert should_catchup(None, datetime(2026, 10, 1, 4, 59)) is False  # 未过 05:00
    assert should_catchup(None, datetime(2026, 10, 1, 5, 0)) is True


def test_next_tick_with_cfg(cfg):
    times = phase_times(cfg)
    assert next_tick(datetime(2026, 10, 1, 1, 0), times) == (datetime(2026, 10, 1, 2, 30), "collect")
    assert next_tick(datetime(2026, 10, 1, 2, 30), times) == (datetime(2026, 10, 1, 3, 0), "dream")
    assert next_tick(datetime(2026, 10, 1, 3, 1), times) == (datetime(2026, 10, 1, 5, 0), "wake")
    assert next_tick(datetime(2026, 10, 1, 5, 1), times) == (datetime(2026, 10, 2, 2, 30), "collect")
    assert next_tick(datetime(2026, 10, 1, 23, 59), times) == (datetime(2026, 10, 2, 2, 30), "collect")


def test_last_journal_date(tmp_project):
    d = tmp_project["data"] / "journal"
    assert last_journal_date(d) is None
    d.mkdir(parents=True)
    (d / "2026-09-30.md").write_text("x", encoding="utf-8")
    (d / "2026-10-01.md").write_text("x", encoding="utf-8")
    (d / "not-a-date.md").write_text("x", encoding="utf-8")
    assert last_journal_date(d) == date(2026, 10, 1)


def test_it11_catchup_true_and_late_meta(tmp_project):
    # 纯函数半边:昨晚无 journal 且 now=09:00 -> True
    assert should_catchup(None, datetime(2026, 10, 1, 9, 0)) is True
    # 链路半边:补跑一夜,journal meta.late=true
    seed = write_seed_jsonl(
        tmp_project["data"] / "seed" / "demo_day.jsonl",
        [make_item(i) for i in range(25)],
    )
    _, text = run_fake_once(tmp_project["data"], tmp_project["config"], late=True)
    assert parse_meta(text)["late"] is True


def test_normal_run_marks_late_false(tmp_project):
    write_seed_jsonl(
        tmp_project["data"] / "seed" / "demo_day.jsonl",
        [make_item(i) for i in range(25)],
    )
    _, text = run_fake_once(tmp_project["data"], tmp_project["config"])
    assert parse_meta(text)["late"] is False


def test_catchup_not_needed_when_yesterday_exists():
    yesterday = date.today() - timedelta(days=1)
    assert should_catchup(yesterday, datetime.now()) is False
