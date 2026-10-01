"""LLM 引擎(C-4)。

G4:openai 包懒加载——只在 OpenAICompatibleEngine 实例化时 import;
未安装 openai 时,FakeEngine 与全部测试照常运行(测试与 --fake 零网络)。
"""

from __future__ import annotations

import os
import threading
from typing import Callable, Protocol

# 拒答模板句(C-4 原文);命中即换 persona 重试 refusal_retry 次
REFUSAL_PATTERNS = ("我无法", "作为AI", "作为 AI", "抱歉,我不能")


class Engine(Protocol):
    """引擎协议:v0.3 §4.2 —— 引擎可选配置化,base_url 换端点即换引擎。"""

    def complete(self, prompt: str, temperature: float, max_tokens: int) -> str: ...


def is_refusal(text: str) -> bool:
    if not text:
        return False
    return any(p in text for p in REFUSAL_PATTERNS)


class FakeEngine:
    """零网络假引擎(G4):按序返回 scripts(字符串或 callable);可模拟正常/拒答/超长。

    scripts 用尽后重复最后一项;scripts 为空时返回无害的合成梦话,方便全链路冒烟。
    complete() 的每次调用(含 temperature/max_tokens)都记录在 .calls,供测试断言。
    """

    def __init__(self, scripts=None):
        self._items: list = [scripts] if isinstance(scripts, str) else list(scripts or [])
        self._lock = threading.Lock()
        self._i = 0
        self.calls: list[dict] = []

    def complete(self, prompt: str, temperature: float, max_tokens: int) -> str:
        with self._lock:
            self.calls.append(
                {"prompt": prompt, "temperature": temperature, "max_tokens": max_tokens}
            )
            item = None
            if self._items:
                item = self._items[min(self._i, len(self._items) - 1)]
                self._i += 1
        if item is None:
            return f"(fake dream #{len(self.calls)}) 这两条碎片撞出了一点微光。"
        if callable(item):
            return item(prompt)
        return item


class OpenAICompatibleEngine:
    """真实引擎:OpenAI 兼容端点(GLM/DeepSeek/vLLM/ollama 皆可)。

    仅真实模式实例化;密钥只走环境变量,不落盘(v0.3 §8 的一致性)。
    """

    def __init__(self, base_url: str, model: str, api_key_env: str, timeout: int = 60):
        if not api_key_env:
            raise ValueError("engine.yaml 未配置 api_key_env")
        api_key = os.environ.get(api_key_env)
        if not api_key:
            raise RuntimeError(
                f"环境变量 {api_key_env} 未设置:真实引擎需要密钥;"
                f"开发与 CI 请用 --fake(FakeEngine,零网络零花费)"
            )
        try:
            import openai  # 懒加载(G4):未安装时真实模式给出清晰错误,fake/测试不受影响
        except ImportError as e:
            raise RuntimeError(
                "openai 包未安装:真实引擎不可用;--fake 模式与测试不需要该包"
            ) from e
        self._client = openai.OpenAI(base_url=base_url, api_key=api_key, timeout=timeout)
        self._model = model

    def complete(self, prompt: str, temperature: float, max_tokens: int) -> str:
        resp = self._client.chat.completions.create(
            model=self._model,
            messages=[{"role": "user", "content": prompt}],
            temperature=temperature,
            max_tokens=max_tokens,
        )
        return resp.choices[0].message.content or ""
