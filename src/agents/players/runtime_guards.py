"""Shared runtime guards: a wall-clock timeout primitive and an MCP-tool wrapper.

One timeout primitive (`call_with_timeout`) is reused by the planner's strategy
call and by the per-MCP-tool wrapper so the timeout behaviour is defined once
(DRY). The unified agent's async invoke() uses the asyncio-native equivalent
(`asyncio.wait_for` over an executor) for the same budget, since it already
runs on an event loop.

Single Responsibility: bound a blocking call by wall-clock time. These helpers
do nothing football-specific and hold no state.
"""

from __future__ import annotations

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


def wrap_tool_with_timeout(tool: Any, timeout: float) -> Any:
    """Wrap an MCP tool so a single call cannot exceed `timeout` seconds.

    The returned wrapper preserves the tool's identity (`tool_name`,
    `tool_spec`) so the Strands loop still sees the same name/schema. On
    timeout it returns a benign failed-tool-call result instead of blocking,
    letting the loop produce a final answer (or the tick time out into the
    deterministic fallback).
    """
    return _TimeoutTool(tool, timeout)


class _TimeoutTool:
    """Callable proxy that bounds the wrapped tool by wall-clock time.

    Transparent for attribute access (name/schema/spec) so it is a drop-in for
    the original tool, but the call is run through `call_with_timeout`.
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
