"""测试公共设施:tmp 配置/种子工厂 + journal 解析器。

G4:全部测试走 FakeEngine,零网络;不依赖 openai 包。
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from dreamlayer.engine import FakeEngine  # 不触发 openai 导入(engine 懒加载),conftest 安全引用

PROJECT_ROOT = Path(__file__).resolve().parents[1]

WEIGHTS_YAML = """\
# 权重数值只存在于此(G2)
tag_weights:
  selected: 1.0
  rejected: 2.0
  hesitated: 3.0
  discarded: 1.5
  unknown: 1.0
history_sample: 6
history_window_days: 90
coverage_boost_factor: 2.0
coverage_boost_days: 14
"""

RHYTHM_YAML = """\
collect_time: "02:30"
dream_time: "03:00"
wake_time: "05:00"
min_pool: 20
pairs_per_night: 20
temperature: 1.2
max_tokens: 300
content_max_chars: 2000
personas:
  - 竞争对手的眼光
  - 假设十年后回看
  - 悲观主义者的直觉
  - 如果你是被拒绝的那一方
  - 一个刚入职的实习生
  - 审计员的怀疑
pair_constraints:
  hard: [tag]
  soft: [origin, time_bucket]
collectors:
  demo:
    seed_path: null
  read_disk: []
max_reflux_per_day: 3
quiet_cycle: { idle_days: 7, mode: "off" }
"""

PRIVACY_YAML = """\
exclude_globs:
  - '**/.env*'
  - '**/*.pem'
  - '**/*.key'
  - '**/*.keystore'
  - '**/*credential*'
  - '**/*secret*'
  - '**/*token*'
  - '**/node_modules/**'
  - '**/.git/objects/**'
redact_patterns:
  - 'sk-[A-Za-z0-9]{16,}'
  - 'AKIA[0-9A-Z]{16}'
  - 'ghp_[A-Za-z0-9]{30,}'
  - '(?i)(password|passwd|secret|token)\\s*[:=]\\s*\\S{6,}'
journal_local_only: true
retention_days: 90
origin_switches: {}
"""

ENGINE_YAML = """\
base_url: 'https://open.bigmodel.cn/api/paas/v4'
model: 'glm-4-flash'
api_key_env: 'DREAM_LLM_API_KEY'
concurrency: 5
request_timeout_s: 60
refusal_retry: 1
"""

CONFIG_FILES = {
    "weights.yaml": WEIGHTS_YAML,
    "rhythm.yaml": RHYTHM_YAML,
    "privacy.yaml": PRIVACY_YAML,
    "engine.yaml": ENGINE_YAML,
}


def write_configs(config_dir: Path, **overrides) -> Path:
    """写四份 yaml;overrides 用 <stem>_yaml 关键字整体替换某份(如 rhythm_yaml="...")。"""
    config_dir.mkdir(parents=True, exist_ok=True)
    files = dict(CONFIG_FILES)
    for key, text in overrides.items():
        assert key.endswith("_yaml"), f"override 键必须是 <stem>_yaml:{key}"
        stem = key[: -len("_yaml")]
        files[f"{stem}.yaml"] = text
    for name, text in files.items():
        (config_dir / name).write_text(text, encoding="utf-8")
    return config_dir


def make_item(i: int, tag="rejected", origin="daily-pipeline", days_ago=0, content=None, **extra):
    t = (datetime.now() - timedelta(days=days_ago)).strftime("%Y-%m-%d") + f" 0{i % 9 + 1}:{i % 60:02d}:00"
    item = {
        "id": f"t-{i:03d}",
        "content": content or f"素材 {i}:这是一条测试素材的正文,不含任何语义处理。",
        "time": t,
        "tag": tag,
        "origin": origin,
    }
    item.update(extra)
    return item


def write_seed_jsonl(path: Path, items: list[dict]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(it, ensure_ascii=False) for it in items) + "\n", encoding="utf-8"
    )
    return path


@pytest.fixture
def tmp_project(tmp_path):
    """tmp 配置目录 + tmp 数据目录(绝不触碰仓库根的 data/)。"""
    cfg = write_configs(tmp_path / "config")
    data = tmp_path / "data"
    (data / "seed").mkdir(parents=True)
    return {"root": tmp_path, "config": cfg, "data": data}


@pytest.fixture
def cfg(tmp_project):
    from dreamlayer.config import load_config

    return load_config(tmp_project["config"])


def run_fake_once(data_dir: Path, config_dir: Path, collectors=None, late=False,
                  engine=None):
    """进程内跑 run --once --fake 等价链路,返回 (journal_path, journal_text)。

    engine 缺省 FakeEngine(微型梦与醒来打包调用都吃假响应);传入 WakeAwareEngine
    可让醒来筛选拿到可控 JSON。
    """
    from dreamlayer.config import load_config
    from dreamlayer.engine import FakeEngine
    from dreamlayer.scheduler import build_collectors, run_once

    c = load_config(config_dir)
    cols = collectors if collectors is not None else build_collectors(c, data_dir)
    path = run_once(c, cols, engine if engine is not None else FakeEngine(), data_dir=data_dir, late=late)
    return path, path.read_text(encoding="utf-8")


class WakeAwareEngine(FakeEngine):
    """微型梦走 FakeEngine 合成梦话;prompt 以"醒来筛选"开头的打包调用返回 wake_response。

    wake_response:callable(prompt)->str | str | None。None 时为 prompt 中出现的每个
    id 自动生成一条答案(open_question 含 "2.4",grounding 由素材侧数字保证)。
    """

    def __init__(self, wake_response=None, scripts=None):
        super().__init__(scripts)
        self._wake_response = wake_response

    def complete(self, prompt: str, temperature: float, max_tokens: int) -> str:
        if prompt.startswith("醒来筛选"):
            with self._lock:
                self.calls.append(
                    {"prompt": prompt, "temperature": temperature, "max_tokens": max_tokens,
                     "phase": "wake"}
                )
            resp = self._wake_response
            if callable(resp):
                return resp(prompt)
            if isinstance(resp, str):
                return resp
            ids = re.findall(r"id=([\w-]+)", prompt)
            return json.dumps(
                [{"id": i, "observation": f"观察 {i}", "open_question": f"{i} 提到的 2.4 之后呢?"}
                 for i in ids],
                ensure_ascii=False,
            )
        return super().complete(prompt, temperature, max_tokens)


def lx_wake_response(prompt: str) -> str:
    """IT-13 用:按片段提取 id 与 LX 专名,生成能过 grounding 闸的答案。"""
    out = []
    for sec in re.split(r"(?m)^片段 ", prompt)[1:]:
        mid = re.search(r"id=([\w-]+)", sec)
        lx = re.search(r"LX\d+", sec)
        if mid and lx:
            out.append({
                "id": mid.group(1),
                "observation": f"{lx.group(0)} 和另一条撞出了回声",
                "open_question": f"{lx.group(0)} 那条线后来发生了什么?",
            })
    return json.dumps(out, ensure_ascii=False)


# ---------- journal 解析 ----------

_META_RE = re.compile(r"(?m)^meta: (.+)$")
_PAIR_SPLIT_RE = re.compile(r"(?m)^## pair ")


def parse_meta(text: str) -> dict:
    m = _META_RE.search(text)
    assert m, "journal 缺少 meta 行"
    out = {}
    for tok in m.group(1).split():
        k, _, v = tok.partition("=")
        if v == "true":
            v = True
        elif v == "false":
            v = False
        else:
            try:
                v = int(v)
            except ValueError:
                pass
        out[k] = v
    return out


def parse_pairs(text: str) -> list[dict]:
    out = []
    for sec in _PAIR_SPLIT_RE.split(text)[1:]:
        d = {"header": sec.splitlines()[0]}
        pm = re.search(r"(?m)^persona: (.*)$", sec)
        rm = re.search(r"raw: (.*?)(?=\nverdict:)", sec, re.S)
        vm = re.search(r"(?m)^verdict: (\S+)$", sec)
        em = re.search(r"(?m)^evidence: \[(.*)\]$", sec)
        om = re.search(r"(?m)^observation: (.*)$", sec)
        qm = re.search(r"(?m)^open_question: (.*)$", sec)
        d["persona"] = pm.group(1) if pm else None
        d["raw"] = rm.group(1).strip() if rm else None
        d["verdict"] = vm.group(1) if vm else None
        d["observation"] = om.group(1).strip() if om else ""
        d["open_question"] = qm.group(1).strip() if qm else ""
        d["evidence"] = [x.strip() for x in em.group(1).split(",")] if em else []
        d["fields"] = {
            ln.split(":")[0] for ln in sec.splitlines() if re.match(r"^[a-z_]+:", ln)
        }
        out.append(d)
    return out
