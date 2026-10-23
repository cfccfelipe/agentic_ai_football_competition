"""Per-agentId routing to position + correct skill file, for BOTH teams.

Covers AC-B1..B4:
  - every agentId 0..4 resolves to its correct position label via the
    single-source constants.position_for;
  - the composed system prompt carries the position-UNIQUE body marker (no
    cross-wiring: GK loads gk/, FWD1 loads fwd1/, etc.);
  - BOTH resolution branches: (a) payload-supplied myPlayers, and (b) the
    pinned MY_PLAYER_ID production branch with myPlayers omitted;
  - BOTH teams: team 0 HOME and team 1 AWAY (away perspective summarized).

Pure: no AWS, no network, no real strands.
"""

import asyncio
import copy
import json

import pytest

from test_helpers import GAME_STATE, mock_agentcore_gateway

mock_agentcore_gateway()

import constants  # noqa: E402
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


# Position-unique markers taken from the real plugins/<pos>/<strategy>.md bodies.
POSITION_MARKER = {
    "GK": "Goalkeeper",
    "DEF": "Defender",
    "MID": "Midfielder",
    "FWD1": "Forward 1",
    "FWD2": "Forward 2",
}

# Markers that must NOT appear (would mean cross-wiring to another position).
OTHER_MARKERS = {
    "GK": ["Forward 1", "Forward 2", "Midfielder"],
    "DEF": ["Goalkeeper", "Forward 1", "Forward 2"],
    "MID": ["Goalkeeper", "Forward 1", "Forward 2"],
    "FWD1": ["Goalkeeper", "Forward 2 (Right"],
    "FWD2": ["Goalkeeper", "Forward 1 (Left"],
}


def _collect(invoke, payload):
    async def _run():
        out = []
        async for chunk in invoke(payload, None):
            out.append(chunk)
        return out

    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(_run())
    finally:
        loop.close()


def _capturing_factory(captured):
    def factory(system_prompt=None, tools=None, **kwargs):
        captured["system_prompt"] = system_prompt
        return lambda prompt, **kw: '[{"commandType": "MOVE_TO", "parameters": {"target_x": 0, "target_y": 0}}]'

    return factory


def _state_for_team(team_id):
    """A game state where the ball is free, so every position has a sane tick."""
    gs = copy.deepcopy(GAME_STATE)
    gs["ball"]["isFree"] = True
    gs["ball"].pop("possessionAgentId", None)
    return gs


@pytest.mark.parametrize("player_id", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("team_id", [0, 1])
def test_routing_supplied_myplayers(player_id, team_id):
    """Branch (a): payload supplies myPlayers -> effective_pid from payload."""
    expected_pos = constants.PLAYER_POSITIONS[player_id]
    captured = {}

    # Register pinned to a DIFFERENT id to prove myPlayers wins when present.
    pinned = (player_id + 1) % 5
    invoke = unified_agent.register(_FakeApp(), pinned, agent_factory=_capturing_factory(captured))

    payload = {
        "prompt": {
            "teamId": team_id,
            "gameState": _state_for_team(team_id),
            "myPlayers": [player_id],
            # Pin the strategy so the loaded body is deterministic across
            # positions (balanced bodies carry the position-unique marker).
            "strategy": "balanced",
        }
    }
    out = _collect(invoke, payload)

    prompt = captured["system_prompt"]
    assert POSITION_MARKER[expected_pos] in prompt
    for bad in OTHER_MARKERS[expected_pos]:
        assert bad not in prompt, f"{expected_pos} prompt leaked marker {bad!r}"

    parsed = json.loads(out[0])
    assert parsed[0]["playerId"] == player_id
    assert parsed[0]["teamId"] == team_id
    assert parsed[0]["commandType"] in VALID_COMMANDS


@pytest.mark.parametrize("player_id", [0, 1, 2, 3, 4])
@pytest.mark.parametrize("team_id", [0, 1])
def test_routing_pinned_id_myplayers_absent(player_id, team_id):
    """Branch (b): production wiring — myPlayers omitted, pinned id resolves."""
    expected_pos = constants.PLAYER_POSITIONS[player_id]
    captured = {}

    invoke = unified_agent.register(_FakeApp(), player_id, agent_factory=_capturing_factory(captured))

    payload = {
        "prompt": {
            "teamId": team_id,
            "gameState": _state_for_team(team_id),
            # myPlayers deliberately omitted
            "strategy": "balanced",
        }
    }
    out = _collect(invoke, payload)

    prompt = captured["system_prompt"]
    assert POSITION_MARKER[expected_pos] in prompt
    for bad in OTHER_MARKERS[expected_pos]:
        assert bad not in prompt

    parsed = json.loads(out[0])
    assert parsed[0]["playerId"] == player_id
    assert parsed[0]["teamId"] == team_id
