"""Offline, seeded, deterministic match-evaluation runner.

Generates tick records WITHOUT AWS and WITHOUT a live model, then feeds them
through the pure ``metrics`` pipeline and the ``report`` renderer.

``simulate_match`` is ONE producer of tick records (the offline one). A future
``cloudwatch_source.records_from_cloudwatch(...)`` adapter would emit the same
record shape from CloudWatch logs/traces and reuse ``metrics`` + ``report``
unchanged — see the package docstring. No boto3/CloudWatch code lives here
(YAGNI); only the record contract is fixed.
"""

import copy
import os
import random
import sys
import zlib
from collections.abc import Callable


def _bootstrap_paths() -> None:
    """Wire sys.path so this module runs standalone (``make eval``) AND under pytest.

    Mirrors tests/conftest.py: the shared kernel (``src/commons``), the unified
    agent package (``src/agents/players`` for ``constants``), the ``tests/`` dir
    (for the ``GAME_STATE`` seed in ``test_helpers``), and ``src/`` (so the
    ``eval`` package imports). Inserts are idempotent, so importing under pytest
    (where conftest already wired these) is harmless.
    """
    here = os.path.dirname(os.path.abspath(__file__))
    src = os.path.normpath(os.path.join(here, ".."))
    repo_root = os.path.normpath(os.path.join(src, ".."))
    for path in (
        os.path.join(src, "commons"),
        os.path.join(src, "agents", "players"),
        os.path.join(repo_root, "tests"),
        src,
    ):
        if path not in sys.path:
            sys.path.insert(0, path)


_bootstrap_paths()

import constants  # noqa: E402
from parsing import parse_commands  # noqa: E402
from test_helpers import GAME_STATE  # noqa: E402

from eval.metrics import agent_performance, command_breakdown  # noqa: E402
from eval.report import build_json, render_text, write_json  # noqa: E402

# A deterministic decider: (game_state, team_name, player_id) ->
# (command_dict, latency_ms, success).
Decider = Callable[[dict, str, int], tuple[dict, float, bool]]

_DEFAULT_TEAMS = ["Lightning Cloud", "Fort Knox Athletic"]
_DEFAULT_TICKS = 90
_DEFAULT_SEED = 1234

# Per-position latency base (ms); seeded jitter is layered on top and the result
# is clamped below the hard tick budget.
_POSITION_LATENCY_BASE = {
    "GK": 600.0,
    "DEF": 740.0,
    "MID": 850.0,
    "FWD1": 560.0,
    "FWD2": 720.0,
}

# Command bias per position, further nudged by scoreline/possession in the
# decider. Weights are relative, not probabilities.
_POSITION_BIAS = {
    "GK": {"GK_DISTRIBUTE": 5, "MOVE_TO": 3, "PASS": 1},
    "DEF": {"MARK": 4, "PRESS_BALL": 3, "INTERCEPT": 2, "SLIDE_TACKLE": 2, "MOVE_TO": 2},
    "MID": {"PASS": 4, "MOVE_TO": 4, "PRESS_BALL": 2, "MARK": 2, "INTERCEPT": 1},
    "FWD1": {"MOVE_TO": 4, "SHOOT": 3, "PASS": 3, "PRESS_BALL": 1},
    "FWD2": {"MOVE_TO": 4, "SHOOT": 3, "PASS": 2, "PRESS_BALL": 1},
}


def _biased_choice(rng: random.Random, weights: dict) -> str:
    """Weighted pick over a {commandType: weight} map (deterministic via rng)."""
    types = list(weights)
    return rng.choices(types, weights=[weights[t] for t in types], k=1)[0]


def _command_for(command_type: str, player_id: int) -> dict:
    """Build a minimal valid command dict for a type (parser fills defaults)."""
    cmd: dict = {"commandType": command_type, "parameters": {}}
    if command_type == "MOVE_TO":
        cmd["parameters"] = {"target_x": 0, "target_y": 0}
    elif command_type == "SHOOT":
        cmd["parameters"] = {"aim_location": "TR", "power": 0.8}
    return cmd


def make_fake_decider(seed: int) -> Decider:
    """Return a deterministic, offline decision function.

    The pick is biased by position and nudged by scoreline/possession: a losing
    team leans attacking (SHOOT/PASS/MOVE_TO), a winning team leans defensive
    (MARK/PRESS_BALL/INTERCEPT). Latency is a seeded, position-based synthetic
    value clamped below the tick budget. ``success`` is always True on this happy
    path (mirrors the healthy example); inject a different decider to exercise
    the alert path.
    """
    budget_ms = constants.TICK_TIMEOUT_SECONDS * 1000

    def decider(game_state: dict, team_name: str, player_id: int) -> tuple[dict, float, bool]:
        tick = int(game_state.get("tick", 0))
        # Fold the team name into the seed so the two teams play distinctly while
        # staying fully deterministic (same name + seed + player + tick => same pick).
        team_salt = zlib.crc32(team_name.encode("utf-8"))
        rng = random.Random(seed + team_salt + player_id * 1000 + tick)
        position = constants.position_for(player_id)

        weights = dict(_POSITION_BIAS[position])
        score = game_state.get("score", {})
        losing = score.get("home", 0) < score.get("away", 0)
        winning = score.get("home", 0) > score.get("away", 0)
        if losing:
            for t in ("SHOOT", "PASS", "MOVE_TO"):
                if t in weights:
                    weights[t] += 3
        elif winning:
            for t in ("MARK", "PRESS_BALL", "INTERCEPT"):
                if t in weights:
                    weights[t] += 3

        command_type = _biased_choice(rng, weights)
        command = _command_for(command_type, player_id)

        base = _POSITION_LATENCY_BASE[position]
        latency = base + rng.uniform(-120.0, 220.0)
        latency = max(100.0, min(latency, budget_ms - 100.0))
        return command, round(latency, 1), True

    return decider


def _vary_state(base: dict, *, tick: int, home: int, away: int, possessor: str) -> dict:
    """Deep-copy the seed state and vary scoreline/clock/possession for a tick."""
    gs = copy.deepcopy(base)
    gs["tick"] = tick
    gs["gameTime"] = float(tick)
    gs["score"] = {"home": home, "away": away}
    gs["ball"]["possessionAgentId"] = possessor
    return gs


def simulate_match(
    *,
    ticks: int,
    teams: list[str],
    seed: int,
    decider: Decider | None = None,
) -> list[dict]:
    """Produce tick records offline (injectable ``decider`` seam for tests).

    Loops ``ticks`` times over 2 teams × 5 players. Each iteration varies the
    GAME_STATE seed (score/clock/possession), calls the decider, parses the
    returned command through ``parse_commands`` to decide ``success`` (a valid
    parsed command ⇒ success), and maps ``player_id -> position``. Fully offline
    and reproducible: same inputs -> identical records.
    """
    if decider is None:
        decider = make_fake_decider(seed)

    records: list[dict] = []
    for tick in range(ticks):
        # Deterministic, tick-driven variation of scoreline and possession.
        home = tick % 3
        away = (tick // 2) % 3
        possessor = f"agentId_{tick % 5}"
        game_state = _vary_state(
            GAME_STATE, tick=tick, home=home, away=away, possessor=possessor
        )

        for team_index, team_name in enumerate(teams):
            for player_id in range(5):
                command, latency_ms, decided_ok = decider(
                    game_state, team_name, player_id
                )
                text = _command_to_text(command)
                parsed = parse_commands(text, team_index, player_id)
                success = decided_ok and len(parsed) == 1
                records.append(
                    {
                        "team": team_name,
                        "position": constants.position_for(player_id),
                        "commandType": command["commandType"],
                        "latency_ms": latency_ms,
                        "success": success,
                    }
                )
    return records


def _command_to_text(command: dict) -> str:
    """Serialize one command dict to the JSON-array text the parser expects."""
    import json

    return json.dumps([command])


def main(argv=None) -> int:
    """CLI entry: simulate offline, print the report, write the JSON artifact."""
    records = simulate_match(
        ticks=_DEFAULT_TICKS, teams=_DEFAULT_TEAMS, seed=_DEFAULT_SEED
    )
    breakdown = command_breakdown(records)
    performance = agent_performance(records)

    print(render_text(breakdown, performance))

    artifact = build_json(breakdown, performance)
    path = write_json(artifact)
    print(f"JSON artifact written to: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
