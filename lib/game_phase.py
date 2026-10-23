"""Game phase detection for AI soccer agents.

Classifies every tick into one of six tactical phases so agents receive a
named situational context instead of having to infer it from raw numbers.

Phases
------
KICKOFF    — match just started or restarted after a goal
SET_PIECE  — free kick, corner, throw-in, goal kick in progress
COUNTER    — team just won possession in own half and ball is moving fast
ATTACKING  — team has possession in opponent's half
PRESSING   — team just lost the ball and is within pressing range
DEFENDING  — opponents are in dangerous positions near our goal
BALANCED   — none of the above; settled mid-game situation

Each phase also ships an action_hint string written in second-person so it
can be pasted verbatim into the LLM state summary without extra formatting.
"""

from __future__ import annotations
from dataclasses import dataclass
from enum import Enum

from state import (
    get_goal_positions,
    get_possession_info,
    _is_my_team,
    dist,
)


class Phase(str, Enum):
    KICKOFF   = "KICKOFF"
    SET_PIECE = "SET_PIECE"
    COUNTER   = "COUNTER"
    ATTACKING = "ATTACKING"
    PRESSING  = "PRESSING"
    DEFENDING = "DEFENDING"
    BALANCED  = "BALANCED"


# Play modes the server reports for set pieces
_SET_PIECE_MODES = {
    "FREE_KICK", "FREEKICK",
    "CORNER", "CORNER_KICK",
    "THROW_IN", "THROWIN",
    "GOAL_KICK", "GOALKICK",
    "PENALTY",
}

# Play modes that signal a kickoff / restart
_KICKOFF_MODES = {"KICKOFF", "KICK_OFF", "KICKOFF_HOME", "KICKOFF_AWAY"}


@dataclass(frozen=True)
class GamePhase:
    phase: Phase
    action_hint: str          # short instruction injected into LLM prompt
    urgency: float            # 0.0 = calm, 1.0 = maximum urgency


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def detect_phase(game_state: dict, team_id: int) -> GamePhase:
    """Classify the current game tick into a tactical phase.

    Parameters
    ----------
    game_state : dict  Full game state payload from the server.
    team_id    : int   0 = HOME, 1 = AWAY.

    Returns
    -------
    GamePhase with .phase, .action_hint, and .urgency.
    """
    play_mode   = (game_state.get("playMode") or "OPEN_PLAY").upper()
    ball        = game_state.get("ball", {})
    players     = game_state.get("players", [])
    score       = game_state.get("score", {})
    game_time   = float(game_state.get("gameTime", 0))

    ball_pos    = ball.get("position", {"x": 0, "y": 0})
    ball_vel    = ball.get("velocity", {"x": 0, "y": 0})
    ball_speed  = dist(ball_vel, {"x": 0, "y": 0})

    my_goal_x, opp_goal_x = get_goal_positions(team_id)
    _, _, we_have_ball = get_possession_info(ball, players, team_id)

    # ---- 1. Kickoff / restart -------------------------------------------
    if play_mode in _KICKOFF_MODES:
        return GamePhase(
            Phase.KICKOFF,
            "KICKOFF — hold your formation until the ball is played.",
            urgency=0.3,
        )

    # ---- 2. Set piece ---------------------------------------------------
    if play_mode in _SET_PIECE_MODES:
        side = _set_piece_side(play_mode, team_id)
        if side == "ours":
            return GamePhase(
                Phase.SET_PIECE,
                f"SET PIECE ({play_mode}) in our favour — move to your assigned position now.",
                urgency=0.8,
            )
        else:
            return GamePhase(
                Phase.SET_PIECE,
                f"SET PIECE ({play_mode}) against us — get into a defensive shape immediately.",
                urgency=0.9,
            )

    ball_in_our_half    = _in_our_half(ball_pos["x"], my_goal_x)
    ball_in_their_half  = not ball_in_our_half
    opponents_near_goal = _opponents_near_goal(players, team_id, my_goal_x, threshold=30.0)

    # ---- 3. Counter-attack — we just won ball in our half ---------------
    if we_have_ball and ball_in_our_half and ball_speed > 1.0:
        return GamePhase(
            Phase.COUNTER,
            "COUNTER-ATTACK — sprint forward immediately, spread wide and look for the pass.",
            urgency=0.95,
        )

    # ---- 4. Attacking — we have possession in their half ----------------
    if we_have_ball and ball_in_their_half:
        return GamePhase(
            Phase.ATTACKING,
            "ATTACKING — maintain possession, create shooting opportunities, support the ball carrier.",
            urgency=0.6,
        )

    # ---- 5. Defending — opponents threatening our goal ------------------
    if opponents_near_goal >= 2:
        return GamePhase(
            Phase.DEFENDING,
            "DEFENDING — compact shape, track runners, do not leave gaps near your goal.",
            urgency=0.95,
        )

    # ---- 6. Pressing — we just lost possession and ball is close --------
    if not we_have_ball:
        my_players = [p for p in players if _is_my_team(p, team_id)]
        if my_players:
            avg_dist = sum(dist(p.get("position", {}), ball_pos) for p in my_players) / len(my_players)
            if avg_dist < 22.0:
                return GamePhase(
                    Phase.PRESSING,
                    "PRESSING — close down immediately, win the ball back high.",
                    urgency=0.85,
                )

    # ---- 7. Balanced / default ------------------------------------------
    score_diff = _score_diff(score, team_id)
    time_left  = max(0.0, 300.0 - game_time)   # assume 300 s halves; safe default

    if score_diff > 0 and time_left < 60:
        return GamePhase(
            Phase.BALANCED,
            "HOLD THE LEAD — stay compact, recycle possession, don't overcommit forward.",
            urgency=0.5,
        )
    if score_diff < -1 and time_left < 120:
        return GamePhase(
            Phase.BALANCED,
            "CHASING THE GAME — push higher, take risks, create chances quickly.",
            urgency=0.75,
        )

    return GamePhase(
        Phase.BALANCED,
        "BALANCED — maintain shape, look for openings, stay disciplined.",
        urgency=0.4,
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _in_our_half(ball_x: float, my_goal_x: float) -> bool:
    """True when the ball is on the same side as our goal."""
    if my_goal_x < 0:   # HOME team — our half is x < 0
        return ball_x < 0
    return ball_x > 0   # AWAY team — our half is x > 0


def _opponents_near_goal(players: list, team_id: int, my_goal_x: float, threshold: float) -> int:
    """Count opponents within *threshold* units of our goal."""
    count = 0
    for p in players:
        if _is_my_team(p, team_id):
            continue
        px = p.get("position", {}).get("x", 0)
        if abs(px - my_goal_x) < threshold:
            count += 1
    return count


def _set_piece_side(play_mode: str, team_id: int) -> str:
    """Return 'ours' or 'theirs' — best-effort from the mode string."""
    if team_id == 0:
        if "HOME" in play_mode:
            return "ours"
        if "AWAY" in play_mode:
            return "theirs"
    else:
        if "AWAY" in play_mode:
            return "ours"
        if "HOME" in play_mode:
            return "theirs"
    # mode has no team qualifier — assume ours (more conservative: get in position)
    return "ours"


def _score_diff(score: dict, team_id: int) -> int:
    """Positive means we're winning."""
    if team_id == 0:
        return score.get("home", 0) - score.get("away", 0)
    return score.get("away", 0) - score.get("home", 0)
