"""入梦引擎(C-5)— 强制随机配对后的高温微型梦。

结构受控,语义不受控(v0.3 §4.2 钉死):prompt 骨架照抄原文(含诚实阀门),
素材信息仅 content/summary + origin/tag/time——没有别的。
拒答 -> 换 persona 重试 refusal_retry 次;每次尝试都保留在 meta.attempts(§9 安全拒答对策)。
"""

from __future__ import annotations

import random
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from .contract import Material
from .engine import is_refusal

# prompt 骨架逐字照抄 v0.3 §4.2(标点为原文的半角逗号/冒号/问号)
SKELETON_LINES = (
    "这两条碎片被随机放在了一起。",
    "不要总结,不要分析,不要得出结论。",
    "只说:它们放在一起让你想到什么?像什么?让你不舒服还是兴奋?",
    "如果什么都没触发,直说'这两条没碰出东西'——这不算失败。",
)


@dataclass
class MicroDream:
    """一次微型梦。pair = (素材键A, 素材键B);meta.attempts 保留每次尝试的 raw。"""

    pair: tuple[str, str]
    persona: str
    raw: str
    meta: dict = field(default_factory=dict)


def _material_block(m: Material, label: str) -> str:
    """只暴露 content/summary + origin/tag/time——只有这些,没有别的(v0.3 §4.2)。"""
    return (
        f"碎片{label} [origin={m.origin} · tag={m.tag} · time={m.time.strftime('%Y-%m-%d %H:%M')}]\n"
        f"{m.content}"
    )


def build_prompt(a: Material, b: Material, persona: str) -> str:
    parts = [
        f"视角乱入:{persona}",
        "",
        *SKELETON_LINES,
        "",
        _material_block(a, "A"),
        "",
        _material_block(b, "B"),
    ]
    return "\n".join(parts)


def dream_night(
    pairs,
    engine,
    personas,
    temperature: float = 1.2,
    concurrency: int = 5,
    max_tokens: int = 300,
    refusal_retry: int = 1,
    rng: random.Random | None = None,
) -> list[MicroDream]:
    """一夜 N 次微型梦:ThreadPoolExecutor 并行,顺序与 pairs 一致。

    persona 与拒答重试用的替补 persona 都在主线程预先抽定,worker 内不做随机,避免共享 rng 竞争。
    """
    rng = rng or random.Random()
    personas = list(personas)
    plans = []
    for p in pairs:
        persona = rng.choice(personas)
        alts = [x for x in personas if x != persona] or personas
        alt = rng.choice(alts)
        plans.append((p, persona, alt))

    def _info(m: Material) -> dict:
        return {"tag": m.tag, "origin": m.origin, "date": m.time.strftime("%m-%d"), "key": m.key}

    def run(plan) -> MicroDream:
        p, persona, alt = plan
        a, b = p.a, p.b
        attempts: list[str] = []
        raw = engine.complete(build_prompt(a, b, persona), temperature, max_tokens)
        attempts.append(raw)
        final_persona = persona
        tries = 0
        while is_refusal(raw) and tries < refusal_retry:
            final_persona = alt  # 换 persona 重试(§9:不重试轰炸)
            raw = engine.complete(build_prompt(a, b, alt), temperature, max_tokens)
            attempts.append(raw)
            tries += 1
        return MicroDream(
            pair=(a.key, b.key),
            persona=final_persona,
            raw=raw,
            meta={
                "temperature": temperature,
                "attempts": attempts,
                "a": _info(a),
                "b": _info(b),
            },
        )

    with ThreadPoolExecutor(max_workers=max(1, int(concurrency))) as ex:
        return list(ex.map(run, plans))
