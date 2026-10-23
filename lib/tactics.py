"""Dynamic formation and tactical positioning for AI soccer agents.

Replaces the hardcoded `default_x_factor` constants in FallbackConfig with
situation-aware home positions that adapt to score, time remaining, and the
current game phase.

Why this matters
----------------
A team leading 2-0 with 60 seconds left should play 10–15 units deeper than
their normal shape.  A team losing by 2 goals with 2 minutes left should push
every outfield player 15–20 units higher.  Currently both scenarios use the
same hardcoded factors from fallback.py — this module gives the fallback
engine the context it needs to make the right call.

Design
------
- `get_formation` is the single public function. It returns a `Formation`
  dataclass that maps each player_id to a (home_x, home_y) target and a
  recommended stance.
- The existing `FallbackConfig` is not modified; instead `apply_formation`
  patches the live config values at runtime for one tick.
- The state summary calls `format_formation_for_prompt` to give the LLM a
  one-line hint about the tactical shape in use.

Coordinate system
-----------------
  x: -55 (HOME goal) to +55 (AWAY goal)
  y: -35 to +35
  Team 0 (HOME) attacks toward +x, defends toward -x.
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum
from typing import NamedTuple

from game_phase import GamePhase, Phase


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

class TacticalShape(str, Enum):
    ULTRA_DEFENSIVE = "ULTRA_DEFENSIVE"
    DEFENSIVE       = "DEFENSIVE"
    BALANCED        = "BALANCED"
    ATTACKING       = "ATTACKING"
    ALL_OUT_ATTACK  = "ALL_OUT_ATTACK"
    COUNTER         = "COUNTER"


class PlayerFormation(NamedTuple):
    home_x: float
    home_y: float
    stance: int        # 0=Balanced, 1=Attack, 2=Defend


@dataclass(frozen=True)
class Formation:
    shape: TacticalShape
    positions: dict[int, PlayerFormation]   # player_id → formation
    description: str                        # short text for the LLM prompt


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def get_formation(
    team_id: int,
    score: dict,
    game_time: float,
    phase: GamePhase,
    half_duration: float = 300.0,
) -> Formation:
    """Return the current tactical formation based on situation.

    Parameters
    ----------
    team_id       : 0 = HOME, 1 = AWAY
    score         : {"home": int, "away": int}
    game_time     : seconds elapsed this half
    phase         : GamePhase from game_phase.detect_phase()
    half_duration : assumed half length (seconds)
    """
    atk_x = 55.0 if team_id == 0 else -55.0
    def_x = -atk_x
    sign  = 1 if atk_x > 0 else -1   # +1 for HOME, -1 for AWAY

    score_diff  = _score_diff(score, team_id)
    time_left   = max(0.0, half_duration - game_time)
    shape       = _choose_shape(score_diff, time_left, phase)

    positions   = _build_positions(shape, def_x, atk_x, sign)
    description = _describe(shape, score_diff, time_left)

    return Formation(shape=shape, positions=positions, description=description)


def format_formation_for_prompt(formation: Formation, my_player_id: int) -> str:
    """Return a one-line hint to inject into the LLM state summary."""
    pf = formation.positions.get(my_player_id)
    if pf:
        stance_name = {0: "Balanced", 1: "Attack", 2: "Defend"}.get(pf.stance, "Balanced")
        return (
            f"Tactical shape: {formation.shape.value} — {formation.description} "
            f"(your home zone: x={pf.home_x:.1f}, y={pf.home_y:.1f}, stance={stance_name})"
        )
    return f"Tactical shape: {formation.shape.value} — {formation.description}"


def get_player_home(formation: Formation, player_id: int) -> tuple[float, float] | None:
    """Convenience accessor — returns (home_x, home_y) or None."""
    pf = formation.positions.get(player_id)
    return (pf.home_x, pf.home_y) if pf else None


# ---------------------------------------------------------------------------
# Shape selection
# ---------------------------------------------------------------------------

def _choose_shape(score_diff: int, time_left: float, phase: GamePhase) -> TacticalShape:
    """Pick a shape from situation signals."""

    # Phase overrides first — hard tactical moments
    if phase.phase == Phase.COUNTER:
        return TacticalShape.COUNTER
    if phase.phase == Phase.DEFENDING and score_diff <= 0:
        return TacticalShape.ULTRA_DEFENSIVE

    # Score + time scenarios
    if score_diff >= 2 and time_left < 90:
        return TacticalShape.ULTRA_DEFENSIVE
    if score_diff >= 1 and time_left < 60:
        return TacticalShape.DEFENSIVE
    if score_diff <= -2 and time_left < 120:
        return TacticalShape.ALL_OUT_ATTACK
    if score_diff <= -1 and time_left < 90:
        return TacticalShape.ATTACKING
    if score_diff < 0:
        return TacticalShape.ATTACKING
    if score_diff > 0:
        return TacticalShape.DEFENSIVE

    return TacticalShape.BALANCED


# ---------------------------------------------------------------------------
# Formation tables
# ---------------------------------------------------------------------------
# GK=0, DEF=1, MID=2, FWD1=3, FWD2=4
# Positions are expressed as fractions of goal_x so they flip correctly for
# AWAY teams.  Multiply by sign to get absolute x.
#
# Format: (x_fraction_of_goal, y, stance)
#   x_fraction uses def_x for defensive anchors, atk_x for attacking ones.

def _build_positions(
    shape: TacticalShape,
    def_x: float,
    atk_x: float,
    sign: int,
) -> dict[int, PlayerFormation]:
    """Build the per-player formation dict for the given shape."""

    def pos(x: float, y: float, stance: int) -> PlayerFormation:
        return PlayerFormation(home_x=round(x, 1), home_y=round(y, 1), stance=stance)

    d = def_x   # e.g. -55 for HOME
    a = atk_x   # e.g. +55 for HOME
    s = sign    # +1 for HOME, -1 for AWAY

    tables: dict[TacticalShape, dict[int, PlayerFormation]] = {
        TacticalShape.ULTRA_DEFENSIVE: {
            0: pos(d * 0.92,  0.0, 2),
            1: pos(d * 0.50,  0.0, 2),
            2: pos(d * 0.25,  0.0, 2),
            3: pos(s *  5.0, -5.0, 2),
            4: pos(s *  5.0,  5.0, 2),
        },
        TacticalShape.DEFENSIVE: {
            0: pos(d * 0.92,  0.0, 2),
            1: pos(d * 0.45,  0.0, 2),
            2: pos(s *  2.0,  0.0, 0),
            3: pos(s * 15.0, -5.0, 0),
            4: pos(s * 15.0,  5.0, 0),
        },
        TacticalShape.BALANCED: {
            0: pos(d * 0.90,  0.0, 2),
            1: pos(d * 0.40,  0.0, 2),
            2: pos(s *  0.0,  0.0, 0),
            3: pos(a * 0.40, -8.0, 1),
            4: pos(a * 0.40,  8.0, 1),
        },
        TacticalShape.ATTACKING: {
            0: pos(d * 0.88,  0.0, 2),
            1: pos(d * 0.30,  0.0, 0),
            2: pos(s * 10.0,  0.0, 1),
            3: pos(a * 0.55, -8.0, 1),
            4: pos(a * 0.55,  8.0, 1),
        },
        TacticalShape.ALL_OUT_ATTACK: {
            0: pos(d * 0.85,  0.0, 2),
            1: pos(s * 10.0,  0.0, 1),
            2: pos(s * 20.0,  0.0, 1),
            3: pos(a * 0.65, -5.0, 1),
            4: pos(a * 0.65,  5.0, 1),
        },
        TacticalShape.COUNTER: {
            0: pos(d * 0.92,  0.0, 2),
            1: pos(d * 0.40,  0.0, 2),   # DEF holds back during counter
            2: pos(s * 15.0,  0.0, 1),   # MID bursts forward
            3: pos(a * 0.60, -8.0, 1),
            4: pos(a * 0.60,  8.0, 1),
        },
    }

    return tables.get(shape, tables[TacticalShape.BALANCED])


# ---------------------------------------------------------------------------
# Description strings
# ---------------------------------------------------------------------------

_DESCRIPTIONS: dict[TacticalShape, str] = {
    TacticalShape.ULTRA_DEFENSIVE: "hold deep, defend the lead at all costs",
    TacticalShape.DEFENSIVE:       "stay compact, don't overcommit forward",
    TacticalShape.BALANCED:        "maintain shape, look for openings",
    TacticalShape.ATTACKING:       "push higher, create overloads in the final third",
    TacticalShape.ALL_OUT_ATTACK:  "everyone forward — need a goal urgently",
    TacticalShape.COUNTER:         "sprint into channels, exploit the space behind them",
}


def _describe(shape: TacticalShape, score_diff: int, time_left: float) -> str:
    base = _DESCRIPTIONS.get(shape, "maintain position")
    if time_left < 60:
        base += f" ({int(time_left)}s left)"
    return base


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _score_diff(score: dict, team_id: int) -> int:
    """Positive = we're winning."""
    if team_id == 0:
        return score.get("home", 0) - score.get("away", 0)
    return score.get("away", 0) - score.get("home", 0)
