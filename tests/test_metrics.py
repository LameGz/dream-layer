"""metrics 单测(FR-I1/I2):五指标统计 + 保底产物 SVG。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from dreamlayer.metrics import (
    band_svg,
    drift_svg,
    journal_stats,
    reflux_stats,
    report_text,
    write_report,
)


def _seed_pool(pool_dir: Path, n_days=20, per_day=3):
    pool_dir.mkdir(parents=True, exist_ok=True)
    today = date.today()
    lines = []
    k = 0
    for d in range(n_days):
        for j in range(per_day):
            day = today - timedelta(days=d)
            lines.append(json.dumps({
                "id": f"m-{k}", "content": f"邻近带素材 Laya 2.4 第 {k} 条观察记录 {d}",
                "time": datetime(day.year, day.month, day.day, 8, 0).isoformat(),
                "tag": ["rejected", "hesitated", "discarded"][k % 3],
                "origin": "daily-pipeline",
            }, ensure_ascii=False))
            k += 1
    (pool_dir / "pool.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _seed_journal(journal_dir: Path, days):
    journal_dir.mkdir(parents=True, exist_ok=True)
    for d, pairs in days.items():
        day = date.today() - timedelta(days=d)
        (journal_dir / f"{day.isoformat()}.md").write_text(
            f"# dream_journal · {day.isoformat()}\n"
            f"meta: pool=30 pairs={pairs} history_sampled=6 late=false origin_relaxed=0 "
            f"time_relaxed=0 hard_relaxed=0 dropped=0 redacted=0 all_noise={pairs == 0} warnings=0\n",
            encoding="utf-8",
        )


def _seed_reflux(data_dir: Path, entries):
    f = data_dir / "reflux_log.jsonl"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(
        "\n".join(json.dumps(e, ensure_ascii=False) for e in entries) + "\n", encoding="utf-8"
    )


def test_journal_stats_counts_dreamed_nights(tmp_path):
    _seed_journal(tmp_path / "journal", {0: 20, 1: 12, 2: 0})
    s = journal_stats(tmp_path / "journal")
    assert s == {"nights_total": 3, "nights_dreamed": 2, "pairs_total": 32}


def test_reflux_stats_per_verdict(tmp_path):
    _seed_reflux(tmp_path, [
        {"verdict": "recall", "confirmed_at": datetime(2026, 9, 20).isoformat()},
        {"verdict": "trend", "confirmed_at": datetime(2026, 9, 25).isoformat()},
        {"verdict": "cross_time", "confirmed_at": datetime(2026, 9, 28).isoformat()},
    ])
    s = reflux_stats(tmp_path)
    assert s == {"total": 3, "recall": 1, "trend": 1, "cross_time": 1}


def test_report_text_contains_five_metrics(tmp_path):
    _seed_journal(tmp_path / "journal", {0: 20, 1: 0})
    _seed_reflux(tmp_path, [
        {"verdict": "recall", "confirmed_at": datetime.now().isoformat()},
    ])
    text = report_text(tmp_path)
    for key in ("误杀回收数", "趋势预警命中", "跨时关联确认", "梦产率", "存在感指标"):
        assert key in text
    assert "有效回流:1" in text and "入梦夜数:1" in text


def test_drift_svg_needs_two_weeks(tmp_path):
    _seed_pool(tmp_path / "pool", n_days=20)
    svg = drift_svg(tmp_path / "pool")
    assert svg and svg.startswith("<svg") and "被拒池主题漂移" in svg
    assert svg.count("<polyline") >= 1
    # 数据不足(单周)不产图
    small = tmp_path / "small"
    _seed_pool(small, n_days=3)
    assert drift_svg(small / "pool") is None


def test_band_svg_daily_counts(tmp_path):
    _seed_pool(tmp_path / "pool", n_days=10)
    svg = band_svg(tmp_path / "pool")
    assert svg and svg.startswith("<svg") and "阈值邻近带聚合曲线" in svg


def test_write_report_outputs(tmp_path):
    _seed_pool(tmp_path / "pool", n_days=20)
    _seed_journal(tmp_path / "journal", {0: 20, 1: 12})
    _seed_reflux(tmp_path, [{"verdict": "trend", "confirmed_at": datetime.now().isoformat()}])
    out = write_report(tmp_path)
    assert (out / "drift.svg").exists()
    assert (out / "band.svg").exists()
    assert list(out.glob("metrics-*.md"))
