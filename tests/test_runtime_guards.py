"""Tests for the shared runtime-guard helpers (timeout primitive + tool wrapper)."""

import asyncio
import sys
import time
from abc import ABC, abstractmethod

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


# ---------------------------------------------------------------------------
# A1/P1b — the wrapper MUST be a VALID Strands AgentTool so the registry keeps
# the four tactical tools (an opaque proxy is dropped: "unrecognized tool
# specification"). These tests install a minimal AgentTool base mirroring the
# real v1.13 contract (tool_name/tool_spec/tool_type props + async stream), then
# prove the wrapper (a) subclasses AgentTool and exposes an accepted tool_spec,
# and (b) still times a slow tool out benignly inside the stream path.
# ---------------------------------------------------------------------------


@pytest.fixture
def strands_agent_tool_base(monkeypatch):
    """Install a faithful minimal strands.types.tools.AgentTool + ToolResultEvent.

    Mirrors the real abstract contract so isinstance + abstractmethod coverage
    are exercised. Reset the wrapper's cached subclass so it rebinds to this
    base for the duration of the test.
    """

    class AgentTool(ABC):
        def __init__(self) -> None:
            self._is_dynamic = False

        @property
        @abstractmethod
        def tool_name(self) -> str: ...

        @property
        @abstractmethod
        def tool_spec(self): ...

        @property
        @abstractmethod
        def tool_type(self) -> str: ...

        @abstractmethod
        def stream(self, tool_use, invocation_state, **kwargs): ...

    class ToolResultEvent:
        def __init__(self, result):
            self.result = result

    tools_mod = type(sys)("strands.types.tools")
    tools_mod.AgentTool = AgentTool
    events_mod = type(sys)("strands.types._events")
    events_mod.ToolResultEvent = ToolResultEvent
    types_pkg = sys.modules.get("strands.types") or type(sys)("strands.types")
    strands_pkg = sys.modules.get("strands") or type(sys)("strands")

    monkeypatch.setitem(sys.modules, "strands", strands_pkg)
    monkeypatch.setitem(sys.modules, "strands.types", types_pkg)
    monkeypatch.setitem(sys.modules, "strands.types.tools", tools_mod)
    monkeypatch.setitem(sys.modules, "strands.types._events", events_mod)
    monkeypatch.setattr(runtime_guards, "_TIMEOUT_AGENT_TOOL_CLS", None)

    yield AgentTool, ToolResultEvent

    runtime_guards._TIMEOUT_AGENT_TOOL_CLS = None


class _FakeMCPTool:
    """Stand-in MCP AgentTool: real name/spec + an async stream yielding a result."""

    def __init__(self, name="evaluate_shot", delay=0.0, event_cls=None):
        self._name = name
        self._delay = delay
        self._event_cls = event_cls

    @property
    def tool_name(self):
        return self._name

    @property
    def tool_spec(self):
        return {"name": self._name, "description": "x", "inputSchema": {"json": {}}}

    @property
    def tool_type(self):
        return "python"

    async def stream(self, tool_use, invocation_state, **kwargs):
        if self._delay:
            await asyncio.sleep(self._delay)
        result = {"toolUseId": tool_use.get("toolUseId", ""), "status": "success",
                  "content": [{"text": "0.8"}]}
        yield self._event_cls(result) if self._event_cls else result


def _drain_stream(wrapped, tool_use):
    async def _run():
        events = []
        async for event in wrapped.stream(tool_use, {}):
            events.append(event)
        return events

    return asyncio.run(_run())


def test_wrapped_tool_is_a_valid_agent_tool(strands_agent_tool_base):
    AgentTool, _ = strands_agent_tool_base
    wrapped = runtime_guards.wrap_tool_with_timeout(_FakeMCPTool(), timeout=1.0)

    # (a) It IS a Strands AgentTool the registry accepts — not an opaque proxy.
    assert isinstance(wrapped, AgentTool)
    assert wrapped.tool_name == "evaluate_shot"
    spec = wrapped.tool_spec
    assert spec["name"] == "evaluate_shot"
    assert "inputSchema" in spec
    assert wrapped.tool_type == "python"


def test_wrapped_tool_streams_through_when_fast(strands_agent_tool_base):
    _, event_cls = strands_agent_tool_base
    tool = _FakeMCPTool(event_cls=event_cls)
    wrapped = runtime_guards.wrap_tool_with_timeout(tool, timeout=1.0)
    events = _drain_stream(wrapped, {"toolUseId": "abc", "input": {}})
    last = events[-1].result
    assert last["status"] == "success"
    assert last["toolUseId"] == "abc"


def test_wrapped_slow_tool_times_out_benignly(strands_agent_tool_base):
    slow = _FakeMCPTool(name="slow", delay=0.3)
    wrapped = runtime_guards.wrap_tool_with_timeout(slow, timeout=0.02)

    start = time.monotonic()
    events = _drain_stream(wrapped, {"toolUseId": "t1", "input": {}})
    elapsed = time.monotonic() - start

    assert elapsed < 0.25
    result = events[-1].result
    assert result["status"] == "error"
    assert result["toolUseId"] == "t1"
