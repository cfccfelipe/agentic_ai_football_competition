"""Controlled 3-phase flow + static/dynamic split in unified_agent.invoke().

Covers:
  T-ORDER    — PHASE gate: select_strategy -> compose_tick_prompt -> agent_factory,
               with no skill-content/tool access before the strategy is settled;
               an unknown strategy is COERCED (not raised) to DEFAULT_STRATEGY;
               a raising planner falls back without composing or building an agent.
  T-STATIC-b — build_static_base() runs ONCE at register(), not per tick (patching
               it to raise after register() still lets a tick succeed).
  T-TOOL     — the static tool catalog alone drives decide-with-facts: with a
               plain (tool-free) strategy body, a catalog-following fake model
               calls the tactical tool before a SHOOT (north-star AC-N3).

Pure: no AWS, no network, no real strands.
"""

import asyncio
import copy
import json

import pytest

from test_helpers import GAME_STATE, mock_agentcore_gateway

mock_agentcore_gateway()

import constants  # noqa: E402
import plugin_loader  # noqa: E402
import planner  # noqa: E402
import unified_agent  # noqa: E402
from parsing import VALID_COMMANDS  # noqa: E402


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


class _FakeTool:
    def __init__(self, name):
        self.tool_name = name
        self.tool_spec = {"name": name}
        self.tool_type = "python"
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return {"status": "success", "content": [{"text": "0.8"}]}


class _FakeMCP:
    def __init__(self, tools):
        self._tools = tools

    def list_tools_sync(self):
        return list(self._tools)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _inject_tools(monkeypatch, tools):
    monkeypatch.setattr(unified_agent, "_gateway_transport", lambda: object())
    monkeypatch.setattr(unified_agent, "MCPClient", lambda transport: _FakeMCP(tools))


def _payload(player_id=3, game_state=None):
    gs = copy.deepcopy(game_state if game_state is not None else GAME_STATE)
    return {"prompt": {"teamId": 0, "gameState": gs, "myPlayers": [player_id]}}


def _run_invoke(invoke, payload):
    async def _collect():
        out = []
        async for chunk in invoke(payload, None):
            out.append(chunk)
        return out

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_collect())
    finally:
        loop.close()


# --- T-ORDER: phase ordering + gate -----------------------------------------

def test_phase_order_select_then_compose_then_factory(monkeypatch):
    events = []

    real_select = planner.select_strategy

    def spy_select(*a, **kw):
        events.append("select")
        return real_select(*a, **kw)

    real_compose = plugin_loader.compose_tick_prompt

    def spy_compose(*a, **kw):
        events.append("compose")
        return real_compose(*a, **kw)

    monkeypatch.setattr(planner, "select_strategy", spy_select)
    monkeypatch.setattr(plugin_loader, "compose_tick_prompt", spy_compose)

    def factory(system_prompt=None, tools=None, **kwargs):
        events.append("factory")
        return lambda prompt, **kw: '[{"commandType": "MOVE_TO", "parameters": {"target_x": 0, "target_y": 0}}]'

    invoke = unified_agent.register(_FakeApp(), 3, agent_factory=factory)
    _run_invoke(invoke, _payload(3))

    # Strategy must be settled before any skill content is composed or an agent
    # (with tools) is built.
    assert events == ["select", "compose", "factory"]


def test_unknown_strategy_is_coerced_not_raised(monkeypatch):
    # Planner returns garbage; the PHASE-1 guard must coerce to DEFAULT_STRATEGY
    # and still reach the normal compose path (NOT the except -> fallback path).
    monkeypatch.setattr(planner, "select_strategy", lambda *a, **kw: "nonsense-strategy")

    seen = {}
    real_compose = plugin_loader.compose_tick_prompt

    def spy_compose(static_base, strategy, position_label, player_id):
        seen["strategy"] = strategy
        return real_compose(static_base, strategy, position_label, player_id)

    monkeypatch.setattr(plugin_loader, "compose_tick_prompt", spy_compose)

    def factory(system_prompt=None, tools=None, **kwargs):
        return lambda prompt, **kw: '[{"commandType": "MOVE_TO", "parameters": {"target_x": 1, "target_y": 1}}]'

    invoke = unified_agent.register(_FakeApp(), 3, agent_factory=factory)
    out = _run_invoke(invoke, _payload(3))

    assert seen["strategy"] == constants.DEFAULT_STRATEGY
    parsed = json.loads(out[0])
    assert parsed[0]["commandType"] in VALID_COMMANDS
    assert parsed[0]["playerId"] == 3


def test_raising_planner_falls_back_without_compose_or_factory(monkeypatch):
    def boom(*a, **kw):
        raise RuntimeError("planner blew up")

    monkeypatch.setattr(planner, "select_strategy", boom)

    compose_called = {"n": 0}
    factory_called = {"n": 0}

    def spy_compose(*a, **kw):
        compose_called["n"] += 1
        return "x"

    def factory(**kwargs):
        factory_called["n"] += 1
        return lambda prompt, **kw: "[]"

    monkeypatch.setattr(plugin_loader, "compose_tick_prompt", spy_compose)

    invoke = unified_agent.register(_FakeApp(), 3, agent_factory=factory)
    out = _run_invoke(invoke, _payload(3))

    # No skill content composed, no agent built — deterministic fallback only.
    assert compose_called["n"] == 0
    assert factory_called["n"] == 0
    parsed = json.loads(out[0])
    assert isinstance(parsed, list) and parsed
    assert parsed[0]["commandType"] in VALID_COMMANDS
    assert parsed[0]["playerId"] == 3


# --- T-STATIC-b: static base built once at register() -----------------------

def test_static_base_built_once_not_per_tick(monkeypatch):
    def factory(system_prompt=None, tools=None, **kwargs):
        # Prove the cached static base rode into the prompt.
        assert "evaluate_shot" in system_prompt
        return lambda prompt, **kw: '[{"commandType": "MOVE_TO", "parameters": {"target_x": 0, "target_y": 0}}]'

    invoke = unified_agent.register(_FakeApp(), 3, agent_factory=factory)

    # Break build_static_base AFTER register() captured it. A per-tick rebuild
    # would now raise; a cached base survives.
    def boom():
        raise AssertionError("build_static_base must NOT run per tick")

    monkeypatch.setattr(plugin_loader, "build_static_base", boom)

    out = _run_invoke(invoke, _payload(3))
    parsed = json.loads(out[0])
    assert parsed[0]["commandType"] in VALID_COMMANDS


# --- T-TOOL: catalog alone drives decide-with-facts -------------------------

def test_tool_catalog_drives_tool_use_with_tool_free_body(monkeypatch):
    # A strategy body with NO tool mention still yields a tool call before the
    # SHOOT, because the STATIC catalog is the sufficient driver (AC-N3).
    tool = _FakeTool("evaluate_shot")
    _inject_tools(monkeypatch, [tool])

    # Guarantee the dynamic body contains no tool wording for this test.
    monkeypatch.setattr(
        plugin_loader,
        "load_skill_prompt",
        lambda strategy, pos, pid: (
            "You are a Forward. Shoot when in range. "
            "Return ONLY a JSON array with one command."
        ),
    )

    def factory(system_prompt=None, tools=None, **kwargs):
        # The catalog instructs: call the matching tool once before a SHOOT.
        assert "evaluate_shot" in system_prompt

        def agent(prompt, **kw):
            if tools:
                tools[0]()  # catalog-following: consult before the risky action
            return '[{"commandType": "SHOOT", "parameters": {"aim_location": "TR", "power": 0.9}}]'

        return agent

    invoke = unified_agent.register(_FakeApp(), 3, agent_factory=factory)
    out = _run_invoke(invoke, _payload(3))

    assert tool.calls >= 1
    parsed = json.loads(out[0])
    assert isinstance(parsed, list) and len(parsed) == 1
    assert parsed[0]["commandType"] in VALID_COMMANDS
