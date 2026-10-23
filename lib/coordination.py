"""Coordination context for AI soccer agents.

There is NO agent-to-agent communication channel in this platform.
Each agent runs in an isolated invocation and cannot write messages
to its teammates.

Two legitimate coordination sources are used instead:

1. Coach instructions  — teamChat is coach → agents (read-only for agents).
   The coach can send natural-language tactical instructions during a match.
   We surface these verbatim in the state summary so every agent acts on them.

2. Inferred teammate intent  — every agent already sees the full positions,
   velocities, and actions of all 10 players in the game state.
   Reading that data lets an agent infer what teammates are about to do
   without any message passing. This is how real multi-agent football works.

Public API
----------
    read_coach_instructions(game_state, team_id)  → list[str]
    infer_teammate_context(game_state, team_id, my_player_id)  → list[str]
    format_coordination_for_prompt(...)  → str
"""

from __future__ import annotations
import math

from state import (
    get_goal_positions,
    get_possession_info,
    holder_is_me,
    _is_my_team,
    _player_idx,
    dist,
)

# ---------------------------------------------------------------------------
# Position labels
# ---------------------------------------------------------------------------

_LABELS: dict[int, str] = {
    0: "GK",
    1: "DEF",
    2: "MID",
    3: "FWD1",
    4: "FWD2",
}


# ---------------------------------------------------------------------------
# 1. Coach instructions
# ---------------------------------------------------------------------------

def read_coach_instructions(game_state: dict, team_id: int) -> list[str]:
    """Return the coach's instructions for our team from teamChat.

    teamChat is a read-only field populated by the coach from the sideline.
    Agents must not write to it — they only read it.

    Each entry may have the shape:
        {"teamId": 0, "message": "Press higher in the second half"}
    or a flat string. Both forms are handled.

    Returns a list of instruction strings (empty if none).
    """
    raw = game_state.get("teamChat", [])
    instructions: list[str] = []

    for entry in raw:
        if isinstance(entry, str):
            instructions.append(entry.strip())
            continue
        if not isinstance(entry, dict):
            continue
        # Filter to our team when a teamId is present
        entry_team = entry.get("teamId")
        if entry_team is not None and entry_team != team_id:
            continue
        msg = entry.get("message") or entry.get("text") or entry.get("signal") or ""
        if isinstance(msg, str) and msg.strip():
            instructions.append(msg.strip())

    return instructions


# ---------------------------------------------------------------------------
# 2. Inferred teammate context
# ---------------------------------------------------------------------------

def infer_teammate_context(
    game_state: dict,
    team_id: int,
    my_player_id: int,
) -> list[str]:
    """Derive likely teammate intentions from their positions and velocities.

    No messages are passed between agents. Instead each agent reasons about
    what its teammates are *about to do* by reading the same game state snapshot.

    Returns a list of human-readable observation strings, one per relevant
    teammate, ready to be injected into the LLM state summary.
    """
    ball    = game_state.get("ball", {})
    players = game_state.get("players", [])
    _, _, we_have_ball = get_possession_info(ball, players, team_id)
    my_goal_x, opp_goal_x = get_goal_positions(team_id)
    ball_pos = ball.get("position", {"x": 0.0, "y": 0.0})

    lines: list[str] = []

    my_players = [p for p in players if _is_my_team(p, team_id)]

    for p in my_players:
        pid = _player_idx(p)
        if pid == my_player_id:
            continue

        label   = _LABELS.get(pid, f"P{pid}")
        pos     = p.get("position", {"x": 0.0, "y": 0.0})
        vel     = p.get("velocity", {"x": 0.0, "y": 0.0})
        stamina = p.get("stamina", 1.0)
        is_sprinting = p.get("isSprinting", False)

        has_ball_this_player = holder_is_me(ball, players, team_id, pid)
        d_ball   = dist(pos, ball_pos)
        d_opgoal = abs(pos.get("x", 0) - opp_goal_x)

        intent = _infer_intent(
            pid, pos, vel, stamina, is_sprinting,
            has_ball_this_player, d_ball, d_opgoal,
            we_have_ball, opp_goal_x, my_goal_x,
        )

        if intent:
            lines.append(f"  {label}(id={pid}): {intent}")

    return lines


def _infer_intent(
    pid: int,
    pos: dict,
    vel: dict,
    stamina: float,
    is_sprinting: bool,
    has_ball: bool,
    d_ball: float,
    d_opp_goal: float,
    we_have_ball: bool,
    opp_goal_x: float,
    my_goal_x: float,
) -> str:
    """Return a short intent string for one teammate."""
    sign = 1 if opp_goal_x > 0 else -1  # direction of attack
    vx   = vel.get("x", 0.0)
    vy   = vel.get("y", 0.0)
    speed = math.sqrt(vx ** 2 + vy ** 2)

    moving_toward_opp_goal = (vx * sign) > 0.5 and speed > 0.5
    moving_toward_own_goal = (vx * sign) < -0.5 and speed > 0.5
    in_opp_half  = (pos.get("x", 0) * sign) > 5
    in_own_half  = not in_opp_half
    stamina_low  = stamina < 0.45

    # GK: always anchored
    if pid == 0:
        if has_ball:
            return "has ball — about to distribute"
        return "holding position in goal"

    # Has the ball
    if has_ball:
        if d_opp_goal < 25:
            return "in shooting range — may shoot"
        if speed > 0.3:
            return "dribbling — look for pass option"
        return "on ball — waiting for run"

    # We have possession
    if we_have_ball:
        if is_sprinting and moving_toward_opp_goal:
            return f"making run into {'right' if vy > 1 else 'left' if vy < -1 else 'central'} channel"
        if in_opp_half and speed < 0.3:
            return "holding position in attacking third — available for pass"
        if in_own_half and moving_toward_opp_goal:
            return "carrying ball forward — support run"
        return "positioning for pass"

    # Opponent has possession
    if not we_have_ball:
        if d_ball < 8 and speed > 0.3:
            return "closing down ball carrier"
        if in_own_half and speed < 0.3:
            return "holding defensive shape"
        if moving_toward_own_goal:
            return "tracking back to defend"
        if stamina_low:
            return "tracking back (low stamina)"

    return ""


# ---------------------------------------------------------------------------
# 3. Format for prompt
# ---------------------------------------------------------------------------

def format_coordination_for_prompt(
    coach_instructions: list[str],
    teammate_context: list[str],
) -> str:
    """Combine coach instructions and inferred teammate context into one block."""
    lines: list[str] = []

    if coach_instructions:
        lines.append("Coach instructions:")
        for inst in coach_instructions:
            lines.append(f"  ⚽ {inst}")
    else:
        lines.append("Coach instructions: (none)")

    lines.append("")

    if teammate_context:
        lines.append("Teammate context (inferred from positions):")
        lines.extend(teammate_context)
    else:
        lines.append("Teammate context: (no clear intent readable)")

    return "\n".join(lines)
