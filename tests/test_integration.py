"""集成联调用例:IT-01 / IT-02 / IT-03 / IT-09(+ origin 开关)。

全部走 FakeEngine,零网络(G4);数据写入 tmp,绝不触碰仓库根的 data/。
"""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path

from conftest import (
    PROJECT_ROOT,
    RHYTHM_YAML,
    make_item,
    parse_meta,
    parse_pairs,
    run_fake_once,
    write_seed_jsonl,
)
from dreamlayer.__main__ import main

DEMO_SEED = PROJECT_ROOT / "data" / "seed" / "demo_day.jsonl"


# ---------- IT-01 ----------

def test_it01_demo_full_night_via_cli(tmp_project):
    """demo 45 条,run --once --fake:journal 生成、meta.pool=45、素材无重复、
    满 20 对(FR-G2);默认 FakeEngine 的醒来打包响应无法解析 -> 全 noise + 今夜无梦。"""
    write_configs_with_seed(tmp_project["config"], DEMO_SEED)
    rc = main([
        "run", "--once", "--fake",
        "--config-dir", str(tmp_project["config"]),
        "--data-dir", str(tmp_project["data"]),
    ])
    assert rc == 0
    journal = tmp_project["data"] / "journal" / f"{datetime.now().date().isoformat()}.md"
    assert journal.exists()
    text = journal.read_text(encoding="utf-8")
    meta = parse_meta(text)
    assert meta["pool"] == 45  # 45 条原始投递(其中 1 条重复 content)
    # G6(单夜同一素材最多入 1 对)不可放宽:34 条今日唯一 + 6 条历史抽样 = 40 候选 -> 20 对。
    assert meta["pairs"] == 20
    dreams = parse_pairs(text)
    assert len(dreams) == 20
    keys = [k for d in dreams for k in d["evidence"]]
    assert len(set(keys)) == len(keys) == 2 * len(dreams)  # 无重复素材
    assert all(d["verdict"] in {"noise", "recall", "trend", "cross_time"} for d in dreams)
    assert meta["all_noise"] is True  # 醒来响应不可解析 -> 全 noise(FR-B6)
    assert "今夜无梦" in text
    for d in dreams:  # 模板字段齐全
        assert {"persona", "raw", "verdict", "observation", "open_question", "evidence"} <= d["fields"]
    assert "# dream_journal ·" in text and text.startswith(f"# dream_journal · {datetime.now().date()}")
    # §6 梦话契约落盘 + 晨报(空夜也要写,存在感指标的每日仪式)
    assert (tmp_project["data"] / "dreams" / f"{datetime.now().date().isoformat()}.jsonl").exists()
    morning = tmp_project["data"] / "morning" / f"{datetime.now().date().isoformat()}.md"
    assert morning.exists() and "今夜无梦" in morning.read_text(encoding="utf-8")


def write_configs_with_seed(config_dir: Path, seed: Path):
    from conftest import write_configs

    return write_configs(
        config_dir,
        rhythm_yaml=RHYTHM_YAML.replace("seed_path: null", f"seed_path: '{seed.as_posix()}'"),
    )


# ---------- IT-02 ----------

def test_it02_below_waterline(tmp_project):
    """种子裁到 10 条:journal 记"太累但没东西可梦",无 micro_dreams 段。"""
    lines = DEMO_SEED.read_text(encoding="utf-8").splitlines()[:10]
    seed = tmp_project["data"] / "seed" / "demo_day.jsonl"
    seed.write_text("\n".join(lines) + "\n", encoding="utf-8")
    write_configs_with_seed(tmp_project["config"], seed)
    _, text = run_fake_once(tmp_project["data"], tmp_project["config"])
    meta = parse_meta(text)
    assert meta["pool"] == 10
    assert meta["pairs"] == 0
    assert "太累但没东西可梦" in text
    assert "## pair" not in text  # 无 micro_dreams 段


# ---------- IT-03 ----------

def test_it03_privacy_end_to_end(tmp_project):
    """secret_token.log 完全不入池不入 journal(路径级排除);含密钥普通条目入池但已打码。"""
    src = tmp_project["root"] / "pipeline-out"
    src.mkdir()
    (src / "secret_token.log").write_text(
        "api_token: super-secret-value-9527\nNEVER-READ-MARKER-7f3a91\n", encoding="utf-8"
    )
    now = datetime.now().isoformat()
    (src / "items.jsonl").write_text(
        "\n".join(
            [
                json.dumps({"id": "alpha-01", "content": "普通条目,没有密钥。", "time": now,
                            "tag": "rejected"}, ensure_ascii=False),
                json.dumps({"id": "beta-02",
                            "content": ("凭据轮换记录:sk-liveabcdef1234567890ab 已失效。"
                                        "本次轮换涉及生产与预发两个环境,新凭据由值班同学线下同步,"
                                        "历史告警与审计记录不受影响,日志中的旧值已按隐私规则打码处理。"),
                            "time": now, "tag": "rejected"}, ensure_ascii=False),
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    rhythm = RHYTHM_YAML.replace("min_pool: 20", "min_pool: 2").replace(
        "pairs_per_night: 20", "pairs_per_night: 1"
    ).replace(
        "  read_disk: []",
        "  read_disk:\n"
        f"    - name: daily\n      origin: daily-pipeline\n      path_glob: '{src.as_posix()}/**/*'\n"
        "      format: jsonl\n      content_field: content\n      time_field: time\n"
        "      default_tag: rejected",
    )
    from conftest import write_configs

    write_configs(tmp_project["config"], rhythm_yaml=rhythm)
    _, text = run_fake_once(tmp_project["data"], tmp_project["config"])

    pool_dir = tmp_project["data"] / "pool"
    pool_text = "\n".join(
        f.read_text(encoding="utf-8") for f in sorted(pool_dir.glob("*.jsonl"))
    )
    # 路径级排除:secret_token.log 的内容完全不出现在池与 journal
    assert "NEVER-READ-MARKER-7f3a91" not in pool_text
    assert "NEVER-READ-MARKER-7f3a91" not in text
    assert "super-secret-value-9527" not in pool_text
    # 内容级脱敏:入池但无 sk- 明文,池与 journal 均无泄漏
    assert "sk-" not in pool_text and "sk-" not in text
    assert "[REDACTED]" in pool_text
    assert "beta-02" in pool_text  # 打码条目正常入池
    # 两条都进了配对(journal evidence 出现普通条目 id)
    dreams = parse_pairs(text)
    assert len(dreams) == 1
    assert set(dreams[0]["evidence"]) == {"alpha-01", "beta-02"}


# ---------- IT-09 ----------

def test_it09_drop_tag_becomes_unknown_with_warning(tmp_project):
    """tag='drop' 且 tag_map 无此项:入池为 unknown,meta.warnings 计数。"""
    items = [
        make_item(1, tag="drop"),
        make_item(2, tag="rejected"),
    ]
    write_seed_jsonl(tmp_project["data"] / "seed" / "demo_day.jsonl", items)
    from conftest import write_configs

    write_configs(
        tmp_project["config"],
        rhythm_yaml=RHYTHM_YAML.replace("min_pool: 20", "min_pool: 2").replace(
            "pairs_per_night: 20", "pairs_per_night: 1"
        ),
    )
    _, text = run_fake_once(tmp_project["data"], tmp_project["config"])
    meta = parse_meta(text)
    # tag_unmapped 1 条 + 醒来打包响应解析失败 1 条(默认 FakeEngine,均如实计数,NFR7)
    assert meta["warnings"] == 2
    assert "tag_unmapped:drop" in text  # warnings_detail 记录原始 tag
    pool_text = "\n".join(
        f.read_text(encoding="utf-8")
        for f in sorted((tmp_project["data"] / "pool").glob("*.jsonl"))
    )
    assert '"tag": "unknown"' in pool_text


# ---------- origin 级开关(v0.3 §8) ----------

def test_origin_switch_drops_items(tmp_project):
    items = [make_item(1, origin="muted-src"), make_item(2, origin="muted-src")]
    write_seed_jsonl(tmp_project["data"] / "seed" / "demo_day.jsonl", items)
    from conftest import PRIVACY_YAML, write_configs

    write_configs(
        tmp_project["config"],
        rhythm_yaml=RHYTHM_YAML.replace("min_pool: 20", "min_pool: 2"),
        privacy_yaml=PRIVACY_YAML.replace("origin_switches: {}", "origin_switches: { muted-src: false }"),
    )
    _, text = run_fake_once(tmp_project["data"], tmp_project["config"])
    meta = parse_meta(text)
    assert meta["dropped"] == 2
    assert "origin_switched:muted-src" in text
    assert "太累但没东西可梦" in text  # 全被开关挡掉 -> 水位不足


# ---------- IT-13(P1):wake 全链路 -> 晨报 -> confirm -> metrics ----------

def test_it13_wake_reflux_confirm_metrics(tmp_project):
    """24 条各含唯一 LX 专名的素材 -> 12 对;醒来打包响应全过两道闸 -> top3 回流(FR-C4);
    晨报含 confirm 提示;confirm CLI 登记 reflux_log(FR-I3);metrics 计数(FR-I1)。"""
    items = [
        make_item(
            i,
            tag=["rejected", "hesitated", "selected", "discarded"][i % 4],
            origin=["daily-pipeline", "zcode", "kb"][i % 3],
            content=f"素材 LX{i:02d} 的独立上下文,用于醒来筛选专名锚点。",
        )
        for i in range(24)
    ]
    write_seed_jsonl(tmp_project["data"] / "seed" / "demo_day.jsonl", items)
    from conftest import WakeAwareEngine, lx_wake_response, write_configs

    write_configs(tmp_project["config"])  # conftest 默认:quiet off
    engine = WakeAwareEngine(wake_response=lx_wake_response)
    path, text = run_fake_once(tmp_project["data"], tmp_project["config"], engine=engine)
    meta = parse_meta(text)
    assert meta["pairs"] == 12
    assert meta["all_noise"] is False
    dreams = parse_pairs(text)
    refluxed = [d for d in dreams if d["verdict"] in ("trend", "cross_time")]
    assert len(refluxed) == 3  # 两路合计 top3
    assert all(d["observation"] and d["open_question"] for d in refluxed)
    assert len([d for d in dreams if d["verdict"] == "noise"]) == 9

    # 晨报:3 条 + 每条 confirm 提示
    today = datetime.now().date().isoformat()
    morning = (tmp_project["data"] / "morning" / f"{today}.md").read_text(encoding="utf-8")
    assert "昨夜 3 条值得看" in morning
    assert morning.count("dreamlayer confirm") == 3
    assert "只观察与提问" in morning

    # confirm CLI:晨报里的 dream_id -> reflux_log.jsonl
    m = re.search(r"dreamlayer confirm ([\w-]+) (recall|trend|cross_time)", morning)
    dream_id, verdict = m.group(1), m.group(2)
    assert main(["confirm", dream_id, verdict, "--data-dir", str(tmp_project["data"])]) == 0
    log_text = (tmp_project["data"] / "reflux_log.jsonl").read_text(encoding="utf-8")
    assert dream_id in log_text and verdict in log_text
    # dreams jsonl 的对应记录被打上 confirmed 标记
    assert f'"dream_id": "{dream_id}"' in (tmp_project["data"] / "dreams" / f"{today}.jsonl").read_text(encoding="utf-8")
    # 重复确认拒绝
    assert main(["confirm", dream_id, verdict, "--data-dir", str(tmp_project["data"])]) == 1

    # metrics:五指标报告落盘 + 邻近带曲线(漂移图需要跨周数据,单日不产)
    assert main(["metrics", "--data-dir", str(tmp_project["data"])]) == 0
    rep = tmp_project["data"] / "report"
    report = next(iter(rep.glob("metrics-*.md"))).read_text(encoding="utf-8")
    assert "有效回流:1" in report and "入梦夜数:1" in report
    assert (rep / "band.svg").exists()
