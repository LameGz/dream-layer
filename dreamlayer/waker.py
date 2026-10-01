"""醒来筛选(waker)—— P1 已建(FR-C)。纯规则两路 + 一次打包小模型调用 + 两道机械闸。

Lane A 出乎意料度(surprise,0-1):先问"这个连接居然能搭上?"
    surprise = 0.4·origin_span + 0.3·time_span + 0.3·lexical_novelty
    origin_span     两条素材 origin 不同 = 1.0,相同 = 0.0(后续可细化为类别距离表)
    time_span       = min(Δdays, 90) / 90
    lexical_novelty = 1 − |dream内容词 ∩ (素材A内容词 ∪ 素材B内容词)| / |dream内容词|
                    (停用词过滤后计算;衡量梦话引入了多少素材里没有的词)
    top 10 进第二步。
Lane B 稀有锚点(rare-shared-anchor):两条素材共享池内低频 token(出现率 < 5%)、
    相同数字或相同专名时,无论 surprise 多低直接进第二步,
    verdict 候选锁 cross_time,配额 5 条/夜。
    理由:跨时共享实体恰恰是 P3 痛点("同一事件的两个阶段")的形态,
    纯意外度规则会把它当"不意外"扔掉——这是规则版最伤的误杀。
第二步:开放问题生成(对入选片段做一次小模型打包调用,产出 observation + open_question),
过两道机械闸(原则:这条不能只活在提示词里):
  1) 祈使检测:open_question 命中标记(建议 / 应该 / 下一步 / 值得做 / 可以考虑 / 需要你 / 记得去)
     → 降 noise;
  2) grounding:open_question 不含 evidence 素材中的具体指称(专名/数字/低频词)→ 降 noise。
保留:两路合计 top 3 进回流,其余标 noise 留档(FR-C4)。
分词:中文 = 字符 bigram + 拉丁 \\w+ 词,零依赖(FR-C1);jieba / embedding 换算法属 FR-C5,待校准集。

verdict 暂定映射:Lane B 锁 cross_time(PRD 原文);Lane A 暂定 trend(意外度驱动的候选信号);
recall/trend/cross_time 的最终判定永远属于人(confirm CLI,FR-D4)——梦只提名,不定案。
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass, field

# 结构配额与公式权重(PRD FR-C 原文数值,非权重表项)
LANE_A_TOP = 10
LANE_B_QUOTA = 5
RARE_DF_MAX = 0.05
W_ORIGIN, W_TIME, W_LEXICAL = 0.4, 0.3, 0.3
TIME_SPAN_WINDOW_DAYS = 90

# 祈使检测标记(FR-C3 原文列表 + 英文集——红队 C3:英文建议不得绕过闸)
IMPERATIVE_MARKS = (
    "建议", "应该", "下一步", "值得做", "可以考虑", "需要你", "记得去",
    "you should", "next step", "worth doing", "consider ", "recommend",
    "action item", "don't forget",
)

# 停用词(最小集:只为 lexical_novelty 服务,不过度过滤)
STOPWORDS = frozenset(
    "的 了 是 在 和 有 不 这 那 我 你 他 她 它 我們 你們 他們 一个 没有 什么 这个 那个 就是 还是 "
    "但是 因为 所以 如果 已经 还是 只是 一些 我们 你们 他们 自己 什么 怎么 这个 那个 "
    "the a an and or of to in is are was were be been being it this that these those "
    "with for on at as by from but not have has had do does did will would can could"
    .split()
)

_CJK_RUN = re.compile(r"[\u4e00-\u9fff]+")
_LATIN_WORD = re.compile(r"[A-Za-z0-9_]+")
_NUMBER = re.compile(r"\d+(?:\.\d+)?")

# 打包调用的 prompt 以此开头:sink/测试据此把醒来调用与微型梦调用区分开
WAKE_PROMPT_MARK = "醒来筛选"


@dataclass
class Reflux:
    """一条候选回流(FR-D)。verdict 为机器暂定,人工确认后进 reflux_log(FR-I3)。"""

    dream_id: str
    verdict: str
    surprise: float
    lane: str  # "A" | "B"
    fragment: str
    evidence: list[str]
    observation: str
    open_question: str
    evidence_info: list[dict] = field(default_factory=list)


def tokenize(text: str) -> set[str]:
    """中文 = 字符 bigram(单字 run 保留原字)+ 拉丁/数字词(小写);停用词过滤。零依赖。"""
    toks: set[str] = set()
    text = text or ""
    for w in _LATIN_WORD.findall(text):
        toks.add(w.lower())
    for run in _CJK_RUN.findall(text):
        if len(run) == 1:
            toks.add(run)
        for i in range(len(run) - 1):
            toks.add(run[i : i + 2])
    return {t for t in toks if t not in STOPWORDS}


def numbers(text: str) -> set[str]:
    """数字锚点:必须 ≥4 位或含小数点(年份/版本号/id 才配当锚点;"2"不配——红队 C1)。"""
    return {n for n in _NUMBER.findall(text or "") if "." in n or len(n) >= 4}


def proper_words(text: str) -> set[str]:
    """专名的机械代理:长度 >= 2 的拉丁词(小写)。"""
    return {w.lower() for w in _LATIN_WORD.findall(text or "") if len(w) >= 2}


def _doc_counts(materials) -> tuple[dict[str, int], int]:
    """token 在池内的出现次数(Lane B 与 grounding 共用)。

    红队 C2:纯比例阈值在小池子里失效(52 条池子 df<5% ⟺ 恰好 2 条共享,几乎任何
    共享 bigram 都"稀有")——稀有必须钉死在"出现 2 次且不超过 5%·N",即"恰好少数
    素材共享",通用 bigram(出现次数多)自然被排除。
    """
    mats = list(materials)
    df: dict[str, int] = {}
    for m in mats:
        for t in tokenize(getattr(m, "content", "") or ""):
            df[t] = df.get(t, 0) + 1
    return df, len(mats)


def _rare_cap(total: int) -> int:
    return max(2, math.ceil(RARE_DF_MAX * total)) if total else 2


def _split_day_diff(a, b) -> int:
    ta, tb = getattr(a, "time", None), getattr(b, "time", None)
    if ta is None or tb is None:
        return 0
    return abs((ta.date() - tb.date()).days)


def surprise_of(raw: str, mat_a, mat_b) -> tuple[float, float, float, float]:
    """返回 (surprise, origin_span, time_span, lexical_novelty)。素材缺失时各分量按 0 处理。"""
    origin_span = 1.0 if mat_a.origin != mat_b.origin else 0.0
    time_span = min(_split_day_diff(mat_a, mat_b), TIME_SPAN_WINDOW_DAYS) / TIME_SPAN_WINDOW_DAYS
    dream_toks = tokenize(raw)
    if dream_toks:
        mat_toks = tokenize(mat_a.content) | tokenize(mat_b.content)
        novelty = 1 - len(dream_toks & mat_toks) / len(dream_toks)
    else:
        novelty = 0.0
    return (
        W_ORIGIN * origin_span + W_TIME * time_span + W_LEXICAL * novelty,
        origin_span,
        time_span,
        novelty,
    )


def lane_b_anchor(mat_a, mat_b, df_counts: dict[str, int], total: int) -> dict:
    """稀有锚点检测:共享低频 token / 相同数字 / 相同专名。

    强弱分级:数字/专名 = 强锚点(跨时实体的形态);纯 bigram = 弱锚点(排序排尾部,
    防小池子里通用 bigram 灌水 Lane B——红队 C2)。
    """
    toks_a, toks_b = tokenize(mat_a.content), tokenize(mat_b.content)
    cap = _rare_cap(total)
    rare = {t for t in (toks_a & toks_b) if 2 <= df_counts.get(t, 0) <= cap}
    nums = numbers(mat_a.content) & numbers(mat_b.content)
    proper = proper_words(mat_a.content) & proper_words(mat_b.content)
    return {"rare": sorted(rare), "numbers": sorted(nums), "proper": sorted(proper),
            "strong": bool(nums or proper)}


def build_prompt(selected: list[dict]) -> str:
    """第二步打包调用:一次小模型调用产出全部入选片段的 observation + open_question。

    selected 元素:{"dream_id", "raw", "mat_a", "mat_b"}(material 对象)。
    prompt 以 WAKE_PROMPT_MARK 开头:测试与引擎据此区分醒来调用与微型梦调用。
    """
    parts = [
        f"{WAKE_PROMPT_MARK}:下面 {len(selected)} 段是昨晚的微型梦片段。对每段只产出两个字段:",
        "observation:一句陈述,说这段梦把什么放在一起时看到了什么(不评价、不建议);",
        "open_question:留给作者的一个问题,必须包含证据素材里的具体指称(专名/数字/日期)。",
        "禁止出现祈使式建议:建议、应该、下一步、值得做、可以考虑、需要你、记得去。",
        '只输出一个 JSON 数组,形如 [{"id": "...", "observation": "...", "open_question": "..."}],'
        "不要输出数组以外的任何文字。",
        "",
    ]
    for i, s in enumerate(selected, 1):
        a, b = s["mat_a"], s["mat_b"]
        parts += [
            f"片段 {i} · id={s['dream_id']}",
            f"梦话:{s['raw']}",
            f"素材A [id={a.key} · origin={a.origin} · tag={a.tag} · time={a.time.date().isoformat()}]",
            a.content,
            f"素材B [id={b.key} · origin={b.origin} · tag={b.tag} · time={b.time.date().isoformat()}]",
            b.content,
            "",
        ]
    return "\n".join(parts)


def parse_wake_response(text: str, valid_ids: set[str]) -> dict[str, dict] | None:
    """宽解析:整体 JSON -> 截取 [..] -> 失败返回 None(调用方降级为全 noise,不中断)。"""
    if not text or not text.strip():
        return None
    candidates = [text.strip()]
    first, last = text.find("["), text.rfind("]")
    if 0 <= first < last:
        candidates.append(text[first : last + 1])
    for cand in candidates:
        try:
            arr = json.loads(cand)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(arr, list):
            continue
        out: dict[str, dict] = {}
        for ent in arr:
            if not isinstance(ent, dict):
                continue
            did = str(ent.get("id", ""))
            if did in valid_ids and did not in out:
                out[did] = {
                    "observation": str(ent.get("observation", "") or ""),
                    "open_question": str(ent.get("open_question", "") or ""),
                }
        return out
    return None


def imperative_ok(question: str) -> bool:
    """祈使检测:命中任一标记即不通过(闸 1);英文词小写匹配,中文不受影响。"""
    q = (question or "").lower()
    return not any(mark in q for mark in IMPERATIVE_MARKS)


def grounding_ok(question: str, mat_a, mat_b, df_counts: dict[str, int], total: int) -> bool:
    """grounding:问题必须含 evidence 素材中的具体指称——数字 / 拉丁专名词 / 池内低频 bigram(闸 2)。"""
    q = (question or "").lower()
    if not q:
        return False
    for t in numbers(mat_a.content) | numbers(mat_b.content):
        if t in q:
            return True
    for w in proper_words(mat_a.content) | proper_words(mat_b.content):
        if w in q:
            return True
    cap = _rare_cap(total)
    rare = {t for t in (tokenize(mat_a.content) | tokenize(mat_b.content))
            if 2 <= df_counts.get(t, 0) <= cap}
    return any(t in q for t in rare)


def wake(dream_dicts, pool, engine, *, today=None, temperature: float = 0.3,
         max_tokens: int = 1500, max_reflux: int = 3):
    """对一夜的微型梦做两路筛选与两道闸(FR-C)。

    dream_dicts:journal.write_dreams 落盘的 dream 记录(含 dream_id/pair/raw/meta)。
    pool:Pool 实例(素材内容查询 + 池内 token 出现率);素材缺失的 pair 直接 noise。
    返回 (refluxes: list[Reflux], verdicts: {dream_id: {verdict, surprise, lane, observation,
    open_question}}, warnings: list[str])。

    全部 dream 都会拿到 verdict(回流候选为暂定 verdict,其余 noise);verdicts 即 journal
    重写与 dreams jsonl 回写的 overlay。
    today 仅预留(origin 类别距离表细化时使用);当前各分量都来自素材自身时间。
    """
    materials = {m.key: m for m in pool.all_materials()}
    df_counts, total = _doc_counts(materials.values())
    warnings: list[str] = []

    scored: list[dict] = []
    for d in dream_dicts:
        did = d.get("dream_id") or ""
        a = materials.get(d["pair"][0])
        b = materials.get(d["pair"][1])
        if a is None or b is None:
            warnings.append(f"wake_missing_material:{did}")
            scored.append({"dream_id": did, "dream": d, "mat_a": None, "mat_b": None,
                           "surprise": 0.0, "anchor": {}})
            continue
        surprise, *_ = surprise_of(d.get("raw") or "", a, b)
        scored.append({"dream_id": did, "dream": d, "mat_a": a, "mat_b": b,
                       "surprise": surprise, "anchor": lane_b_anchor(a, b, df_counts, total)})

    # Lane A:top 10
    rated = [s for s in scored if s["mat_a"] is not None]
    lane_a = sorted(rated, key=lambda s: (-s["surprise"], s["dream_id"]))[:LANE_A_TOP]

    # Lane B:稀有锚点,配额 5;强锚点(数字/专名)优先,纯 bigram 弱锚点排尾部(红队 C2)
    anchored = [s for s in rated if s["anchor"]["rare"] or s["anchor"]["numbers"] or s["anchor"]["proper"]]
    lane_b = sorted(
        anchored,
        key=lambda s: (not s["anchor"]["strong"],
                       -(len(s["anchor"]["numbers"]) + len(s["anchor"]["proper"])),
                       -len(s["anchor"]["rare"]),
                       -s["surprise"], s["dream_id"]),
    )[:LANE_B_QUOTA]

    selected_ids: list[str] = []
    for s in lane_a + lane_b:
        if s["dream_id"] not in selected_ids:
            selected_ids.append(s["dream_id"])
    by_id = {s["dream_id"]: s for s in scored}
    selected = [by_id[i] for i in selected_ids]
    prompt_inputs = [
        {"dream_id": s["dream_id"], "raw": s["dream"].get("raw") or "",
         "mat_a": s["mat_a"], "mat_b": s["mat_b"]}
        for s in selected if s["mat_a"] is not None
    ]

    verdicts: dict[str, dict] = {}
    for s in scored:
        verdicts[s["dream_id"]] = {
            "verdict": "noise", "surprise": round(s["surprise"], 4),
            "lane": "", "observation": "", "open_question": "",
        }

    if not selected:
        return [], verdicts, warnings

    # 第二步:一次打包调用;解析失败 -> 全部降 noise(片段已在 journal 留档,不丢)
    try:
        resp = engine.complete(build_prompt(prompt_inputs), temperature, max_tokens)
    except Exception as e:  # 引擎故障同样降级为全 noise,夜不停摆(NFR5)
        warnings.append(f"wake_call_failed:{e}")
        resp = ""
    answers = parse_wake_response(resp, set(selected_ids))
    if answers is None:
        warnings.append("wake_parse_failed")

    candidates: list[Reflux] = []
    for s in selected:
        did = s["dream_id"]
        ans = (answers or {}).get(did)
        if not ans:
            continue  # 无答案 -> noise
        obs, q = ans["observation"], ans["open_question"]
        if not imperative_ok(q):
            continue  # 闸 1
        if not grounding_ok(q, s["mat_a"], s["mat_b"], df_counts, total):
            continue  # 闸 2
        verdict = "cross_time" if s in lane_b else "trend"
        candidates.append(Reflux(
            dream_id=did, verdict=verdict, surprise=round(s["surprise"], 4),
            lane="B" if s in lane_b else "A", fragment=s["dream"].get("raw") or "",
            evidence=list(s["dream"]["pair"]), observation=obs, open_question=q,
            evidence_info=[
                {"key": s["mat_a"].key, "tag": s["mat_a"].tag, "origin": s["mat_a"].origin,
                 "date": s["mat_a"].time.strftime("%m-%d")},
                {"key": s["mat_b"].key, "tag": s["mat_b"].tag, "origin": s["mat_b"].origin,
                 "date": s["mat_b"].time.strftime("%m-%d")},
            ],
        ))

    # 两路合计 top3(FR-C4):cross_time 候选(锚点直通)优先,其次 surprise
    candidates.sort(key=lambda r: (r.verdict != "cross_time", -r.surprise, r.dream_id))
    refluxes = candidates[:max(1, int(max_reflux))]

    for r in refluxes:
        verdicts[r.dream_id].update(
            verdict=r.verdict, lane=r.lane, observation=r.observation, open_question=r.open_question,
        )
    return refluxes, verdicts, warnings
