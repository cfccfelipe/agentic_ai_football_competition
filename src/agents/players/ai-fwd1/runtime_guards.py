"""Shared runtime guards: a wall-clock timeout primitive and an MCP-tool wrapper.

One timeout primitive (`call_with_timeout`) is reused by the planner's strategy
call so the synchronous timeout behaviour is defined once (DRY). The per-MCP-tool
wrapper is a VALID Strands ``AgentTool`` subclass so the Strands tool registry
accepts it unchanged (an opaque proxy is dropped with "unrecognized tool
specification", which silently removes every tactical tool). The wrapper bounds
the tool's own async ``stream`` by wall-clock time inside the invoke path.

Single Responsibility: bound a blocking/streaming call by wall-clock time and
keep the wrapped tool a first-class ``AgentTool``. These helpers do nothing
football-specific and hold no state beyond the wrapped tool + its budget.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from typing import Any, Callable

# A small shared pool for the synchronous timeout primitive. Daemon threads so a
# runaway call never blocks interpreter shutdown; the worker keeps running in the
# background but the caller is released at the deadline.
_EXECUTOR = ThreadPoolExecutor(
    max_workers=8, thread_name_prefix="runtime-guard"
)


def call_with_timeout(fn: Callable[[], Any], timeout: float) -> Any:
    """Run a zero-arg blocking callable, raising TimeoutError past `timeout`.

    The callable's own exceptions propagate unchanged. On timeout a built-in
    TimeoutError is raised; the underlying worker thread is abandoned (daemon),
    so the caller is never blocked past the deadline.
    """
    future = _EXECUTOR.submit(fn)
    try:
        return future.result(timeout=timeout)
    except FutureTimeoutError as exc:
        future.cancel()
        raise TimeoutError(
            f"call exceeded {timeout}s budget"
        ) from exc


def _load_agent_tool_base():
    """Return (AgentTool, ToolResultEvent) from strands, or (None, None) offline.

    Imported lazily so pure constant reads and offline tests that stub ``strands``
    with only ``Agent``/``BedrockModel`` still import this module. When the real
    Strands ``AgentTool`` base is unavailable we fall back to the legacy opaque
    proxy (which only works when no real registry inspects it).
    """
    try:
        from strands.types.tools import AgentTool  # type: ignore
    except Exception:
        return None, None
    try:
        from strands.types._events import ToolResultEvent  # type: ignore
    except Exception:
        ToolResultEvent = None  # type: ignore
    return AgentTool, ToolResultEvent


def _timeout_tool_result(tool_use: Any, name: str, timeout: float) -> dict:
    """Benign failed-tool-call ToolResult so the agent loop can still finish."""
    tool_use_id = ""
    try:
        tool_use_id = tool_use.get("toolUseId", "")  # type: ignore[union-attr]
    except Exception:
        tool_use_id = ""
    return {
        "toolUseId": tool_use_id,
        "status": "error",
        "content": [{"text": f"tool '{name}' timed out after {timeout}s"}],
    }


def wrap_tool_with_timeout(tool: Any, timeout: float) -> Any:
    """Wrap an MCP tool so a single call cannot exceed `timeout` seconds.

    When the real Strands ``AgentTool`` base is importable the returned wrapper
    is a genuine ``AgentTool`` subclass (``_TimeoutAgentTool``): the registry
    accepts it, its ``tool_name``/``tool_spec``/``tool_type`` delegate to the
    wrapped tool, and its async ``stream`` runs the underlying stream under an
    ``asyncio.wait_for`` budget, yielding a benign error ToolResult on timeout.

    Offline (no real ``AgentTool``), it degrades to the legacy callable proxy so
    importing/using this module never hard-requires Strands.
    """
    AgentTool, ToolResultEvent = _load_agent_tool_base()
    if AgentTool is None:
        return _TimeoutTool(tool, timeout)
    return _make_timeout_agent_tool(AgentTool, ToolResultEvent)(tool, timeout)


_TIMEOUT_AGENT_TOOL_CLS: Any = None


def _make_timeout_agent_tool(AgentTool: Any, ToolResultEvent: Any):
    """Build (once) the concrete ``AgentTool`` subclass bound to this install.

    Defined dynamically because ``AgentTool`` is only importable with the real
    Strands package present (not in the offline test env). Cached so repeated
    ``wrap_tool_with_timeout`` calls reuse one class object.
    """
    global _TIMEOUT_AGENT_TOOL_CLS
    if _TIMEOUT_AGENT_TOOL_CLS is not None:
        return _TIMEOUT_AGENT_TOOL_CLS

    class _TimeoutAgentTool(AgentTool):
        """A valid AgentTool that bounds the wrapped tool's stream by wall-clock.

        Delegates identity (name/spec/type) to the wrapped tool so the Strands
        registry sees the real tool; only the ``stream`` execution is bounded.
        """

        def __init__(self, tool: Any, timeout: float):
            super().__init__()
            self._tool = tool
            self._timeout = timeout

        @property
        def tool_name(self) -> str:
            return self._tool.tool_name

        @property
        def tool_spec(self) -> Any:
            return self._tool.tool_spec

        @property
        def tool_type(self) -> str:
            return getattr(self._tool, "tool_type", "python")

        @property
        def supports_hot_reload(self) -> bool:
            return getattr(self._tool, "supports_hot_reload", False)

        def get_display_properties(self) -> dict:
            return {"Name": self.tool_name, "Type": self.tool_type}

        async def stream(self, tool_use, invocation_state, **kwargs):
            """Run the wrapped tool's stream under a hard wall-clock budget.

            Collects the underlying async generator's events inside a bounded
            task. On timeout, yields a single benign error ToolResult so the
            agent loop produces a final answer rather than hanging.
            """
            async def _drain() -> list:
                events = []
                async for event in self._tool.stream(
                    tool_use, invocation_state, **kwargs
                ):
                    events.append(event)
                return events

            try:
                events = await asyncio.wait_for(_drain(), timeout=self._timeout)
            except asyncio.TimeoutError:
                result = _timeout_tool_result(
                    tool_use, self.tool_name, self._timeout
                )
                if ToolResultEvent is not None:
                    yield ToolResultEvent(result)
                else:
                    yield result
                return
            for event in events:
                yield event

    _TIMEOUT_AGENT_TOOL_CLS = _TimeoutAgentTool
    return _TimeoutAgentTool


class _TimeoutTool:
    """LEGACY callable proxy, used ONLY when the real AgentTool base is absent.

    Transparent for attribute access (name/schema/spec) so it is a drop-in for
    the original tool offline, but a direct call is run through
    `call_with_timeout`. The real runtime always uses ``_TimeoutAgentTool``.
    """

    def __init__(self, tool: Any, timeout: float):
        self._tool = tool
        self._timeout = timeout
        # Mirror the identifying attributes the Strands loop reads, when present.
        for attr in ("tool_name", "tool_spec", "tool_type"):
            if hasattr(tool, attr):
                setattr(self, attr, getattr(tool, attr))

    def __getattr__(self, name: str) -> Any:
        # Delegate anything we did not copy (e.g. stream/invoke internals).
        return getattr(self._tool, name)

    def __call__(self, *args: Any, **kwargs: Any) -> Any:
        try:
            return call_with_timeout(
                lambda: self._tool(*args, **kwargs), self._timeout
            )
        except TimeoutError:
            name = getattr(self._tool, "tool_name", "tool")
            return {
                "status": "error",
                "content": [
                    {"text": f"tool '{name}' timed out after {self._timeout}s"}
                ],
            }
