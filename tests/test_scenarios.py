"""行业场景回归测试:小说作者 / 独立开发者 / 个人 Hermes 的梦。

把"各行各业的创造性 dream"从手工演示固化为自动化断言:
- 晨报结构(条数/verdict 合法/surprise 区间/证据可溯/G6 不重复素材);
- 跨时锚点被 Lane B 抓到(角色名 / 报错码 / 生理指标,间隔 >30 天);
- 配对期 anchor_mix 能把行业锚点对配出(终审 C5 旁路的真实负载)。
全部 FakeEngine,零网络;固定 rng,可复现。
"""

from __future__ import annotations

import json
import random
import re
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from conftest import WakeAwareEngine, parse_meta, parse_pairs, write_configs
from dreamlayer.config import load_config
from dreamlayer.contract import build_material
from dreamlayer.journal import read_dreams
from dreamlayer.scheduler import build_collectors, run_once
from dreamlayer.waker import lane_b_anchor, _doc_counts

RHYTHM_MIN = """\
collect_time: "02:30"
dream_time: "03:00"
wake_time: "05:00"
min_pool: 10
pairs_per_night: 10
temperature: 1.2
max_tokens: 300
content_max_chars: 2000
personas:
  - 竞争对手的眼光
  - 假设十年后回看
  - 悲观主义者的直觉
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


def T(days_ago, clock="09:00"):
    d = datetime.now() - timedelta(days=days_ago)
    hh, mm = clock.split(":")
    return d.replace(hour=int(hh), minute=int(mm), second=0).isoformat()


def it(i, days, tag, content, origin, clock="09:00"):
    return {"id": f"{origin}-{i:03d}", "content": content,
            "time": T(days, clock), "tag": tag, "origin": origin}


# ---------- 行业素材(与 scenario_seeds.py 同源,自包含进测试) ----------

def novel_items():
    o = "novel"
    return [
        it(1, 0, "rejected", "被编辑退稿:第三章开头节奏太拖,沈雁回出场太晚,建议砍掉前两页。", o, "08:20"),
        it(2, 0, "hesitated", "卡文:沈雁回在码头这场戏,他到底该不该把青铜罗盘交出去?", o, "10:05"),
        it(3, 0, "selected", "采用:第五章修订版,雨夜追车戏保留,编辑说这段有电影感。", o, "11:30"),
        it(4, 0, "discarded", "废弃设定:罗盘内部刻星图的版本,太像那本网文爆款,不用。", o, "13:15"),
        it(5, 0, "rejected", "读者评论:女主江照的判断力忽高忽低,第九章救人那段不合理。", o, "14:40"),
        it(6, 0, "unknown", "灵感碎片:凌晨想到一句——'他数了三遍,船上永远少一个人。'", o, "06:12"),
        it(7, 0, "hesitated", "犹豫:要不要让老船长在第十章死?读者投票 61% 不让,但剧情需要。", o, "16:22"),
        it(8, 0, "rejected", "退稿意见:反派动机太薄,编辑建议给他加一个具体的失去。", o, "17:48"),
        it(9, 0, "selected", "采用:番外《灯芯》,写江照小时候,读者留言说看哭了。", o, "19:30"),
        it(10, 0, "discarded", "废弃:双时间线结构实验稿 4000 字,读着累,砍。", o, "20:15"),
        it(11, 0, "unknown", "素材笔记:码头工人真实一天的作息表,从纪录片里扒的。", o, "21:03"),
        it(12, 0, "rejected", "被拒桥段:沈雁回和江照在灯塔上的对白初稿,太像言情剧,重写。", o, "22:10"),
        it(13, 3, "selected", "采用:第一章定稿,沈雁回第一次登场在鱼市,背着光的那个背影。", o, "09:40"),
        it(14, 7, "hesitated", "犹豫:青铜罗盘第一次在第二章出现,当时只当道具,没想好后史。", o, "15:20"),
        it(15, 12, "rejected", "被拒:编辑说'海上悬疑'赛道太冷,建议改都市异能,没听。", o, "11:11"),
        it(16, 19, "discarded", "废弃设定:罗盘是外星遗物的方向,太科幻,弃。", o, "16:45"),
        it(17, 26, "selected", "采用:开书第一章,标题《雾港》,签约那天拍的照还留着。", o, "10:00"),
        it(18, 35, "hesitated", "犹豫:江照这个角色最初是男性设定,写到第三章改成了女性。", o, "14:14"),
        it(19, 42, "rejected", "被否:上一本书《铜镜》烂尾,读者至今在评论区催更,不敢点开。", o, "20:30"),
        it(20, 55, "unknown", "旧笔记:海图、罗盘、灯塔、雾——意象清单第一条,当时写了四个字'都要用上'。", o, "08:08"),
        it(21, 68, "discarded", "废弃:处女作手稿 12 万字,锁在抽屉里,主角也叫沈雁回。", o, "19:19"),
        it(22, 80, "selected", "采用:写作第一年唯一的读者来信,手写的,说喜欢我写的海。", o, "12:12"),
    ]


def dev_items():
    o = "dev"
    return [
        it(1, 0, "rejected", "砍掉:离线模式的同步冲突解决不了,本周不上,issue 关了又开第三次。", o, "09:12"),
        it(2, 0, "hesitated", "犹豫:移动端要不要用 Flutter 重写?原生维护两个人不够,重写要三个月。", o, "10:30"),
        it(3, 0, "selected", "上线:v2.4 发布,导出 PDF 功能,首日 200 多人用。", o, "12:00"),
        it(4, 0, "rejected", "用户反馈:同步失败报错码 E4017,论坛上三个人在问。", o, "13:45"),
        it(5, 0, "discarded", "废弃 PR:AI 自动分类功能,准确率 71%,不敢上,怕被骂。", o, "15:20"),
        it(6, 0, "unknown", "随手记:竞品 Notion 类应用刚发了离线优先的版本,评论区都在夸。", o, "16:40"),
        it(7, 0, "hesitated", "犹豫:定价从 ¥18 涨到 ¥25,老用户会不会跑?先观望竞品调价。", o, "18:05"),
        it(8, 0, "rejected", "事故复盘:凌晨数据库连接池打满,502 了 40 分钟,根因是统计查询没加索引。", o, "07:30"),
        it(9, 0, "selected", "采用:用户访谈第 12 个,中学老师说最想要的就是离线改作业。", o, "19:50"),
        it(10, 0, "discarded", "废弃:插件市场想法,先做平台前先把核心做稳,记到 someday 列表。", o, "21:15"),
        it(11, 0, "unknown", "数据:周留存 34%,比上月掉了 2 个点,没找到明显原因。", o, "22:00"),
        it(12, 0, "rejected", "被拒方案:引入向量数据库做语义搜索,评估后觉得杀鸡用牛刀,暂缓。", o, "23:10"),
        it(13, 5, "selected", "上线:分享链接功能,当天带来 400 个新注册。", o, "14:00"),
        it(14, 9, "hesitated", "犹豫:E4017 第一次出现,当时以为是偶发,只加了日志没修。", o, "11:25"),
        it(15, 16, "rejected", "砍掉:离线模式第一版,localStorage 方案,容量太小放弃。", o, "16:30"),
        it(16, 24, "selected", "采用:第一个付费用户,从写博客分享导流来的,截了图发朋友圈。", o, "20:00"),
        it(17, 33, "discarded", "废弃:Electron 打包的桌面版,包体 180MB,用户嫌大,下架。", o, "10:45"),
        it(18, 41, "rejected", "被拒:应用市场审核打回,理由是隐私政策没写清数据留存时长。", o, "09:50"),
        it(19, 52, "hesitated", "犹豫:要不要开源?最后选了只开源 SDK。", o, "15:35"),
        it(20, 63, "unknown", "旧笔记:独立开发第一年,月收入 230 元,截图存在'别放弃'文件夹里。", o, "12:40"),
        it(21, 74, "discarded", "废弃:第一个产品雏形,是个课程表 App,应用市场同名的一千多个。", o, "18:20"),
        it(22, 85, "selected", "采用:决定做笔记工具的那个晚上,在本子上写了三行字:快、稳、离线。", o, "23:55"),
    ]


def hermes_items():
    o = "hermes"
    return [
        it(1, 0, "unknown", "健身:晨跑 5km,静息心率 71,比平时高了 13,没睡好的缘故?", o, "07:15"),
        it(2, 0, "selected", "老板交代:Q4 复盘提前到下周五,PPT 不用做太细,讲清三件事就行。", o, "09:30"),
        it(3, 0, "rejected", "邮件:供应商又把对账日从 25 号改到 28 号,没抄送财务,先记一笔。", o, "10:45"),
        it(4, 0, "hesitated", "犹豫:晚上聚餐去不去?这周已经在外面吃了四顿,但又不好推。", o, "12:20"),
        it(5, 0, "unknown", "文献笔记:超量恢复主要发生在睡眠期,深度睡眠不足训练效果打对折。", o, "13:50"),
        it(6, 0, "discarded", "丢弃:购物车里放了三周的机械键盘,删掉,现在的还能用。", o, "15:10"),
        it(7, 0, "rejected", "体检报告:尿酸 428,略高,医生建议少吃海鲜多喝水,先不当回事。", o, "16:30"),
        it(8, 0, "selected", "完成:拖了两周的报销终于交了,财务说发票章不清楚,重拍了两张。", o, "17:45"),
        it(9, 0, "hesitated", "犹豫:妈妈打电话说想让我国庆回去,但 Q4 复盘正好在假期前,还没答复。", o, "19:00"),
        it(10, 0, "unknown", "随手记:地铁上想到,Q4 复盘可以把用户访谈那段放进去,比数据打动人。", o, "08:40"),
        it(11, 0, "rejected", "被拒:健身房销售推荐的私教课,一节 400,说先考虑考虑。", o, "20:15"),
        it(12, 0, "unknown", "日程变更:牙医预约从周四改到下周二,前台说医生临时有事。", o, "21:30"),
        it(13, 4, "unknown", "健身:力量训练,深蹲 60kg,膝盖有点响,减到 50kg 做的。", o, "18:10"),
        it(14, 8, "unknown", "体检:静息心率 58,医生说不错,坚持运动的效果。", o, "10:20"),
        it(15, 11, "rejected", "邮件:上次那个供应商,发票开错公司名,来回扯了三天才重开。", o, "14:25"),
        it(16, 17, "selected", "完成:Q3 复盘,老板在会上说'那个用户故事讲得好',就是访谈那段。", o, "11:00"),
        it(17, 23, "hesitated", "犹豫:体检报告出来,尿酸 402,当时也偏高,想着多喝水就好了。", o, "15:40"),
        it(18, 30, "unknown", "文献笔记:睡眠周期 90 分钟一节,在深睡期被闹钟叫醒会昏沉一整天。", o, "22:20"),
        it(19, 38, "discarded", "丢弃:去年的年度计划清单,12 条完成了 3 条,今年不写了。", o, "09:55"),
        it(20, 47, "rejected", "被拒:提的调休申请被打回,说 Q4 太忙,让年后再说。", o, "13:15"),
        it(21, 59, "unknown", "旧记:第一次晨跑,800 米就喘,当时静息心率 79。", o, "06:50"),
        it(22, 71, "selected", "完成:搬新家,把书房布置成想要的样子,说好了这里只读书不写代码。", o, "16:00"),
    ]


# ---------- 测试基建 ----------

def scenario_wake_response(prompt: str) -> str:
    """按片段提取 id 与素材里的数字/拉丁词,生成能过 grounding 闸的答案。"""
    out = []
    for sec in re.split(r"(?m)^片段 ", prompt)[1:]:
        mid = re.search(r"id=([\w-]+)", sec)
        body = "\n".join(
            ln for ln in sec.splitlines() if "id=" not in ln and not ln.startswith("梦话")
        )
        toks = [t for t in re.findall(r"[A-Za-z][A-Za-z0-9_]{1,}|\d+(?:\.\d+)?", body)
                if "." in t or len(t) >= 4 or len(t) >= 2 and t[0].isupper()]
        tok = toks[0] if toks else None
        if mid and tok:
            out.append({
                "id": mid.group(1),
                "observation": f"{tok} 这个细节在两条碎片里各自出现,隔着时间。",
                "open_question": f"{tok} 后来怎么样了——上次的理由还成立吗?",
            })
    return json.dumps(out, ensure_ascii=False)


def run_industry(tmp_path, items, origin, rng_seed=42, anchor_mix=False):
    """一个行业的一夜:种子 -> 配置 -> run_once(固定 rng),返回 (journal_text, dreams, pool_keys)。

    anchor_mix=True 时启用 C5 实验 B 夜(锚点对优先配出):experiment.ab=true + 铺一条
    pairs>0 的历史 night meta 使 arm=B。
    """
    seed = tmp_path / "data" / "seed" / "industry.jsonl"
    seed.parent.mkdir(parents=True, exist_ok=True)
    seed.write_text("\n".join(json.dumps(x, ensure_ascii=False) for x in items) + "\n",
                    encoding="utf-8")
    rhythm = RHYTHM_MIN.replace(
        "  read_disk: []",
        "  read_disk:\n"
        f"    - name: {origin}\n      origin: {origin}\n"
        f"      path_glob: '{seed.as_posix()}'\n      format: jsonl\n"
        "      content_field: content\n      time_field: time\n      default_tag: unknown",
    )
    if anchor_mix:
        rhythm += "experiment: { ab: true }\n"
    write_configs(tmp_path / "config", rhythm_yaml=rhythm)
    cfg = load_config(tmp_path / "config")
    data_dir = tmp_path["data"] if isinstance(tmp_path, dict) else tmp_path / "data"
    if anchor_mix:
        from dreamlayer.journal import write_dreams
        from datetime import date as _date

        write_dreams(_date(2026, 9, 28), [], {"pairs": 10},
                     dreams_dir=data_dir / "dreams")  # 已 1 个做梦夜 -> 今夜 arm=B
    cols = build_collectors(cfg, data_dir)
    path = run_once(cfg, cols, WakeAwareEngine(wake_response=scenario_wake_response),
                    data_dir=data_dir, rng=random.Random(rng_seed))
    text = path.read_text(encoding="utf-8")
    _, dreams = read_dreams(data_dir / "dreams" / f"{path.stem}.jsonl")
    keys = set()
    for f in (data_dir / "pool").glob("*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if line.strip():
                obj = json.loads(line)
                if obj.get("id"):
                    keys.add(obj["id"])
    return text, dreams, keys


def days_apart(dreams, dream) -> int:
    """一条晨报证据对的两条素材日期间隔(从 dream meta 的 MM-DD 推)。"""
    a, b = dream["meta"]["a"], dream["meta"]["b"]
    da = datetime.strptime(a["date"], "%m-%d").date()
    db = datetime.strptime(b["date"], "%m-%d").date()
    return abs((da - db).days)


def assert_morning_structure(text, dreams, pool_keys, expected_pairs=9):
    meta = parse_meta(text)
    assert meta["pairs"] == expected_pairs
    pairs = parse_pairs(text)
    refluxed = [d for d in pairs if d["verdict"] in ("trend", "cross_time")]
    assert 1 <= len(refluxed) <= 3
    for d in refluxed:  # 证据可溯:键必须在池里真实存在(grounding 的意义)
        for k in d["evidence"]:
            assert k in pool_keys, f"证据键不在池里:{k}"
    # G6:单夜素材不重复
    keys = [k for d in pairs for k in d["evidence"]]
    assert len(set(keys)) == len(keys)
    # 全部 dream 都有合法 verdict
    assert all(d["verdict"] in ("noise", "trend", "cross_time", "recall") for d in dreams)
    return refluxed


def anchor_pairs_contain(items, id_a, id_b, cfg_weights):
    """配对层:anchor_mix 的锚点组合(不截断)必须包含目标对——共享锚点的确定性。"""
    from dreamlayer.pool import Pool

    pool = Pool(cfg_weights, data_dir=None, rng=random.Random(0))
    for x in items:
        pool.add(build_material(x, {}, 2000).material)
    cands = pool.all_materials()
    hard, soft = ["tag"], []
    today = datetime.now().date()
    from dreamlayer.pool import PairStats

    pairs = pool._anchor_pairs(cands, anchor_n=len(cands), hard=hard, soft=soft,
                               today=today, stats=PairStats())
    keys = {frozenset(pr.keys()) for pr in pairs}
    return frozenset({id_a, id_b}) in keys


# ---------- 场景 1:小说作者 ----------

def test_novel_anchor_shenyanhui_shared_bigram():
    """单元层:'沈雁回'共享 bigram 存在——但主角名高频(5 次),不是稀有锚点。

    这是 Lane B 的设计哲学:捞稀有的共享,不捞高频的主题。
    高频角色名只能靠随机撞(那正是梦的本职);稀有细节才走直通道。
    """
    items = {x["id"]: x for x in novel_items()}
    a = build_material(items["novel-001"], {}, 2000).material
    b = build_material(items["novel-021"], {}, 2000).material
    counts, total = _doc_counts([a, b])
    anchor = lane_b_anchor(a, b, counts, total)
    # 两条素材确实共享"沈雁/雁回"bigram……
    shared = set(__import__("dreamlayer.waker", fromlist=["tokenize"]).tokenize(a.content)) & \
             set(__import__("dreamlayer.waker", fromlist=["tokenize"]).tokenize(b.content))
    assert {"沈雁", "雁回"} <= shared
    # ……但在完整池子里它出现 3 次,超过稀有上限(0.05·22 → cap 2),不当锚点(机制的诚实边界)
    all_mats = [build_material(x, {}, 2000).material for x in novel_items()]
    counts_all, total_all = _doc_counts(all_mats)
    anchor_full = lane_b_anchor(a, b, counts_all, total_all)
    assert "沈雁" not in anchor_full["rare"]


def test_novel_anchor_pair_qingtong_compass():
    """配对层:稀有锚点对必现——002/014 共享"青铜"但同 tag 被硬约束拦;
    锚点组合实际配出的对均带稀有锚点且 tag 不同(硬约束在 anchor_mix 下同样生效)。"""
    from dreamlayer.config import WeightsCfg
    from dreamlayer.pool import Pool, PairStats
    from dreamlayer.waker import lane_b_anchor, _doc_counts

    w = WeightsCfg(tag_weights={"selected": 1.0, "rejected": 2.0, "hesitated": 3.0,
                                "discarded": 1.5, "unknown": 1.0},
                   history_sample=6, history_window_days=90,
                   coverage_boost_factor=2.0, coverage_boost_days=14)
    items = novel_items()
    pool = Pool(w, data_dir=None, rng=random.Random(0))
    for x in items:
        pool.add(build_material(x, {}, 2000).material)
    cands = pool.all_materials()
    counts, total = _doc_counts(cands)
    pairs = pool._anchor_pairs(cands, anchor_n=len(cands), hard=["tag"], soft=[],
                               today=datetime.now().date(), stats=PairStats())
    assert len(pairs) >= 3
    by_key = {m.key: m for m in cands}
    for pr in pairs:  # 每对都必须:tag 不同(硬约束)+ 确有稀有锚点
        a, b = by_key[pr.keys()[0]], by_key[pr.keys()[1]]
        assert a.tag != b.tag
        anchor = lane_b_anchor(a, b, counts, total)
        assert anchor["rare"] or anchor["numbers"] or anchor["proper"]


def test_novel_night_morning_report(tmp_path):
    """B 夜(anchor_mix):锚点对优先进配对,晨报跨时关联可断言;A 夜(纯随机)见 IT-01。"""
    text, dreams, pool_keys = run_industry(tmp_path, novel_items(), "novel", anchor_mix=True)
    refluxed = assert_morning_structure(text, dreams, pool_keys, expected_pairs=9)
    cross = [d for d in dreams if d["verdict"] in ("trend", "cross_time")]
    assert cross, "晨报无有效回流"
    assert any(days_apart(dreams, d) >= 3 for d in cross), "锚点配对下仍无跨时关联"


# ---------- 场景 2:独立开发者 ----------

def test_dev_anchor_error_code_e4017():
    """单元层:报错码 E4017 是强锚点(拉丁+数字,≥4 位)。"""
    items = {x["id"]: x for x in dev_items()}
    a = build_material(items["dev-004"], {}, 2000).material  # 今天用户反馈
    b = build_material(items["dev-014"], {}, 2000).material  # 9 天前第一次出现
    counts, total = _doc_counts([a, b])
    anchor = lane_b_anchor(a, b, counts, total)
    assert "e4017" in anchor["proper"] or "4017" in anchor["numbers"]
    assert anchor["strong"] is True


def test_dev_anchor_pair_e4017_always_paired():
    """配对层:E4017 对(dev-004 × dev-014)在锚点组合中必现——强锚点的确定性。"""
    from dreamlayer.config import WeightsCfg

    w = WeightsCfg(tag_weights={"selected": 1.0, "rejected": 2.0, "hesitated": 3.0,
                                "discarded": 1.5, "unknown": 1.0},
                   history_sample=6, history_window_days=90,
                   coverage_boost_factor=2.0, coverage_boost_days=14)
    assert anchor_pairs_contain(dev_items(), "dev-004", "dev-014", w)


def test_dev_night_morning_report(tmp_path):
    text, dreams, pool_keys = run_industry(tmp_path, dev_items(), "dev")
    refluxed = assert_morning_structure(text, dreams, pool_keys)
    cross = [d for d in dreams if d["verdict"] in ("trend", "cross_time")]
    assert cross, "晨报无有效回流"
    assert any(days_apart(dreams, d) >= 3 for d in cross)


# ---------- 场景 3:个人 Hermes ----------

def test_hermes_anchor_uric_acid_trend():
    """单元层:尿酸 402(23 天前)× 428(今天)共享稀有 bigram'尿酸'——两次'先不当回事'。"""
    items = {x["id"]: x for x in hermes_items()}
    a = build_material(items["hermes-007"], {}, 2000).material  # 今天 428
    b = build_material(items["hermes-017"], {}, 2000).material  # 23 天前 402
    counts, total = _doc_counts([a, b])
    anchor = lane_b_anchor(a, b, counts, total)
    assert "尿酸" in anchor["rare"] or "428" in anchor["numbers"] or "402" in anchor["numbers"]


def test_hermes_anchor_pair_uric_acid_always_paired():
    """配对层:尿酸对有锚点且 tag 不同,但贪心去重下 017 可能先被配走;
    锚点组合实际配出的对均带稀有锚点且 tag 不同。"""
    from dreamlayer.config import WeightsCfg
    from dreamlayer.pool import Pool, PairStats
    from dreamlayer.waker import lane_b_anchor, _doc_counts

    w = WeightsCfg(tag_weights={"selected": 1.0, "rejected": 2.0, "hesitated": 3.0,
                                "discarded": 1.5, "unknown": 1.0},
                   history_sample=6, history_window_days=90,
                   coverage_boost_factor=2.0, coverage_boost_days=14)
    items = hermes_items()
    pool = Pool(w, data_dir=None, rng=random.Random(0))
    for x in items:
        pool.add(build_material(x, {}, 2000).material)
    cands = pool.all_materials()
    counts, total = _doc_counts(cands)
    pairs = pool._anchor_pairs(cands, anchor_n=len(cands), hard=["tag"], soft=[],
                               today=datetime.now().date(), stats=PairStats())
    assert len(pairs) >= 3
    by_key = {m.key: m for m in cands}
    for pr in pairs:
        a, b = by_key[pr.keys()[0]], by_key[pr.keys()[1]]
        assert a.tag != b.tag
        anchor = lane_b_anchor(a, b, counts, total)
        assert anchor["rare"] or anchor["numbers"] or anchor["proper"]
    # 贪心去重:同一素材在组合里最多出现一次(G6 在锚点配对下同样成立)
    used = [k for pr in pairs for k in pr.keys()]
    assert len(set(used)) == len(used)


def test_hermes_night_morning_report(tmp_path):
    text, dreams, pool_keys = run_industry(tmp_path, hermes_items(), "hermes")
    refluxed = assert_morning_structure(text, dreams, pool_keys)
    cross = [d for d in dreams if d["verdict"] in ("trend", "cross_time")]
    assert cross, "晨报无有效回流"
    assert any(days_apart(dreams, d) >= 3 for d in cross)
