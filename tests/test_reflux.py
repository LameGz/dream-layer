"""reflux 单测(FR-D4 / FR-I3):reflux_log 登记 / confirmed 标记 / quiet_cycle。"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta
from pathlib import Path

from dreamlayer.__main__ import main
from dreamlayer import reflux
from dreamlayer.__main__ import main
from dreamlayer.reflux import (
    already_confirmed,
    append_confirm,
    confirmed_dates,
    find_dream,
    load_candidates,
    load_log,
    log_path,
    mark_confirmed,
    quiet_skip,
)


def _write_dreams(data_dir: Path):
    dreams_dir = data_dir / "dreams"
    dreams_dir.mkdir(parents=True, exist_ok=True)
    meta = {"pairs": 2, "pool": 24, "late": False}
    lines = [json.dumps({"record": "night", "date": "2026-10-01", "meta": meta}, ensure_ascii=False)]
    for i in (1, 2):
        lines.append(json.dumps({
            "record": "dream", "dream_id": f"2026-10-01-{i:02d}", "pair": [f"ka{i}", f"kb{i}"],
            "persona": "审计员的怀疑", "raw": "梦话。", "meta": {},
            "verdict": "trend", "surprise": 0.5,
            "observation": f"观察 {i}", "open_question": f"问题 {i}?",
        }, ensure_ascii=False))
    (dreams_dir / "2026-10-01.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_find_dream_by_id(tmp_path):
    _write_dreams(tmp_path)
    d = find_dream(tmp_path, "2026-10-01-02")
    assert d and d["pair"] == ["ka2", "kb2"]
    assert find_dream(tmp_path, "2099-01-01-01") is None
    assert find_dream(tmp_path, "garbage") is None


def test_confirm_flow_marks_and_appends(tmp_path):
    _write_dreams(tmp_path)
    append_confirm(tmp_path, "2026-10-01-01", "recall", find_dream(tmp_path, "2026-10-01-01"))
    mark_confirmed(tmp_path, "2026-10-01-01")
    log = load_log(tmp_path)
    assert len(log) == 1
    assert log[0]["verdict"] == "recall" and log[0]["evidence"] == ["ka1", "kb1"]
    assert already_confirmed(log, "2026-10-01-01") is True
    assert already_confirmed(log, "2026-10-01-02") is False
    # dreams jsonl 的对应行打上 confirmed 标记,另一条不受影响
    text = (tmp_path / "dreams" / "2026-10-01.jsonl").read_text(encoding="utf-8")
    assert '"confirmed": true' in text
    assert text.count('"dream_id"') == 2  # 两条 dream 行(night 行无 dream_id)


def test_confirmed_dates_parses_or_skips():
    log = [
        {"confirmed_at": datetime(2026, 9, 28, 8, 0).isoformat()},
        {"confirmed_at": "garbage"},
    ]
    assert confirmed_dates(log) == [date(2026, 9, 28)]


def test_quiet_skip_matrix(tmp_path):
    today = date(2026, 10, 1)
    # mode off 永不跳过
    assert quiet_skip({"idle_days": 7, "mode": "off"}, tmp_path, today) == (False, "")
    # 空日志 + 奇数序数日 -> 跳过;偶数 -> 不跳
    skip, note = quiet_skip({"idle_days": 7, "mode": "alternate_days"}, tmp_path, today)
    assert skip == (today.toordinal() % 2 == 1)
    if skip:
        assert "隔日梦" in note
    # 7 天内有确认(含第 7 天) -> 不跳过;第 8 天起回到奇偶判定
    confirmed_on = date(2026, 9, 28)
    f = tmp_path / "reflux_log.jsonl"
    f.write_text(json.dumps({"dream_id": "x", "verdict": "recall",
                             "confirmed_at": datetime(2026, 9, 28, 8).isoformat()},
                            ensure_ascii=False) + "\n", encoding="utf-8")
    for d in (confirmed_on, confirmed_on + timedelta(days=3), confirmed_on + timedelta(days=7)):
        assert quiet_skip({"idle_days": 7, "mode": "alternate_days"}, tmp_path, d) == (False, "")
    d8 = confirmed_on + timedelta(days=8)
    skip, note = quiet_skip({"idle_days": 7, "mode": "alternate_days"}, tmp_path, d8)
    assert skip == (d8.toordinal() % 2 == 1)
    assert (note != "") == skip


def test_confirm_cli_end_to_end(tmp_path):
    _write_dreams(tmp_path)
    dd = str(tmp_path)
    assert main(["confirm", "2026-10-01-01", "recall", "--data-dir", dd]) == 0
    assert main(["confirm", "2026-10-01-01", "recall", "--data-dir", dd]) == 1  # 重复
    assert main(["confirm", "2099-01-01-01", "recall", "--data-dir", dd]) == 1  # 不存在
    assert main(["confirm", "2026-10-01-02", "noise", "--data-dir", dd]) == 1  # noise 不是有效回流
    assert main(["confirm", "2026-10-01-02", "cross_time", "--data-dir", dd]) == 0
    assert len(load_log(tmp_path)) == 2
    assert log_path(tmp_path).exists()


# ---------- 交互过审(review) ----------

def _write_candidates(data_dir: Path):
    dreams_dir = data_dir / "dreams"
    dreams_dir.mkdir(parents=True, exist_ok=True)
    lines = [json.dumps({"record": "night", "date": "2026-10-01",
                         "meta": {"pairs": 3}}, ensure_ascii=False)]
    for i, (verdict, confirmed) in enumerate(
            [("trend", False), ("cross_time", False), ("noise", False), ("recall", True)], 1):
        lines.append(json.dumps({
            "record": "dream", "dream_id": f"2026-10-01-{i:02d}", "pair": [f"ka{i}", f"kb{i}"],
            "persona": "审计员的怀疑", "raw": "梦话。", "meta": {"a": {"key": f"ka{i}", "tag": "rejected",
             "date": "09-28"}, "b": {"key": f"kb{i}", "tag": "hesitated", "date": "10-01"}},
            "verdict": verdict, "surprise": 0.5 + i / 10,
            "observation": f"观察 {i}", "open_question": f"问题 {i}?",
            **({"confirmed": True} if confirmed else {}),
        }, ensure_ascii=False))
    (dreams_dir / "2026-10-01.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_load_candidates_filters_noise_and_confirmed(tmp_path):
    _write_candidates(tmp_path)
    cands = reflux.load_candidates(tmp_path, date(2026, 10, 1))
    assert [c["dream_id"] for c in cands] == ["2026-10-01-01", "2026-10-01-02"]


def test_apply_batch_registers_skips_and_warns(tmp_path):
    _write_candidates(tmp_path)
    ok, warns = reflux.apply_batch(
        tmp_path,
        ["2026-10-01-01:recall", "2026-10-01-02:cross_time",
         "2026-10-01-01:trend", "2099-01-01-99:recall", "2026-10-01-03:noise", "垃圾"],
    )
    assert ok == 2
    assert len(warns) == 4  # 重复 / 找不到 / noise 非法 / 无冒号
    log = load_log(tmp_path)
    assert [e["verdict"] for e in log] == ["recall", "cross_time"]
    # confirmed 标记同步写入 dreams jsonl
    cands = reflux.load_candidates(tmp_path, date(2026, 10, 1))
    assert cands == []


def test_review_wizard_registers_and_skips(tmp_path, monkeypatch, capsys):
    _write_candidates(tmp_path)
    cands = reflux.load_candidates(tmp_path, date(2026, 10, 1))
    answers = iter(["1", "s"])  # 第一条登记 recall,第二条跳过
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    n = reflux.run_wizard(cands, tmp_path)
    out = capsys.readouterr().out
    assert n == 1
    assert "已登记 recall" in out and "跳过" in out
    assert [e["verdict"] for e in load_log(tmp_path)] == ["recall"]
    # 再跑一遍:剩下的候选只有一条
    cands2 = reflux.load_candidates(tmp_path, date(2026, 10, 1))
    assert [c["dream_id"] for c in cands2] == ["2026-10-01-02"]


def test_review_wizard_quit_stops_early(tmp_path, monkeypatch):
    _write_candidates(tmp_path)
    cands = reflux.load_candidates(tmp_path, date(2026, 10, 1))
    answers = iter(["3", "q"])
    monkeypatch.setattr("builtins.input", lambda prompt="": next(answers))
    n = reflux.run_wizard(cands, tmp_path)
    assert n == 1
    assert [e["verdict"] for e in load_log(tmp_path)] == ["cross_time"]


def test_review_cli_batch(tmp_path):
    _write_candidates(tmp_path)
    dd = str(tmp_path)
    assert main(["review", "--batch", "2026-10-01-01:trend,2026-10-01-02:recall",
                 "--data-dir", dd]) == 0
    assert len(load_log(tmp_path)) == 2
