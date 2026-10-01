"""素材池(C-3):去重 / 日切 / 加权 / 约束配对 / 覆盖计数。

G1:这里没有任何语义参与——只有 tag/origin/时间桶/覆盖计数这些结构字段。
G2:权重数值与 boost 系数只来自 weights.yaml。
G6:单夜同一素材最多入 1 对(used 集合硬保证)。
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import date
from pathlib import Path

from .contract import Material, content_hash

# 约束维度枚举(非权重,允许的常量)
CONSTRAINT_DIMS = ("tag", "origin", "time_bucket")


def time_bucket(m: Material, today: date) -> str:
    """时间桶(C-3):今天 / 1-7 天 / 8-30 天 / 31-90 天。"""
    d = (today - m.time.date()).days
    if d <= 0:
        return "today"
    if d <= 7:
        return "1-7d"
    if d <= 30:
        return "8-30d"
    return "31-90d"


@dataclass
class PairStats:
    """配对放宽计数(C-3 要求至少前三项)。"""

    origin_relaxed: int = 0
    time_relaxed: int = 0
    hard_relaxed: int = 0
    history_sampled: int = 0


@dataclass
class Pair:
    a: Material
    b: Material

    def keys(self) -> tuple[str, str]:
        return (self.a.key, self.b.key)


class Pool:
    """内存索引 + jsonl 落盘(data/pool/YYYY-MM-DD.jsonl 追加写;coverage.json 跨夜)。"""

    def __init__(self, weights, data_dir: Path | None = None, rng: random.Random | None = None):
        self.weights = weights
        self.data_dir = Path(data_dir) if data_dir is not None else None
        self.rng = rng or random.Random()
        self._by_key: dict[str, Material] = {}
        self._content_hashes: dict[str, str] = {}  # content_hash -> key(辅索引,见 _index)
        self._coverage: dict[str, list] = {}
        if self.data_dir is not None:
            self.data_dir.mkdir(parents=True, exist_ok=True)
            self._load_pool_files()
            self._coverage = self._load_coverage()

    # ---------- 索引与落盘 ----------

    def _index(self, m: Material) -> bool:
        """幂等入索引:键 = id 优先;辅以 content 哈希——带 id 与不带 id 的相同 content 视为同一条。"""
        h = content_hash(m.content)
        if m.id and m.id in self._by_key:
            return False
        if h in self._content_hashes:
            return False
        key = m.key
        if key in self._by_key:
            return False
        self._by_key[key] = m
        self._content_hashes[h] = key
        return True

    def add(self, m: Material) -> bool:
        """幂等添加(C-3);落盘为该素材所属日期的 jsonl 追加写。"""
        if not self._index(m):
            return False
        if self.data_dir is not None:
            f = self.data_dir / f"{m.time.date().isoformat()}.jsonl"
            with f.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(m.to_dict(), ensure_ascii=False) + "\n")
        return True

    def _load_pool_files(self) -> None:
        for f in sorted(self.data_dir.glob("*.jsonl")):
            for line in f.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    self._index(Material.from_dict(json.loads(line)))
                except (json.JSONDecodeError, KeyError, ValueError):
                    continue  # 坏行跳过,不让整夜停摆

    def __len__(self) -> int:
        return len(self._by_key)

    def all_materials(self) -> list[Material]:
        return list(self._by_key.values())

    def material(self, key: str) -> Material | None:
        """按幂等键查询(waker 据此取配对素材的 content)。"""
        return self._by_key.get(key)

    def count_on(self, day: date) -> int:
        """当日(去重后)素材数——水位检查只看这个。"""
        return sum(1 for m in self._by_key.values() if m.time.date() == day)

    # ---------- 滚动清理(FR-A8) ----------

    def prune(self, before: date) -> int:
        """删除 time.date() < before 的素材:日桶文件整文件删除 + 内存索引 + coverage 键。

        journal 永久但仅本地,不在清理范围(FR-H3);返回清理条数。
        """
        doomed = [k for k, m in self._by_key.items() if m.time.date() < before]
        if not doomed:
            return 0
        for k in doomed:
            m = self._by_key.pop(k)
            self._content_hashes.pop(content_hash(m.content), None)
            self._coverage.pop(k, None)
        if self.data_dir is not None:
            for f in self.data_dir.glob("*.jsonl"):
                try:
                    if date.fromisoformat(f.stem) < before:
                        f.unlink()
                except ValueError:
                    continue
            self._save_coverage()
        return len(doomed)

    # ---------- 历史抽样 ----------

    def sample_history(self, n: int, window_days: int, today: date | None = None) -> list[Material]:
        """窗口内均匀随机抽 n 条历史素材(不含今天)。"""
        today = today or date.today()
        cands = [
            m
            for m in self._by_key.values()
            if 0 < (today - m.time.date()).days <= window_days
        ]
        return self.rng.sample(cands, min(n, len(cands)))

    # ---------- 覆盖计数与加权 ----------

    @property
    def coverage(self) -> dict:
        return self._coverage

    def _coverage_path(self) -> Path | None:
        return self.data_dir / "coverage.json" if self.data_dir is not None else None

    def _load_coverage(self) -> dict:
        p = self._coverage_path()
        if p is not None and p.exists():
            try:
                return json.loads(p.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                return {}
        return {}

    def _save_coverage(self) -> None:
        p = self._coverage_path()
        if p is not None:
            p.write_text(json.dumps(self._coverage, ensure_ascii=False, indent=2), encoding="utf-8")

    def record_coverage(self, keys, day: date) -> None:
        """入梦素材记 {键: [最近入梦日期, 次数]}(C-3)。"""
        for k in keys:
            ent = self._coverage.get(k)
            if ent:
                ent[0] = day.isoformat()
                ent[1] = int(ent[1]) + 1
            else:
                self._coverage[k] = [day.isoformat(), 1]
        self._save_coverage()

    def boost_factor(self, key: str, today: date) -> float:
        """覆盖 boost:从未入梦或距上次 > boost_days -> ×factor;纯结构性修正,不碰语义(G1)。"""
        ent = self._coverage.get(key)
        if not ent:
            return self.weights.coverage_boost_factor
        last = date.fromisoformat(ent[0])
        if (today - last).days > self.weights.coverage_boost_days:
            return self.weights.coverage_boost_factor
        return 1.0

    def weight_of(self, m: Material, today: date | None = None) -> float:
        """权重 = tag_weights[tag] × 覆盖 boost;数值只来自 weights.yaml(G2)。"""
        today = today or date.today()
        return self.weights.tag_weights[m.tag] * self.boost_factor(m.key, today)

    # ---------- 约束配对 ----------

    def build_pairs(
        self,
        n: int,
        today: date | None = None,
        constraints: dict | None = None,
        history: list[Material] | None = None,
        mode: str = "random",
    ) -> tuple[list[Pair], PairStats]:
        """约束配对(C-3):分级可配;放宽要计数;梦不因约束停摆——"没东西可梦"只看水位。

        对数封顶 = min(n, 可用素材数 // 2):G6 单夜同一素材最多入 1 对不可放宽。

        mode="random"(默认,红线不变):强制随机配对。
        mode="anchor_mix"(红队 C5 对照实验 B 组):一半锚点对(共享低频 token/数字/专名)
        + 一半随机对——用于回答"战果来自配对机制还是筛选打捞";默认关,experiment.ab 开启。
        """
        today = today or date.today()
        cons = constraints or {"hard": ["tag"], "soft": ["origin", "time_bucket"]}
        hard, soft = list(cons.get("hard", ["tag"])), list(cons.get("soft", ["origin", "time_bucket"]))
        stats = PairStats()

        today_items = [m for m in self._by_key.values() if m.time.date() == today]
        if history is None:
            history = self.sample_history(self.weights.history_sample, self.weights.history_window_days, today)
        stats.history_sampled = len(history)
        candidates = today_items + list(history)

        target = min(n, len(candidates) // 2)
        pairs: list[Pair] = []
        used: set[str] = set()

        if mode == "anchor_mix" and target >= 2:
            anchor_n = target // 2
            anchor_pairs = self._anchor_pairs(candidates, anchor_n, hard, soft, today, stats)
            for p in anchor_pairs:
                pairs.append(p)
                used.update(p.keys())

        while len(pairs) < target and len(candidates) - len(used) >= 2:
            pair = self._form_pair(candidates, used, hard, soft, today, stats)
            if pair is None:
                break
            pairs.append(pair)
            used.update(pair.keys())
        return pairs, stats

    def _anchor_pairs(self, candidates, anchor_n, hard, soft, today, stats) -> list[Pair]:
        """锚点对:候选中共享稀有锚点(低频 token/数字/专名)的组合,随机顺序贪心选取。

        硬约束(tag 不同)仍然生效;软约束照常如实计数。稀有锚点的分母是当夜候选集
        (与 waker Lane B 的全池口径不同——实验解读时知悉,终审问题 3)。
        这是实验旁路,不改变默认随机配对。
        """
        from .waker import lane_b_anchor, _doc_counts

        df_counts, total = _doc_counts(candidates)
        combos: list[tuple[Material, Material]] = []
        for i, a in enumerate(candidates):
            for b in candidates[i + 1 :]:
                if not self._satisfies(a, b, hard, today):
                    continue
                anchor = lane_b_anchor(a, b, df_counts, total)
                if anchor["rare"] or anchor["numbers"] or anchor["proper"]:
                    combos.append((a, b))
        self.rng.shuffle(combos)
        pairs: list[Pair] = []
        used: set[str] = set()
        for a, b in combos:
            if len(pairs) >= anchor_n:
                break
            if a.key in used or b.key in used:
                continue
            pairs.append(Pair(a, b))
            used.update((a.key, b.key))
            self._count_relaxed(a, b, soft, today, stats)
        return pairs

    def _weighted_choice(self, items: list[Material], today: date) -> Material:
        ws = [self.weight_of(m, today) for m in items]
        return self.rng.choices(items, weights=ws, k=1)[0]

    def _satisfies(self, a: Material, b: Material, dims, today: date) -> bool:
        for d in dims:
            if d == "tag" and a.tag == b.tag:
                return False
            if d == "origin" and a.origin == b.origin:
                return False
            if d == "time_bucket" and time_bucket(a, today) == time_bucket(b, today):
                return False
        return True

    def _count_relaxed(self, a: Material, b: Material, soft, today: date, stats: PairStats) -> None:
        """软约束放宽如实计数(C-3)。"""
        for d in soft:
            if d == "origin" and a.origin == b.origin:
                stats.origin_relaxed += 1
            if d == "time_bucket" and time_bucket(a, today) == time_bucket(b, today):
                stats.time_relaxed += 1

    def _pick_b(self, a: Material, rest: list[Material], soft, today: date, stats: PairStats) -> Material:
        """给定 a,从 rest 选 b:软约束尽量满足(重试 <=20 次),满足不了接受最后一个并计数。"""
        b = None
        for _ in range(20):
            b = self._weighted_choice(rest, today)
            if self._satisfies(a, b, soft, today):
                break
        self._count_relaxed(a, b, soft, today, stats)
        return b

    def _form_pair(self, candidates, used: set, hard, soft, today: date, stats: PairStats) -> Pair | None:
        unused = [m for m in candidates if m.key not in used]
        if len(unused) < 2:
            return None

        # 抽 a(加权,含覆盖 boost)
        a = self._weighted_choice(unused, today)
        rest = [m for m in unused if m.key != a.key]
        hard_ok = [m for m in rest if self._satisfies(a, m, hard, today)]
        if hard_ok:
            return Pair(a, self._pick_b(a, hard_ok, soft, today, stats))

        # 硬约束无解:换 a 重试 <=20 次(重试路径同样尽力满足软约束——终审顺手修)
        for _ in range(20):
            a2 = self._weighted_choice(unused, today)
            rest2 = [m for m in unused if m.key != a2.key]
            hard_ok2 = [m for m in rest2 if self._satisfies(a2, m, hard, today)]
            if hard_ok2:
                return Pair(a2, self._pick_b(a2, hard_ok2, soft, today, stats))

        # 仍无解 -> 放宽硬约束并计数;梦不因约束停摆(G6 的素材唯一性才是不可放宽项)
        a3 = self._weighted_choice(unused, today)
        rest3 = [m for m in unused if m.key != a3.key]
        b3 = self._weighted_choice(rest3, today)
        stats.hard_relaxed += 1
        self._count_relaxed(a3, b3, soft, today, stats)
        return Pair(a3, b3)
