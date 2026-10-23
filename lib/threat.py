"""Opponent threat assessment for AI soccer agents.

Computes a threat_score (0.0–1.0) for each opponent based on:
  - Distance to our goal (closer = more dangerous)
  - Whether they carry or are near the ball
  - Their velocity vector (running toward goal raises threat)
  - Whether a teammate is already marking them

The score is intentionally capped at 1.0 and anchored at 0.0 so it is safe
to compare across ticks and game states without normalisation by the caller.

Usage
-----
    from threat import assess_threats

    threats = assess_threats(game_state, team_id)
    # → [ ThreatInfo(player_id=1, score=0.82, is_marked=False, label="⚠ UNMARKED"), ... ]

The returned list is sorted by score descending so threats[0] is always the
most dangerous opponent — convenient for the DEF fallback and for injecting
into the LLM state summary.
"""

from __future__ import annotations
from dataclasses import dataclass
import math

from state import (
    get_goal_positions,
    get_possession_info,
    _is_my_team,
    _player_idx,
    dist,
)


@dataclass(frozen=True)
class ThreatInfo:
    player_id: int
    score: float        # 0.0 – 1.0
    is_marked: bool
    distance_to_goal: float
    label: str          # human-readable tag for the LLM prompt


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def assess_threats(game_state: dict, team_id: int) -> list[ThreatInfo]:
    """Return a threat-ranked list of opponent ThreatInfo objects.

    Sorted by score descending; empty list if no opponents found.
    """
    ball    = game_state.get("ball", {})
    players = game_state.get("players", [])

    my_goal_x, _  = get_goal_positions(team_id)
    goal_pos       = {"x": my_goal_x, "y": 0.0}

    possession_id, _, we_have_ball = get_possession_info(ball, players, team_id)
    ball_pos = ball.get("position", {"x": 0, "y": 0})

    opponents  = [p for p in players if not _is_my_team(p, team_id)]
    my_players = [p for p in players if  _is_my_team(p, team_id)]

    # Pre-compute which opponent ids are being marked by our side.
    # A player is "marked" if any teammate issued a MARK command last action,
    # OR — as a simpler runtime proxy — is within tight_mark_distance of a
    # teammate. We use the proximity proxy here since lastAction can be stale.
    marked_ids = _find_marked_ids(opponents, my_players, tight_mark_distance=4.0)

    results: list[ThreatInfo] = []
    for opp in opponents:
        opp_pos  = opp.get("position", {"x": 0, "y": 0})
        opp_vel  = opp.get("velocity", {"x": 0, "y": 0})
        opp_id   = _player_idx(opp)

        d_goal   = dist(opp_pos, goal_pos)
        d_ball   = dist(opp_pos, ball_pos)
        is_carrier = (not we_have_ball) and (d_ball < 3.0)
        is_marked  = opp_id in marked_ids

        score = _compute_score(
            d_goal     = d_goal,
            d_ball     = d_ball,
            is_carrier = is_carrier,
            velocity   = opp_vel,
            my_goal_x  = my_goal_x,
            is_marked  = is_marked,
        )

        label = _make_label(score, is_marked, is_carrier, opp_vel, my_goal_x)
        results.append(ThreatInfo(
            player_id       = opp_id,
            score           = round(score, 2),
            is_marked       = is_marked,
            distance_to_goal= round(d_goal, 1),
            label           = label,
        ))

    results.sort(key=lambda t: t.score, reverse=True)
    return results


def format_threats_for_prompt(threats: list[ThreatInfo]) -> str:
    """Return a compact multi-line string ready for the LLM state summary."""
    if not threats:
        return "  (no opponents visible)"
    lines = []
    for t in threats:
        lines.append(
            f"  P{t.player_id}: threat={t.score:.2f} distGoal={t.distance_to_goal:.1f} {t.label}"
        )
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_GOAL_RANGE = 55.0   # max meaningful distance from goal on this field


def _compute_score(
    d_goal: float,
    d_ball: float,
    is_carrier: bool,
    velocity: dict,
    my_goal_x: float,
    is_marked: bool,
) -> float:
    """Combine multiple signals into a 0.0–1.0 threat score."""

    # --- Distance to goal (primary signal) ---
    # Sigmoid-like curve: very dangerous inside 20 units, drops off beyond 40
    proximity = max(0.0, 1.0 - (d_goal / _GOAL_RANGE))
    proximity = proximity ** 0.6   # ease the curve so mid-range still matters

    # --- Ball proximity: carrying or within 8 units ---
    if is_carrier:
        ball_factor = 1.0
    elif d_ball < 8.0:
        ball_factor = 0.6
    else:
        ball_factor = 0.0

    # --- Velocity toward our goal ---
    vx = velocity.get("x", 0.0)
    speed = math.sqrt(vx ** 2 + velocity.get("y", 0.0) ** 2)
    # HOME goal is at -x; running toward it means negative vx.
    # AWAY goal is at +x; running toward it means positive vx.
    toward = (-vx if my_goal_x < 0 else vx)
    heading_factor = max(0.0, min(1.0, toward / 3.0)) if speed > 0.3 else 0.0

    # --- Combine ---
    raw = (
        0.50 * proximity
        + 0.25 * ball_factor
        + 0.25 * heading_factor
    )

    # Marking reduces perceived threat by 25% (not eliminated — marked players
    # can still break free)
    if is_marked:
        raw *= 0.75

    return min(1.0, max(0.0, raw))


def _find_marked_ids(opponents: list, my_players: list, tight_mark_distance: float) -> set[int]:
    """Return the set of opponent ids that have a nearby teammate (proxy for marking)."""
    marked: set[int] = set()
    for opp in opponents:
        opp_pos = opp.get("position", {"x": 0, "y": 0})
        for my_p in my_players:
            my_pos = my_p.get("position", {"x": 0, "y": 0})
            if dist(opp_pos, my_pos) <= tight_mark_distance:
                marked.add(_player_idx(opp))
                break
    return marked


def _make_label(score: float, is_marked: bool, is_carrier: bool, velocity: dict, my_goal_x: float) -> str:
    """Build a short text annotation for the LLM."""
    parts = []

    if is_carrier:
        parts.append("has ball")

    vx = velocity.get("x", 0.0)
    speed = math.sqrt(vx ** 2 + velocity.get("y", 0.0) ** 2)
    toward = (-vx if my_goal_x < 0 else vx)
    if speed > 0.5 and toward > 0.3:
        parts.append("running toward goal")

    if is_marked:
        parts.append("marked")
    elif score >= 0.6:
        parts.append("⚠ UNMARKED")

    if score >= 0.75:
        prefix = "🔴"
    elif score >= 0.45:
        prefix = "🟡"
    else:
        prefix = "🟢"

    detail = ", ".join(parts) if parts else "no immediate danger"
    return f"{prefix} {detail}"
