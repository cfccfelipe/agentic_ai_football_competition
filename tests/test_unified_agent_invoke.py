"""Tests for unified_agent.invoke() runtime guards (timeout + fallback + DI).

Pure: no AWS, no network, no real strands. Gateway/strands modules are faked
via test_helpers.mock_agentcore_gateway() BEFORE importing unified_agent.
"""

import asyncio
import copy
import json
import time

import pytest

from test_helpers import GAME_STATE, mock_agentcore_gateway

# Fake out bedrock_agentcore + MCP + strands.tools.mcp before importing the agent.
mock_agentcore_gateway()

import constants  # noqa: E402
import unified_agent  # noqa: E402


class _FakeApp:
    class logger:
        @staticmethod
        def info(msg): pass
        @staticmethod
        def warn(msg): pass
        @staticmethod
        def error(msg): pass

    def entrypoint(self, fn):
        return fn


def _payload():
    return {
        "prompt": {
            "teamId": 0,
            "gameState": copy.deepcopy(GAME_STATE),
            "myPlayers": [3],
        }
    }


def _run_invoke(invoke):
    async def _collect():
        out = []
        async for chunk in invoke(_payload(), None):
            out.append(chunk)
        return out

    # A fresh loop we close WITHOUT draining the default executor: a timed-out
    # tick leaves a background worker thread running, and asyncio.run() would
    # block on shutdown_default_executor() waiting for it. The real AgentCore
    # runtime drives invoke on its own loop and never blocks on that drain.
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_collect())
    finally:
        loop.close()


def test_valid_llm_command_is_parsed_and_returned():
    cmd = '[{"commandType": "SHOOT", "parameters": {"aim_location": "TR", "power": 0.9}}]'

    def factory(**kwargs):
        return lambda prompt, **kw: cmd

    invoke = unified_agent.register(_FakeApp(), 3, agent_factory=factory)
    out = _run_invoke(invoke)

    parsed = json.loads(out[0])
    assert parsed[0]["commandType"] == "SHOOT"
    assert parsed[0]["playerId"] == 3
    assert parsed[0]["teamId"] == 0


def test_slow_model_falls_back_promptly(monkeypatch):
    monkeypatch.setattr(constants, "TICK_TIMEOUT_SECONDS", 0.05)

    def factory(**kwargs):
        def agent(prompt, **kw):
            time.sleep(1.0)
            return "too late"
        return agent

    invoke = unified_agent.register(_FakeApp(), 3, agent_factory=factory)

    start = time.monotonic()
    out = _run_invoke(invoke)
    elapsed = time.monotonic() - start

    # Deterministic fallback returns well under the 5s server budget.
    assert elapsed < 1.0
    parsed = json.loads(out[0])
    assert isinstance(parsed, list) and parsed
    assert parsed[0]["playerId"] == 3


def test_raising_model_falls_back():
    def factory(**kwargs):
        def agent(prompt, **kw):
            raise RuntimeError("model blew up")
        return agent

    invoke = unified_agent.register(_FakeApp(), 3, agent_factory=factory)
    out = _run_invoke(invoke)

    parsed = json.loads(out[0])
    assert isinstance(parsed, list) and parsed
    assert parsed[0]["playerId"] == 3


def test_iteration_cap_passed_as_limits():
    seen = {}

    def factory(**kwargs):
        def agent(prompt, **kw):
            seen.update(kw)
            return '[{"commandType": "PRESS_BALL", "parameters": {"intensity": 0.6}}]'
        return agent

    invoke = unified_agent.register(_FakeApp(), 3, agent_factory=factory)
    _run_invoke(invoke)

    assert seen.get("limits") == {"turns": constants.MAX_TOOL_ITERATIONS}


class _CapturingApp:
    def __init__(self):
        self.lines = []
        app = self

        class logger:
            @staticmethod
            def info(msg): app.lines.append(("info", msg))
            @staticmethod
            def warn(msg): app.lines.append(("warn", msg))
            @staticmethod
            def error(msg): app.lines.append(("error", msg))

        self.logger = logger

    def entrypoint(self, fn):
        return fn


def test_log_lines_carry_team_pos_role_prefix_with_team_name():
    # A3/P8: each app log line is prefixed [team<id> '<name>' pos<id> <ROLE>].
    app = _CapturingApp()

    def factory(**kwargs):
        return lambda prompt, **kw: '[{"commandType": "MOVE_TO", "parameters": {"target_x": 0, "target_y": 0}}]'

    invoke = unified_agent.register(app, 0, agent_factory=factory)

    payload = {
        "prompt": {
            "teamId": 0,
            "teamName": "Lightning Cloud",
            "gameState": copy.deepcopy(GAME_STATE),
            "myPlayers": [0],
            "strategy": "balanced",
        }
    }

    async def _collect():
        out = []
        async for chunk in invoke(payload, None):
            out.append(chunk)
        return out

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_collect())
    finally:
        loop.close()

    infos = [m for lvl, m in app.lines if lvl == "info"]
    assert infos, "expected at least one info log line"
    # player 0 is always GK; prefix includes the team NAME when present.
    assert any(m.startswith("[team0 'Lightning Cloud' pos0 GK]") for m in infos), infos


def test_log_prefix_falls_back_to_team_id_without_name():
    app = _CapturingApp()

    def factory(**kwargs):
        return lambda prompt, **kw: '[{"commandType": "MOVE_TO", "parameters": {"target_x": 0, "target_y": 0}}]'

    invoke = unified_agent.register(app, 0, agent_factory=factory)
    payload = {
        "prompt": {
            "teamId": 1,
            "gameState": copy.deepcopy(GAME_STATE),
            "myPlayers": [0],
            "strategy": "balanced",
        }
    }

    async def _collect():
        out = []
        async for chunk in invoke(payload, None):
            out.append(chunk)
        return out

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(_collect())
    finally:
        loop.close()

    infos = [m for lvl, m in app.lines if lvl == "info"]
    # No team name -> prefix is just [team1 pos0 GK] (no quoted name segment).
    assert any(m.startswith("[team1 pos0 GK]") for m in infos), infos
