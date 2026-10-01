"""配置加载与校验单测(C-10)。"""

from __future__ import annotations

import re

import pytest

from conftest import ENGINE_YAML, PRIVACY_YAML, RHYTHM_YAML, WEIGHTS_YAML, write_configs
from dreamlayer.config import ConfigError, load_config


def test_load_ok(tmp_project):
    cfg = load_config(tmp_project["config"])
    assert cfg.rhythm.min_pool == 20
    assert cfg.rhythm.pair_constraints == {"hard": ["tag"], "soft": ["origin", "time_bucket"]}
    assert cfg.weights.tag_weights["rejected"] == 2.0
    assert cfg.weights.coverage_boost_factor == 2.0
    assert cfg.privacy.journal_local_only is True
    assert cfg.engine.api_key_env == "DREAM_LLM_API_KEY"
    assert cfg.engine.refusal_retry == 1


def test_missing_file_errors(tmp_path):
    (tmp_path / "config").mkdir()
    with pytest.raises(ConfigError):
        load_config(tmp_path / "config")


def test_unknown_tag_weight_key_errors(tmp_project):
    p = tmp_project["config"] / "weights.yaml"
    p.write_text(WEIGHTS_YAML.replace("  selected: 1.0", "  selected: 1.0\n  bogus: 1.0"),
                 encoding="utf-8")
    with pytest.raises(ConfigError, match="未知 tag"):
        load_config(tmp_project["config"])


def test_missing_tag_weight_errors(tmp_project):
    p = tmp_project["config"] / "weights.yaml"
    p.write_text(WEIGHTS_YAML.replace("  discarded: 1.5\n", ""), encoding="utf-8")
    with pytest.raises(ConfigError, match="缺少"):
        load_config(tmp_project["config"])


def test_nonpositive_weight_errors(tmp_project):
    p = tmp_project["config"] / "weights.yaml"
    p.write_text(WEIGHTS_YAML.replace("  selected: 1.0", "  selected: 0"), encoding="utf-8")
    with pytest.raises(ConfigError, match="正数"):
        load_config(tmp_project["config"])


def test_missing_boost_field_errors(tmp_project):
    p = tmp_project["config"] / "weights.yaml"
    p.write_text(WEIGHTS_YAML.replace("coverage_boost_factor: 2.0\n", ""), encoding="utf-8")
    with pytest.raises(ConfigError, match="coverage_boost_factor"):
        load_config(tmp_project["config"])


def test_empty_exclude_globs_errors(tmp_project):
    p = tmp_project["config"] / "privacy.yaml"
    p.write_text(re.sub(r"exclude_globs:\n(  - .*\n)+", "exclude_globs: []\n", PRIVACY_YAML),
                 encoding="utf-8")
    with pytest.raises(ConfigError, match="exclude_globs"):
        load_config(tmp_project["config"])


def test_missing_api_key_env_errors(tmp_project):
    p = tmp_project["config"] / "engine.yaml"
    p.write_text(ENGINE_YAML.replace("api_key_env: 'DREAM_LLM_API_KEY'\n", ""), encoding="utf-8")
    with pytest.raises(ConfigError, match="api_key_env"):
        load_config(tmp_project["config"])


def test_unknown_constraint_dim_errors(tmp_project):
    p = tmp_project["config"] / "rhythm.yaml"
    p.write_text(RHYTHM_YAML.replace("hard: [tag]", "hard: [mood]"), encoding="utf-8")
    with pytest.raises(ConfigError, match="约束维度"):
        load_config(tmp_project["config"])


def test_overlapping_hard_soft_errors(tmp_project):
    p = tmp_project["config"] / "rhythm.yaml"
    p.write_text(RHYTHM_YAML.replace("hard: [tag]", "hard: [tag, origin]"), encoding="utf-8")
    # origin 同时出现在硬约束与软约束中
    with pytest.raises(ConfigError, match="同一维度"):
        load_config(tmp_project["config"])


def test_bad_collector_format_errors(tmp_project):
    p = tmp_project["config"] / "rhythm.yaml"
    p.write_text(
        RHYTHM_YAML.replace(
            "  read_disk: []",
            "  read_disk:\n"
            "    - name: t\n"
            "      origin: t\n"
            "      path_glob: 'x/*.rss'\n"
            "      format: rss",
        ),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="format"):
        load_config(tmp_project["config"])


def test_unknown_rhythm_keys_ignored(tmp_project):
    p = tmp_project["config"] / "rhythm.yaml"
    p.write_text(RHYTHM_YAML + "pair_repeat: never\nquiet_cycle: { idle_days: 7 }\n",
                 encoding="utf-8")
    cfg = load_config(tmp_project["config"])  # 预写字段不报错(quiet_cycle 已是已知键)
    assert cfg.rhythm.min_pool == 20


def test_drop_source_without_path_errors(tmp_project):
    p = tmp_project["config"] / "rhythm.yaml"
    p.write_text(RHYTHM_YAML.replace("  read_disk: []", "  drop:\n    - name: t\n"),
                 encoding="utf-8")
    with pytest.raises(ConfigError, match="path"):
        load_config(tmp_project["config"])


def test_bad_quiet_cycle_mode_errors(tmp_project):
    p = tmp_project["config"] / "rhythm.yaml"
    p.write_text(
        RHYTHM_YAML.replace('quiet_cycle: { idle_days: 7, mode: "off" }',
                            'quiet_cycle: { idle_days: 7, mode: "bogus" }'),
        encoding="utf-8",
    )
    with pytest.raises(ConfigError, match="quiet_cycle"):
        load_config(tmp_project["config"])


def test_p1_rhythm_defaults(tmp_project):
    cfg = load_config(tmp_project["config"])
    assert cfg.rhythm.max_reflux_per_day == 3
    assert cfg.rhythm.wake_temperature == 0.3
    assert cfg.rhythm.wake_max_tokens == 1500
    assert cfg.rhythm.webhook_url_env == "DREAM_WEBHOOK_URL"
    assert cfg.rhythm.quiet_cycle == {"idle_days": 7, "mode": "off"}


def test_write_configs_helper_idempotent(tmp_path):
    d1 = write_configs(tmp_path / "a")
    d2 = write_configs(tmp_path / "a")
    assert d1 == d2
    cfg = load_config(d1)
    assert cfg.engine.concurrency == 5
