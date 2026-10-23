"""Unit tests for the pure eval metrics (src/eval/metrics.py).

The command-breakdown fixtures reproduce the EXACT example numbers from the brief
so the core maths is pinned: counts, percentages, totals, and deterministic sort.
"""

import constants
from eval.metrics import (
    ALERT_LATENCY_MS,
    COMMAND_DISPLAY_NAMES,
    TickRecord,
    agent_performance,
    command_breakdown,
    display_name,
)
from parsing import VALID_COMMANDS

# Target command counts straight from the brief's example report. Display label
# -> raw commandType -> count.
_LIGHTNING_CLOUD = {
    "MARK": 184,
    "MOVE_TO": 94,
    "PASS": 61,
    "PRESS_BALL": 55,
    "INTERCEPT": 41,
    "SLIDE_TACKLE": 19,  # "Clear"
    "GK_DISTRIBUTE": 11,
}
_FORT_KNOX = {
    "MOVE_TO": 179,
    "PRESS_BALL": 113,
    "SHOOT": 33,
    "PASS": 28,
    "SLIDE_TACKLE": 19,  # "Clear"
    "INTERCEPT": 19,
    "GK_DISTRIBUTE": 12,
    "MARK": 2,
}


def _records_from_counts(team: str, counts: dict, latency: float = 751.0) -> list[dict]:
    """Expand a {commandType: count} map into flat success records for a team."""
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


# --- display-name mapping ----------------------------------------------------

def test_display_names_cover_every_valid_command():
    assert set(COMMAND_DISPLAY_NAMES) == VALID_COMMANDS


def test_display_name_known_and_fallback():
    assert display_name("MOVE_TO") == "Move"
    assert display_name("SLIDE_TACKLE") == "Clear"
    assert display_name("GK_DISTRIBUTE") == "GK Dist"
    # Unknown type falls back to a readable title-cased form.
    assert display_name("SOME_NEW_TYPE") == "Some New Type"


# --- command breakdown: EXACT example reproduction ---------------------------

def test_lightning_cloud_breakdown_matches_example():
    records = _records_from_counts("Lightning Cloud", _LIGHTNING_CLOUD, latency=751.0)
    breakdown = command_breakdown(records)["Lightning Cloud"]

    assert breakdown["total"] == 465
    assert breakdown["avg_latency_ms"] == 751

    expected = [
        ("Mark", 184, 40),
        ("Move", 94, 20),
        ("Pass", 61, 13),
        ("Press", 55, 12),
        ("Intercept", 41, 9),
        ("Clear", 19, 4),
        ("GK Dist", 11, 2),
    ]
    actual = [(c["display"], c["count"], c["pct"]) for c in breakdown["commands"]]
    assert actual == expected
    assert sum(c["count"] for c in breakdown["commands"]) == 465
    assert sum(c["pct"] for c in breakdown["commands"]) == 100


def test_fort_knox_breakdown_matches_example():
    records = _records_from_counts("Fort Knox Athletic", _FORT_KNOX, latency=927.0)
    breakdown = command_breakdown(records)["Fort Knox Athletic"]

    assert breakdown["total"] == 405
    assert breakdown["avg_latency_ms"] == 927

    expected = [
        ("Move", 179, 44),
        ("Press", 113, 28),
        ("Shoot", 33, 8),
        ("Pass", 28, 7),
        # 19/19 tie broken deterministically by display name ascending: Clear < Intercept.
        ("Clear", 19, 5),
        ("Intercept", 19, 5),
        ("GK Dist", 12, 3),
        ("Mark", 2, 0),
    ]
    actual = [(c["display"], c["count"], c["pct"]) for c in breakdown["commands"]]
    assert actual == expected
    assert sum(c["count"] for c in breakdown["commands"]) == 405


def test_breakdown_sorts_count_desc_with_name_tiebreak():
    records = _records_from_counts("Fort Knox Athletic", _FORT_KNOX)
    commands = command_breakdown(records)["Fort Knox Athletic"]["commands"]
    counts = [c["count"] for c in commands]
    assert counts == sorted(counts, reverse=True)
    # The 19/19 tie keeps "Clear" before "Intercept" (name asc).
    clear_idx = next(i for i, c in enumerate(commands) if c["display"] == "Clear")
    intercept_idx = next(i for i, c in enumerate(commands) if c["display"] == "Intercept")
    assert clear_idx < intercept_idx


def test_breakdown_two_teams_keyed_separately():
    records = _records_from_counts("Lightning Cloud", _LIGHTNING_CLOUD) + _records_from_counts(
        "Fort Knox Athletic", _FORT_KNOX
    )
    breakdown = command_breakdown(records)
    assert set(breakdown) == {"Lightning Cloud", "Fort Knox Athletic"}
    assert breakdown["Lightning Cloud"]["total"] == 465
    assert breakdown["Fort Knox Athletic"]["total"] == 405


def test_breakdown_avg_latency_rounds():
    records = [
        {"team": "T", "position": "MID", "commandType": "MOVE_TO", "latency_ms": 100.0, "success": True},
        {"team": "T", "position": "MID", "commandType": "MOVE_TO", "latency_ms": 101.0, "success": True},
        {"team": "T", "position": "MID", "commandType": "MOVE_TO", "latency_ms": 102.0, "success": True},
    ]
    # mean = 101.0 -> 101
    assert command_breakdown(records)["T"]["avg_latency_ms"] == 101


def test_tick_record_as_dict_feeds_breakdown():
    records = [
        TickRecord("T", "GK", "GK_DISTRIBUTE", 600.0, True).as_dict(),
        TickRecord("T", "GK", "MOVE_TO", 620.0, True).as_dict(),
    ]
    breakdown = command_breakdown(records)["T"]
    assert breakdown["total"] == 2


# --- agent performance -------------------------------------------------------

def _perf_records(team: str, position: str, latencies: list[float], successes: list[bool]):
    return [
        {"team": team, "position": position, "commandType": "MOVE_TO", "latency_ms": lat, "success": ok}
        for lat, ok in zip(latencies, successes)
    ]


def test_agent_performance_all_success_no_alert():
    records = _perf_records("T", "GK", [600.0, 610.0], [True, True])
    perf = agent_performance(records)["T"]["GK"]
    assert perf["avg_latency_ms"] == 605
    assert perf["success_pct"] == 100
    assert perf["alert"] is False


def test_agent_performance_alerts_on_low_success():
    records = _perf_records("T", "DEF", [700.0, 700.0], [True, False])
    perf = agent_performance(records)["T"]["DEF"]
    assert perf["success_pct"] == 50
    assert perf["alert"] is True


def test_agent_performance_alerts_near_budget():
    # Threshold is 80% of the 3.5s budget == 2800 ms, derived from constants.
    assert ALERT_LATENCY_MS == round(0.8 * constants.TICK_TIMEOUT_SECONDS * 1000)
    at_threshold = ALERT_LATENCY_MS
    records = _perf_records("T", "MID", [at_threshold, at_threshold], [True, True])
    perf = agent_performance(records)["T"]["MID"]
    assert perf["success_pct"] == 100
    assert perf["alert"] is True


def test_agent_performance_omits_positions_with_no_records():
    records = _perf_records("T", "GK", [600.0], [True])
    perf = agent_performance(records)["T"]
    assert set(perf) == {"GK"}


def test_agent_performance_per_position_independent():
    records = _perf_records("T", "GK", [600.0], [True]) + _perf_records(
        "T", "MID", [900.0], [True]
    )
    perf = agent_performance(records)["T"]
    assert perf["GK"]["avg_latency_ms"] == 600
    assert perf["MID"]["avg_latency_ms"] == 900
