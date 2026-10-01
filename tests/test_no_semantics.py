"""配对零语义静态审计(蓝队防守一 (a) / G1 红线的代码层固化)。

pool.py 是配对的发生地:禁止出现任何语义相似度符号。锚点配对的字符串统计
(tokenize/numbers)是允许的——它是实体共现,不是语义距离。
"""

from __future__ import annotations

import re
from pathlib import Path

FORBIDDEN = re.compile(r"similar|cosine|embedding|distance|semantic", re.I)


def test_pool_has_no_semantic_similarity():
    src = (Path(__file__).resolve().parents[1] / "dreamlayer" / "pool.py").read_text(encoding="utf-8")
    # 剥离注释与 docstring 后扫描,防"禁止相似度"这类注释自命中
    code = re.sub(r'""".*?"""', "", src, flags=re.S)
    code = "\n".join(ln.split("#", 1)[0] for ln in code.splitlines())
    hits = FORBIDDEN.findall(code)
    assert not hits, f"pool.py 出现语义相似度符号:{hits}(G1 红线:配对禁止语义)"


def test_waker_pairing_side_has_no_semantic_similarity():
    """配对侧的 _anchor_pairs 经由 waker 的字符串统计实现——同样不许出现语义距离符号。"""
    src = (Path(__file__).resolve().parents[1] / "dreamlayer" / "pool.py").read_text(encoding="utf-8")
    assert "lane_b_anchor" in src  # 锚点统计在,语义距离不在
    code = re.sub(r'""".*?"""', "", src, flags=re.S)
    assert "embedding" not in code.lower()
