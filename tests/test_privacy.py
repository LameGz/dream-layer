"""隐私单测(C-2):路径排除 / 脱敏 / 云目录拒绝,含 IT-10 的 privacy 层参数化。"""

from __future__ import annotations

import pytest

from dreamlayer.privacy import CloudPathError, assert_journal_safe, path_excluded, redact

GLOBS = ["**/*secret*", "**/*token*", "**/.env*", "**/*.pem", "**/node_modules/**"]


def test_path_excluded_posix_and_windows():
    assert path_excluded("F:/pipeline/secret_token.log", GLOBS)
    assert path_excluded("F:\\pipeline\\secret_token.log", GLOBS)  # 反斜杠归一为 posix
    assert path_excluded("a/b/.env.local", ["**/.env*"])
    assert path_excluded("x/node_modules/y/z.js", GLOBS)
    assert not path_excluded("F:/pipeline/daily.jsonl", GLOBS)
    assert not path_excluded("anything", [])


def test_redact_replaces_and_measures():
    text = "这是一段很长的普通上下文,用来稀释打码占比。" * 8 + "key sk-abcdef1234567890abc end"
    out, ratio = redact(text, ["sk-[A-Za-z0-9]{16,}"])
    assert out == text.replace("sk-abcdef1234567890abc", "[REDACTED]")
    assert 0 < ratio < 0.3


def test_redact_ratio_over_threshold():
    text = "sk-aaaaaaaaaaaaaaaaaaaaaaaa"  # 几乎全文被打码
    out, ratio = redact(text, ["sk-[A-Za-z0-9]{16,}"])
    assert out == "[REDACTED]"
    assert ratio > 0.3


def test_redact_no_hit():
    out, ratio = redact("普通文本", ["sk-[A-Za-z0-9]{16,}"])
    assert out == "普通文本" and ratio == 0.0


def test_redact_multiple_patterns():
    out, _ = redact("a ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaa b password: hellosecret", [
        "ghp_[A-Za-z0-9]{30,}",
        "(?i)(password)\\s*[:=]\\s*\\S{6,}",
    ])
    assert "ghp_" not in out and "hellosecret" not in out


@pytest.mark.parametrize("marker", ["OneDrive", "Dropbox", "百度网盘", "坚果云", "iCloud"])
def test_cloud_markers_rejected(tmp_path, marker):
    d = tmp_path / marker / "x"
    with pytest.raises(CloudPathError):
        assert_journal_safe(d)


def test_journal_safe_allows_local(tmp_path):
    assert_journal_safe(tmp_path / "data" / "journal")  # 不抛
    assert_journal_safe(tmp_path / "local_archive") is None  # 不含云标记的路径不抛
