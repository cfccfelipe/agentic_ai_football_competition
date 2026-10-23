"""Tests for the shared runtime-guard helpers (timeout primitive + tool wrapper)."""

import time

import pytest

import runtime_guards


def test_call_with_timeout_returns_value_when_fast():
    assert runtime_guards.call_with_timeout(lambda: 42, timeout=1.0) == 42


def test_call_with_timeout_raises_on_slow_call():
    def slow():
        time.sleep(0.3)
        return "late"

    with pytest.raises(TimeoutError):
        runtime_guards.call_with_timeout(slow, timeout=0.02)


def test_call_with_timeout_propagates_exceptions():
    def boom():
        raise ValueError("nope")

    with pytest.raises(ValueError):
        runtime_guards.call_with_timeout(boom, timeout=1.0)


def test_tool_timeout_wrapper_preserves_name_and_passes_through():
    calls = {}

    def fake_tool(**kwargs):
        calls.update(kwargs)
        return {"ok": True}

    fake_tool.tool_name = "evaluate_shot"
    fake_tool.tool_spec = {"name": "evaluate_shot", "inputSchema": {}}

    wrapped = runtime_guards.wrap_tool_with_timeout(fake_tool, timeout=1.0)

    assert wrapped.tool_name == "evaluate_shot"
    assert wrapped.tool_spec == {"name": "evaluate_shot", "inputSchema": {}}
    result = wrapped(x=1)
    assert result == {"ok": True}
    assert calls == {"x": 1}


def test_tool_timeout_wrapper_surfaces_timeout_sentinel():
    def slow_tool(**kwargs):
        time.sleep(0.3)
        return {"ok": True}

    slow_tool.tool_name = "slow"

    wrapped = runtime_guards.wrap_tool_with_timeout(slow_tool, timeout=0.02)

    start = time.monotonic()
    result = wrapped()
    elapsed = time.monotonic() - start

    # Returns a benign failed-tool-call result promptly instead of blocking.
    assert elapsed < 0.25
    assert isinstance(result, dict)
    assert result.get("status") == "error"
