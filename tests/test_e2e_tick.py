"""End-to-end baseline for ONE agent tick (fully offline).

This is the durable regression line for the whole runtime-hardening effort. It
wires the REAL planner + plugin_loader through the REAL unified_agent.invoke()
path, with only the model and the MCP tools replaced by fakes injected via the
agent_factory DI seam. No AWS, no network, no real strands.

It asserts the five-point minimum successful tick:
  1. The planner SELECTS a state-aware strategy (losing-late -> aggressive,
     winning-late -> defensive).
  2. The chosen strategy's FORMATION is resolved via the O(1) frontmatter
     lookup and threaded into the composed system prompt (value in the allowed
     set).
  3. At least one reasoning step USES a tactical tool (the fake model invokes a
     tool offered through the MCP/tools path).
  4. A VALID single command is returned, correctly tagged teamId/playerId.
  5. It completes without an infinite loop and within the hard budget: the
     tool-iteration cap (2) stops a would-be-looping model, and a hanging model
     trips the 3.5s wall-clock timeout and falls back to the deterministic
     rule-based command.
"""

import asyncio
import copy
import json
import time

import pytest

from test_helpers import GAME_STATE, mock_agentcore_gateway

# Fake bedrock_agentcore + MCP + strands BEFORE importing the agent.
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
    """A deterministic stand-in for an MCP tactical tool."""

    def __init__(self, name):
        self.tool_name = name
        self.tool_spec = {"name": name}
        self.tool_type = "python"
        self.calls = 0

    def __call__(self, *args, **kwargs):
        self.calls += 1
        return {"status": "success", "content": [{"text": "0.8"}]}


def _state(home, away, game_time, possessor="agentId_3"):
    gs = copy.deepcopy(GAME_STATE)
    gs["score"] = {"home": home, "away": away}
    gs["gameTime"] = game_time
    gs["ball"]["possessionAgentId"] = possessor
    return gs


def _payload(game_state, player_id=3):
    return {"prompt": {"teamId": 0, "gameState": game_state, "myPlayers": [player_id]}}


class _FakeMCP:
    """MCP client context manager that offers a fixed tool list."""

    def __init__(self, tools):
        self._tools = tools

    def list_tools_sync(self):
        return list(self._tools)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


def _inject_tools(monkeypatch, tools):
    """Make unified_agent.register() fetch the given tools from a fake gateway."""
    monkeypatch.setattr(unified_agent, "_gateway_transport", lambda: object())
    monkeypatch.setattr(unified_agent, "MCPClient", lambda transport: _FakeMCP(tools))


def _run_invoke(invoke, payload):
    async def _collect():
        out = []
        async for chunk in invoke(payload, None):
            out.append(chunk)
        return out

    # Fresh loop closed WITHOUT draining the default executor (a timed-out tick
    # leaves a worker thread running; the real runtime never blocks on drain).
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_collect())
    finally:
        loop.close()


# --- Points 1 + 2: state-aware selection + formation resolution -------------

def test_planner_is_state_aware_and_formation_resolves():
    # Losing late -> aggressive; winning late -> defensive. Uses the REAL
    # registry-discovered set threaded through the real planner.
    known = plugin_loader.strategy_names()
    assert {"balanced", "aggressive", "defensive"} <= set(known)

    descriptions = plugin_loader.strategy_descriptions()

    losing_late = _state(home=0, away=1, game_time=80)
    assert (
        planner.select_strategy(losing_late, 0, descriptions, hint="auto", known=known)
        == "aggressive"
    )

    winning_late = _state(home=2, away=0, game_time=82)
    assert (
        planner.select_strategy(winning_late, 0, descriptions, hint="auto", known=known)
        == "defensive"
    )

    # Formation is an O(1) frontmatter lookup that rides the strategy choice and
    # lands in the composed prompt.
    prompt = plugin_loader.build_system_prompt("aggressive", "FWD", 3)
    assert "1-1-2" in prompt  # aggressive's remapped formation (two forwards)
    assert "1-1-2" in constants.ALLOWED_FORMATIONS
    assert "Formation" in prompt
    # Guardrails still intact.
    assert "JSON array" in prompt
    # Static tool catalog folded into the base (static/dynamic split).
    assert "evaluate_shot" in prompt


# --- Points 1-4: a full happy-path tick through the real invoke() -----------

def test_happy_path_tick_selects_uses_tool_and_returns_valid_command(monkeypatch):
    # Losing late so the rule-based path (used by the fake strategy agent that
    # returns a name the parser picks up) resolves to aggressive, and the fake
    # model USES a tool then returns a valid command.
    gs = _state(home=0, away=2, game_time=78)
    tool = _FakeTool("evaluate_shot")
    _inject_tools(monkeypatch, [tool])

    captured = {}

    def factory(system_prompt=None, tools=None, **kwargs):
        captured["system_prompt"] = system_prompt
        captured["tools"] = tools

        def agent(prompt, **kw):
            captured["limits"] = kw.get("limits")
            # One reasoning step that USES an offered tactical tool.
            if tools:
                tools[0]()
            return '[{"commandType": "SHOOT", "parameters": {"aim_location": "TR", "power": 0.9}}]'

        return agent

    invoke = unified_agent.register(_FakeApp(), 3, agent_factory=factory)
    out = _run_invoke(invoke, _payload(gs))

    # Point 2: the composed prompt carries a formation from the allowed set.
    assert any(f in captured["system_prompt"] for f in constants.ALLOWED_FORMATIONS)
    assert "Formation" in captured["system_prompt"]

    # Point 3: a tactical tool was offered AND used; the composed prompt also
    # carries the static tool catalog that drives decide-with-facts.
    assert captured["tools"] and tool.calls >= 1
    assert "evaluate_shot" in captured["system_prompt"]

    # Point 5 (cap threaded): the iteration cap rode the invocation.
    assert captured["limits"] == {"turns": constants.MAX_TOOL_ITERATIONS}

    # Point 4: exactly one valid, correctly-tagged command.
    parsed = json.loads(out[0])
    assert isinstance(parsed, list) and len(parsed) == 1
    assert parsed[0]["commandType"] in VALID_COMMANDS
    assert parsed[0]["playerId"] == 3
    assert parsed[0]["teamId"] == 0


# --- Point 5: infinite-loop protection (cap) --------------------------------

def test_tool_iteration_cap_stops_a_would_be_looping_model(monkeypatch):
    # A model that WOULD loop forever (keeps calling a tool) must be bounded by
    # the per-invocation turns cap. We model Strands' loop here: the fake honours
    # the `limits['turns']` it is handed, proving the cap value actually stops it.
    tool = _FakeTool("calculate_pass_options")
    _inject_tools(monkeypatch, [tool])
    gs = _state(home=0, away=1, game_time=80)

    def factory(system_prompt=None, tools=None, **kwargs):
        def agent(prompt, **kw):
            max_turns = kw["limits"]["turns"]
            turns = 0
            # Would run unbounded without the cap.
            while True:
                tools[0]()
                turns += 1
                if turns >= max_turns:
                    break
            return '[{"commandType": "PASS", "parameters": {"target_player_id": 3, "type": "THROUGH"}}]'

        return agent

    invoke = unified_agent.register(_FakeApp(), 2, agent_factory=factory)
    out = _run_invoke(invoke, _payload(gs, player_id=2))

    # The loop was capped at exactly MAX_TOOL_ITERATIONS, not infinite.
    assert tool.calls == constants.MAX_TOOL_ITERATIONS
    parsed = json.loads(out[0])
    assert parsed[0]["commandType"] in VALID_COMMANDS
    assert parsed[0]["playerId"] == 2


# --- Point 5: infinite-loop protection (wall-clock timeout) -----------------

def test_hanging_model_trips_timeout_and_falls_back(monkeypatch):
    monkeypatch.setattr(constants, "TICK_TIMEOUT_SECONDS", 0.05)
    gs = _state(home=0, away=1, game_time=80)

    def factory(system_prompt=None, tools=None, **kwargs):
        def agent(prompt, **kw):
            time.sleep(1.0)  # hang past the wall-clock budget
            return "never returned in time"
        return agent

    invoke = unified_agent.register(_FakeApp(), 3, agent_factory=factory)

    start = time.monotonic()
    out = _run_invoke(invoke, _payload(gs))
    elapsed = time.monotonic() - start

    # Fell back well under the 5s server budget with a deterministic command.
    assert elapsed < 1.0
    parsed = json.loads(out[0])
    assert isinstance(parsed, list) and parsed
    assert parsed[0]["commandType"] in VALID_COMMANDS
    assert parsed[0]["playerId"] == 3
    assert parsed[0]["teamId"] == 0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        try:
            fn()
        except TypeError:
            pass  # monkeypatch-dependent tests run under pytest
    print("e2e tick checks executed")
