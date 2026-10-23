"""Tests for the eval reporter (render_text/build_json/write_json) and the
offline seeded runner (simulate_match) determinism + health.
"""

import json
import os

import constants
from eval.metrics import agent_performance, command_breakdown
from eval.report import SCHEMA_VERSION, build_json, render_text, write_json
from eval.run_eval import main, make_fake_decider, simulate_match

_LIGHTNING_CLOUD = {
    "MARK": 184,
    "MOVE_TO": 94,
    "PASS": 61,
    "PRESS_BALL": 55,
    "INTERCEPT": 41,
    "SLIDE_TACKLE": 19,
    "GK_DISTRIBUTE": 11,
}


def _records_from_counts(team: str, counts: dict, latency: float = 751.0) -> list[dict]:
    records = []
    for command_type, count in counts.items():
        for _ in range(count):
            records.append(
                {
                    "team": team,
                    "position": "MID",
                    "commandType": command_type,
                    "latency_ms": latency,
                    "success": True,
                }
            )
    return records


# --- render_text -------------------------------------------------------------

def test_render_text_has_both_sections_and_team_lines():
    records = _records_from_counts("Lightning Cloud", _LIGHTNING_CLOUD, latency=751.0)
    breakdown = command_breakdown(records)
    performance = agent_performance(records)
    text = render_text(breakdown, performance)

    assert "Command breakdown" in text
    assert "Agent performance" in text
    assert "Lightning Cloud" in text
    # "N cmds · Mms avg" summary line.
    assert "465 cmds · 751ms avg" in text
    # Command rows with labels + counts + pct, in count-desc order.
    assert "Mark  184 · 40%" in text
    assert text.index("Mark  184") < text.index("Move  94")


def test_render_text_marks_alert_rows():
    # A sub-100% success position must be flagged in the rendered output.
    records = [
        {"team": "T", "position": "GK", "commandType": "MOVE_TO", "latency_ms": 600.0, "success": True},
        {"team": "T", "position": "GK", "commandType": "MOVE_TO", "latency_ms": 600.0, "success": False},
    ]
    breakdown = command_breakdown(records)
    performance = agent_performance(records)
    text = render_text(breakdown, performance)
    assert "[ALERT]" in text


def test_render_text_no_alert_when_healthy():
    records = _records_from_counts("Lightning Cloud", _LIGHTNING_CLOUD)
    text = render_text(command_breakdown(records), agent_performance(records))
    assert "[ALERT]" not in text


# --- build_json / write_json -------------------------------------------------

def test_build_json_shape_and_provenance():
    records = _records_from_counts("Lightning Cloud", _LIGHTNING_CLOUD)
    breakdown = command_breakdown(records)
    performance = agent_performance(records)
    data = build_json(
        breakdown, performance, meta={"generated_at": "2024-01-01T00:00:00+00:00"}
    )

    assert data["schema_version"] == SCHEMA_VERSION
    assert data["generated_at"] == "2024-01-01T00:00:00+00:00"
    assert data["model_id"] == constants.MODEL_ID
    assert data["tick_budget_ms"] == int(constants.TICK_TIMEOUT_SECONDS * 1000) == 3500
    assert data["command_breakdown"] == breakdown
    assert data["agent_performance"] == performance


def test_write_json_roundtrips_to_abs_path(tmp_path):
    records = _records_from_counts("Lightning Cloud", _LIGHTNING_CLOUD)
    data = build_json(
        command_breakdown(records),
        agent_performance(records),
        meta={"generated_at": "2024-01-01T00:00:00+00:00"},
    )
    path = write_json(data, out_dir=str(tmp_path))

    assert os.path.isabs(path)
    assert os.path.exists(path)
    with open(path, encoding="utf-8") as fh:
        loaded = json.load(fh)
    assert loaded == data


# --- offline runner: determinism + health -----------------------------------

def test_simulate_match_is_deterministic():
    a = simulate_match(ticks=20, teams=["A", "B"], seed=7)
    b = simulate_match(ticks=20, teams=["A", "B"], seed=7)
    assert a == b
    assert len(a) == 20 * 2 * 5  # ticks × teams × players


def test_simulate_match_default_run_all_success():
    records = simulate_match(ticks=30, teams=["A", "B"], seed=7)
    performance = agent_performance(records)
    for team, positions in performance.items():
        for position, stats in positions.items():
            assert stats["success_pct"] == 100, (team, position)


def test_simulate_match_covers_all_positions():
    records = simulate_match(ticks=10, teams=["A"], seed=3)
    positions = {r["position"] for r in records}
    # 4-role set after the fwd1/fwd2 collapse: players 3 and 4 both label FWD.
    assert positions == {"GK", "DEF", "MID", "FWD"}


def test_simulate_match_latency_under_budget():
    records = simulate_match(ticks=30, teams=["A", "B"], seed=7)
    budget_ms = constants.TICK_TIMEOUT_SECONDS * 1000
    assert all(r["latency_ms"] < budget_ms for r in records)


def test_make_fake_decider_returns_valid_command_type():
    from parsing import VALID_COMMANDS

    decider = make_fake_decider(42)
    from test_helpers import GAME_STATE

    for player_id in range(5):
        command, latency, success = decider(GAME_STATE, "A", player_id)
        assert command["commandType"] in VALID_COMMANDS
        assert latency > 0
        assert success is True


def test_main_runs_offline_and_writes_artifact(capsys, monkeypatch, tmp_path):
    # Redirect artifacts into tmp so nothing scatters; confirm it prints both
    # sections and reports the artifact path.
    monkeypatch.setattr(
        "eval.run_eval.write_json",
        lambda data, out_dir=None: __import__("eval.report", fromlist=["write_json"]).write_json(
            data, out_dir=str(tmp_path)
        ),
    )
    rc = main()
    out = capsys.readouterr().out
    assert rc == 0
    assert "Command breakdown" in out
    assert "Agent performance" in out
    assert "JSON artifact written to:" in out
    assert "Lightning Cloud" in out
    assert "Fort Knox Athletic" in out
