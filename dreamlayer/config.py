"""配置加载与跨字段校验(C-10)。

四份 yaml:weights / rhythm / privacy / engine。
G2:权重数值与 tag->权重映射只来自 weights.yaml,core 不做兜底——缺字段启动即报错。
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
from pathlib import Path

import yaml

from .contract import TAGS

PAIR_CONSTRAINT_DIMS = ("tag", "origin", "time_bucket")
COLLECTOR_FORMATS = ("jsonl", "log", "md", "mdfile")

# C-5:personas 池来自 rhythm.yaml,默认六条
DEFAULT_PERSONAS = (
    "竞争对手的眼光",
    "假设十年后回看",
    "悲观主义者的直觉",
    "如果你是被拒绝的那一方",
    "一个刚入职的实习生",
    "审计员的怀疑",
)


class ConfigError(ValueError):
    """配置缺失/非法。启动即失败,不带病运行。"""


@dataclass
class WeightsCfg:
    """G2:全部字段必填,无代码兜底值。"""

    tag_weights: dict
    history_sample: int
    history_window_days: int
    coverage_boost_factor: float
    coverage_boost_days: int


@dataclass
class RhythmCfg:
    collect_time: str = "02:30"
    dream_time: str = "03:00"
    wake_time: str = "05:00"
    min_pool: int = 20
    pairs_per_night: int = 20
    temperature: float = 1.2
    max_tokens: int = 300
    content_max_chars: int = 2000
    personas: list = field(default_factory=lambda: list(DEFAULT_PERSONAS))
    # C-3:约束分级可配;P0 单采集源,origin 默认降为软约束(交付报告重申的工程化偏差)
    pair_constraints: dict = field(
        default_factory=lambda: {"hard": ["tag"], "soft": ["origin", "time_bucket"]}
    )
    collectors: dict = field(default_factory=dict)
    # P1:醒来筛选与回流(默认值仅在配置缺字段时生效,显式配置优先)
    wake_temperature: float = 0.3
    wake_max_tokens: int = 1500
    webhook_url_env: str = "DREAM_WEBHOOK_URL"   # webhook URL 不落盘(FR-H4 同款纪律)
    max_reflux_per_day: int = 3
    quiet_cycle: dict = field(
        default_factory=lambda: {"idle_days": 7, "mode": "alternate_days"}
    )
    # 红队 C5 对照实验:{ ab: true } 时按日期奇偶交替 随机配对(A)/ 锚点+随机(B);
    # 默认关——配对禁相似度的红线不变,B 组只是实验旁路
    experiment: dict = field(default_factory=lambda: {"ab": False})


@dataclass
class PrivacyCfg:
    exclude_globs: list = field(default_factory=list)
    redact_patterns: list = field(default_factory=list)
    journal_local_only: bool = True
    retention_days: int = 90
    origin_switches: dict = field(default_factory=dict)
    # 红队 D1:local_only 时非本地引擎直接拒绝启动(默认 open:云端引擎,素材会离开本机)
    mode: str = "open"


@dataclass
class EngineCfg:
    base_url: str = ""
    model: str = ""
    api_key_env: str = ""
    concurrency: int = 5
    request_timeout_s: int = 60
    refusal_retry: int = 1


@dataclass
class Cfg:
    weights: WeightsCfg
    rhythm: RhythmCfg
    privacy: PrivacyCfg
    engine: EngineCfg


def _build(cls, data: dict, label: str):
    known = {f.name for f in fields(cls)}
    dropped = sorted(set(data) - known)
    if dropped:
        # 未知键忽略(P0 允许预写 P1 字段,如 pair_repeat / quiet_cycle / max_reflux_per_day)
        data = {k: v for k, v in data.items() if k in known}
    try:
        return cls(**data)
    except TypeError as e:
        raise ConfigError(f"{label}: 字段缺失或类型非法({e})") from e


def _validate(w: dict, r: dict, p: dict, e: dict) -> None:
    tw = w.get("tag_weights")
    if not isinstance(tw, dict) or not tw:
        raise ConfigError("weights.yaml: tag_weights 必须为非空映射")
    unknown = sorted(set(tw) - set(TAGS))
    if unknown:
        raise ConfigError(f"weights.yaml: tag_weights 含未知 tag {unknown}(允许五值:{list(TAGS)})")
    missing = [t for t in TAGS if t not in tw]
    if missing:
        # G2:权重只来自配置,core 不做兜底,五值必须给全
        raise ConfigError(f"weights.yaml: tag_weights 缺少 {missing}")
    for t, v in tw.items():
        if not isinstance(v, (int, float)) or isinstance(v, bool) or v <= 0:
            raise ConfigError(f"weights.yaml: tag_weights[{t}] 必须为正数")
    for k in ("history_sample", "history_window_days", "coverage_boost_factor", "coverage_boost_days"):
        if k not in w:
            raise ConfigError(f"weights.yaml: 缺少 {k}(G2:数值只来自配置)")

    globs = p.get("exclude_globs")
    if not isinstance(globs, list) or not globs:
        raise ConfigError("privacy.yaml: exclude_globs 必须为非空列表")
    if not isinstance(p.get("redact_patterns", []), list):
        raise ConfigError("privacy.yaml: redact_patterns 必须为列表")
    switches = p.get("origin_switches", {})
    if not isinstance(switches, dict) or any(not isinstance(v, bool) for v in switches.values()):
        raise ConfigError("privacy.yaml: origin_switches 必须为 bool 映射")
    mode = p.get("mode", "open")
    if mode not in ("open", "local_only"):
        raise ConfigError("privacy.yaml: mode 只允许 open | local_only")

    if not e.get("api_key_env"):
        raise ConfigError("engine.yaml: api_key_env 必须配置(密钥只走环境变量,不落盘)")

    pc = r.get("pair_constraints") or {}
    hard, soft = list(pc.get("hard", ["tag"])), list(pc.get("soft", ["origin", "time_bucket"]))
    for dim in hard + soft:
        if dim not in PAIR_CONSTRAINT_DIMS:
            raise ConfigError(f"rhythm.yaml: 未知配对约束维度 {dim}(允许:{PAIR_CONSTRAINT_DIMS})")
    if set(hard) & set(soft):
        raise ConfigError("rhythm.yaml: 同一维度不能同时出现在硬约束与软约束中")
    personas = r.get("personas")
    if personas is not None and (not isinstance(personas, list) or not personas):
        raise ConfigError("rhythm.yaml: personas 必须为非空列表")
    max_reflux = r.get("max_reflux_per_day")
    if max_reflux is not None and (not isinstance(max_reflux, int) or isinstance(max_reflux, bool) or max_reflux < 1):
        raise ConfigError("rhythm.yaml: max_reflux_per_day 必须为 >=1 的整数")
    qc = r.get("quiet_cycle")
    if qc is not None:
        if not isinstance(qc, dict):
            raise ConfigError("rhythm.yaml: quiet_cycle 必须为映射 { idle_days, mode }")
        idle = qc.get("idle_days", 7)
        if not isinstance(idle, int) or isinstance(idle, bool) or idle < 1:
            raise ConfigError("rhythm.yaml: quiet_cycle.idle_days 必须为 >=1 的整数")
        if str(qc.get("mode", "alternate_days")) not in ("alternate_days", "off"):
            raise ConfigError("rhythm.yaml: quiet_cycle.mode 只允许 alternate_days | off")
    wake_t = r.get("wake_temperature")
    if wake_t is not None and (not isinstance(wake_t, (int, float)) or isinstance(wake_t, bool)):
        raise ConfigError("rhythm.yaml: wake_temperature 必须为数值")
    exp = r.get("experiment")
    if exp is not None:
        if not isinstance(exp, dict) or not isinstance(exp.get("ab", False), bool):
            raise ConfigError("rhythm.yaml: experiment 必须为映射 { ab: bool }")
    for src in (r.get("collectors") or {}).get("drop") or []:
        if not src.get("path"):
            raise ConfigError(f"rhythm.yaml: drop 采集源 {src.get('name')!r} 缺 path")
    for src in (r.get("collectors") or {}).get("read_disk") or []:
        if not src.get("path_glob"):
            raise ConfigError(f"rhythm.yaml: 采集源 {src.get('name')!r} 缺 path_glob")
        if src.get("format", "jsonl") not in COLLECTOR_FORMATS:
            raise ConfigError(
                f"rhythm.yaml: 采集源 {src.get('name')!r} format 非法(允许:{COLLECTOR_FORMATS})"
            )


def load_config(config_dir) -> Cfg:
    d = Path(config_dir)

    def read(name: str) -> dict:
        path = d / name
        if not path.exists():
            raise ConfigError(f"缺少配置文件:{path}")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict):
            raise ConfigError(f"{path} 顶层必须是映射")
        return data

    w, r, p, e = (read(n) for n in ("weights.yaml", "rhythm.yaml", "privacy.yaml", "engine.yaml"))
    _validate(w, r, p, e)
    return Cfg(
        weights=_build(WeightsCfg, w, "weights.yaml"),
        rhythm=_build(RhythmCfg, r, "rhythm.yaml"),
        privacy=_build(PrivacyCfg, p, "privacy.yaml"),
        engine=_build(EngineCfg, e, "engine.yaml"),
    )
