"""引擎单测(C-4):FakeEngine 行为 + openai 懒加载(G4)。"""

from __future__ import annotations

from dreamlayer.engine import FakeEngine, is_refusal


def test_fake_engine_in_order():
    eng = FakeEngine(["第一", "第二", "第三"])
    assert eng.complete("p1", 1.2, 300) == "第一"
    assert eng.complete("p2", 1.2, 300) == "第二"
    assert eng.complete("p3", 1.2, 300) == "第三"


def test_fake_engine_exhausted_repeats_last():
    eng = FakeEngine(["only"])
    eng.complete("a", 1.0, 10)
    assert eng.complete("b", 1.0, 10) == "only"
    assert eng.complete("c", 1.0, 10) == "only"


def test_fake_engine_callable_scripts():
    eng = FakeEngine([lambda prompt: f"回应:{prompt[:4]}"])
    assert eng.complete("hello world", 1.0, 10) == "回应:hell"


def test_fake_engine_single_string_script():
    assert FakeEngine("固定回答").complete("x", 1.0, 10) == "固定回答"


def test_fake_engine_default_no_scripts():
    eng = FakeEngine()
    out = eng.complete("x", 1.0, 10)
    assert out and "fake dream" in out


def test_fake_engine_records_calls():
    eng = FakeEngine(["x"])
    eng.complete("prompt-body", 1.2, 300)
    assert eng.calls == [{"prompt": "prompt-body", "temperature": 1.2, "max_tokens": 300}]


def test_fake_engine_zero_network():
    # FakeEngine 不持有任何客户端/连接对象;唯一状态是脚本队列与调用记录
    eng = FakeEngine(["x"])
    assert eng.__dict__.keys() <= {"_items", "_lock", "_i", "calls"}


def test_engine_module_does_not_import_openai():
    """G4:engine.py 顶层不得 import openai——懒加载只允许出现在 OpenAICompatibleEngine 内部。"""
    import dreamlayer.engine as mod

    with open(mod.__file__, "r", encoding="utf-8") as fh:
        for line in fh:
            if line[:1].isspace():
                continue  # 缩进行:函数体内的懒加载 import 是允许的
            if line.startswith("import openai") or line.startswith("from openai"):
                raise AssertionError(f"engine.py 存在顶层 openai 导入:{line.strip()}")


def test_is_refusal():
    assert is_refusal("抱歉,我不能这样做。")
    assert is_refusal("我无法完成")
    assert is_refusal("作为AI我建议")
    assert is_refusal("作为 AI 我建议")
    assert not is_refusal("这两条没碰出东西")
    assert not is_refusal("")
