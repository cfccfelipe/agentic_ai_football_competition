"""Tests for the planner — strategy selection by hint and by rule."""

import copy
import time

import constants
import planner
from constants import DEFAULT_STRATEGY
from test_helpers import GAME_STATE

DESCRIPTIONS = "- balanced: default\n- aggressive: chase goals\n- defensive: protect lead"


def _state(home, away, game_time):
    gs = copy.deepcopy(GAME_STATE)
    gs["score"] = {"home": home, "away": away}
    gs["gameTime"] = game_time
    return gs


def test_explicit_hint_passes_through():
    for s in ("balanced", "aggressive", "defensive"):
        assert planner.select_strategy(GAME_STATE, 0, DESCRIPTIONS, hint=s) == s


def test_invalid_hint_falls_back_to_default():
    assert planner.select_strategy(GAME_STATE, 0, DESCRIPTIONS, hint="bogus") == DEFAULT_STRATEGY


def test_rule_losing_late_is_aggressive():
    gs = _state(home=0, away=1, game_time=75)  # HOME losing, late
    assert planner.rule_based_strategy(gs, 0) == "aggressive"


def test_rule_winning_late_is_defensive():
    gs = _state(home=2, away=0, game_time=80)  # HOME winning, late
    assert planner.rule_based_strategy(gs, 0) == "defensive"


def test_rule_early_level_is_balanced():
    gs = _state(home=1, away=1, game_time=10)
    assert planner.rule_based_strategy(gs, 0) == "balanced"


def test_rule_two_goals_down_is_aggressive_anytime():
    gs = _state(home=0, away=2, game_time=30)
    assert planner.rule_based_strategy(gs, 0) == "aggressive"


def test_auto_falls_back_to_rule_when_llm_unavailable():
    # agent_factory raises → planner must use the rule-based path.
    def broken_factory():
        raise RuntimeError("no model")

    gs = _state(home=0, away=1, game_time=75)
    result = planner.select_strategy(
        gs, 0, DESCRIPTIONS, hint="auto", agent_factory=broken_factory
    )
    assert result == "aggressive"


def test_auto_uses_llm_choice_when_available():
    def fake_factory():
        return lambda prompt: "I recommend defensive play here."

    gs = _state(home=2, away=0, game_time=80)
    result = planner.select_strategy(
        gs, 0, DESCRIPTIONS, hint="auto", agent_factory=fake_factory
    )
    assert result == "defensive"


def test_auto_falls_back_to_rule_when_llm_times_out(monkeypatch):
    # A strategy call slower than the tick budget must not block: it falls
    # through to the rule-based path.
    monkeypatch.setattr(constants, "TICK_TIMEOUT_SECONDS", 0.05)

    def slow_factory():
        def agent(prompt):
            time.sleep(1.0)
            return "defensive"
        return agent

    gs = _state(home=0, away=1, game_time=75)  # rule would pick aggressive
    start = time.monotonic()
    result = planner.select_strategy(
        gs, 0, DESCRIPTIONS, hint="auto", agent_factory=slow_factory
    )
    elapsed = time.monotonic() - start

    assert elapsed < 1.0
    assert result == "aggressive"


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"{len(fns)} tests passed")
