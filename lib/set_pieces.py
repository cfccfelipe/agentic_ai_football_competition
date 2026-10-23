"""Set-piece awareness for AI soccer agents.

Detects when the game is in a set-piece state (corner, free kick, throw-in,
goal kick, penalty, kickoff) and returns per-position target coordinates plus
a short instruction string for the LLM state summary.

Why here?
---------
All five agents currently treat every play mode identically — they process a
corner kick the same way as open play. Set pieces are some of the highest
expected-value moments in football; adding positional awareness here costs
nothing at runtime (it is just a lookup) and injects high-signal guidance
that the LLM would otherwise have to invent from scratch every tick.

Design
------
- `detect_set_piece` returns a SetPieceInfo or None (None = open play, no op).
- The LLM state summary calls this and appends one line if non-None.
- The fallback rule engine also calls this to override MOVE_TO targets during
  set pieces so the rule-based players sprint to the right spot even when the
  LLM does not.

Coordinate system
-----------------
  x: -55 (HOME goal) to +55 (AWAY goal)
  y: -35 to +35
  Team 0 (HOME) attacks toward +x, defends toward -x.
  Team 1 (AWAY) attacks toward -x, defends toward +x.
"""

from __future__ import annotations
from dataclasses import dataclass, field


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class SetPieceInfo:
    mode: str                               # normalised mode string
    is_ours: bool                           # True = our set piece
    instruction: str                        # injected into LLM prompt
    positions: dict[int, tuple[float, float]] = field(default_factory=dict)
    """Suggested (x, y) per player_id — only includes players that should move."""


# ---------------------------------------------------------------------------
# Play-mode classification
# ---------------------------------------------------------------------------

_SET_PIECE_MODES = {
    "FREE_KICK", "FREEKICK",
    "CORNER", "CORNER_KICK",
    "THROW_IN", "THROWIN",
    "GOAL_KICK", "GOALKICK",
    "PENALTY",
    "KICKOFF", "KICK_OFF", "KICKOFF_HOME", "KICKOFF_AWAY",
}


def detect_set_piece(game_state: dict, team_id: int) -> SetPieceInfo | None:
    """Return a SetPieceInfo if the current play mode is a set piece, else None.

    Parameters
    ----------
    game_state : dict   Full game state payload.
    team_id    : int    0 = HOME, 1 = AWAY.
    """
    raw_mode = (game_state.get("playMode") or "OPEN_PLAY").upper()
    if raw_mode not in _SET_PIECE_MODES and not any(k in raw_mode for k in _SET_PIECE_MODES):
        return None

    is_ours  = _is_our_set_piece(raw_mode, team_id)
    ball_pos = game_state.get("ball", {}).get("position", {"x": 0.0, "y": 0.0})

    return _build_info(raw_mode, is_ours, team_id, ball_pos)


# ---------------------------------------------------------------------------
# Set-piece builders
# ---------------------------------------------------------------------------

def _build_info(mode: str, is_ours: bool, team_id: int, ball_pos: dict) -> SetPieceInfo:
    """Dispatch to the right builder."""
    atk_x = 55.0 if team_id == 0 else -55.0   # our attacking goal x
    def_x = -atk_x                             # our defending goal x

    if "KICKOFF" in mode or "KICK_OFF" in mode:
        return _kickoff(is_ours, team_id, atk_x, def_x, mode)
    if "CORNER" in mode:
        return _corner(is_ours, team_id, atk_x, def_x, ball_pos, mode)
    if "FREE_KICK" in mode or "FREEKICK" in mode:
        return _free_kick(is_ours, team_id, atk_x, def_x, ball_pos, mode)
    if "GOAL_KICK" in mode or "GOALKICK" in mode:
        return _goal_kick(is_ours, team_id, atk_x, def_x, mode)
    if "THROW_IN" in mode or "THROWIN" in mode:
        return _throw_in(is_ours, team_id, ball_pos, mode)
    if "PENALTY" in mode:
        return _penalty(is_ours, team_id, atk_x, def_x, mode)

    # Fallback — shouldn't reach here given the check in detect_set_piece
    return SetPieceInfo(mode=mode, is_ours=is_ours,
                        instruction=f"SET PIECE ({mode}) — get into position.")


def _kickoff(is_ours: bool, team_id: int, atk_x: float, def_x: float, mode: str) -> SetPieceInfo:
    # All players hold compact formation around centre line
    # GK=0, DEF=1, MID=2, FWD1=3, FWD2=4
    sign = 1 if atk_x > 0 else -1
    positions = {
        0: (def_x * 0.9,  0.0),     # GK near own goal
        1: (def_x * 0.4,  0.0),     # DEF back
        2: (sign * -3.0,  0.0),     # MID just behind centre
        3: (sign *  3.0, -5.0),     # FWD1 near centre
        4: (sign *  3.0,  5.0),     # FWD2 near centre
    }
    hint = "KICKOFF — hold compact formation, short pass to MID first."
    return SetPieceInfo(mode=mode, is_ours=is_ours, instruction=hint, positions=positions)


def _corner(is_ours: bool, team_id: int, atk_x: float, def_x: float,
            ball_pos: dict, mode: str) -> SetPieceInfo:
    sign = 1 if atk_x > 0 else -1
    if is_ours:
        # Attacking corner: forwards attack the box, MID on edge, DEF holds
        positions = {
            0: (def_x * 0.9,  0.0),           # GK stays back
            1: (sign * 10.0,  0.0),            # DEF holds halfway
            2: (atk_x * 0.6,  0.0),            # MID edge of box
            3: (atk_x * 0.85, -8.0),           # FWD1 near post
            4: (atk_x * 0.85,  8.0),           # FWD2 far post
        }
        hint = "CORNER (ours) — FWD1 attack near post, FWD2 far post, MID on edge of box."
    else:
        # Defensive corner: everyone back, pack the box
        positions = {
            0: (def_x * 0.92,  0.0),           # GK on line
            1: (def_x * 0.75, -5.0),           # DEF on post
            2: (def_x * 0.70,  5.0),           # MID blocks near post
            3: (sign * 10.0, -10.0),           # FWD1 ready for counter
            4: (sign * 10.0,  10.0),           # FWD2 ready for counter
        }
        hint = "CORNER (theirs) — pack the box, clear your lines, stay goal-side."
    return SetPieceInfo(mode=mode, is_ours=is_ours, instruction=hint, positions=positions)


def _free_kick(is_ours: bool, team_id: int, atk_x: float, def_x: float,
               ball_pos: dict, mode: str) -> SetPieceInfo:
    sign = 1 if atk_x > 0 else -1
    bx = ball_pos.get("x", 0.0)
    # Determine whether the free kick is in attacking or defensive half
    in_attacking_half = (bx * sign) > 0

    if is_ours and in_attacking_half:
        positions = {
            0: (def_x * 0.9,  0.0),
            1: (sign * 5.0,   0.0),
            2: (bx + sign * 5, -8.0),
            3: (atk_x * 0.8, -10.0),
            4: (atk_x * 0.8,  10.0),
        }
        hint = "FREE KICK (ours, attacking) — forwards get in the box, create space."
    elif is_ours and not in_attacking_half:
        positions = {
            0: (def_x * 0.9,  0.0),
            1: (sign * -5.0,  5.0),
            2: (sign *  5.0,  0.0),
            3: (sign * 10.0, -5.0),
            4: (sign * 10.0,  5.0),
        }
        hint = "FREE KICK (ours, defensive) — play short, move into space quickly."
    elif not is_ours and in_attacking_half:
        positions = {
            0: (def_x * 0.92, 0.0),
            1: (def_x * 0.75, -5.0),
            2: (def_x * 0.70,  5.0),
            3: (sign * 5.0,  -5.0),
            4: (sign * 5.0,   5.0),
        }
        hint = "FREE KICK (theirs, dangerous) — wall up, mark runners, stay compact."
    else:
        positions = {
            0: (def_x * 0.85, 0.0),
            1: (sign * -8.0,  0.0),
            2: (sign *  0.0,  0.0),
            3: (sign * 15.0, -5.0),
            4: (sign * 15.0,  5.0),
        }
        hint = "FREE KICK (theirs, low danger) — stay organised, ready to press."
    return SetPieceInfo(mode=mode, is_ours=is_ours, instruction=hint, positions=positions)


def _goal_kick(is_ours: bool, team_id: int, atk_x: float, def_x: float, mode: str) -> SetPieceInfo:
    sign = 1 if atk_x > 0 else -1
    if is_ours:
        positions = {
            0: (def_x * 0.9,  0.0),
            1: (sign * -5.0, -8.0),
            2: (sign *  5.0,  0.0),
            3: (sign * 15.0, -8.0),
            4: (sign * 15.0,  8.0),
        }
        hint = "GOAL KICK (ours) — spread wide to receive, build from the back."
    else:
        positions = {
            0: (def_x * 0.92, 0.0),
            1: (sign * -3.0,  0.0),
            2: (sign *  5.0,  0.0),
            3: (sign * 20.0, -5.0),
            4: (sign * 20.0,  5.0),
        }
        hint = "GOAL KICK (theirs) — press high, win it in their half."
    return SetPieceInfo(mode=mode, is_ours=is_ours, instruction=hint, positions=positions)


def _throw_in(is_ours: bool, team_id: int, ball_pos: dict, mode: str) -> SetPieceInfo:
    bx = ball_pos.get("x", 0.0)
    by = ball_pos.get("y", 0.0)
    # Offer short and long options either side of the ball
    positions = {
        1: (bx - 5.0, by * 0.5),
        2: (bx,       by * 0.3),
        3: (bx + 5.0, by * 0.3),
        4: (bx + 8.0, by * 0.5),
    }
    hint = "THROW IN — create passing angles near the ball, then move quickly."
    return SetPieceInfo(mode=mode, is_ours=is_ours, instruction=hint, positions=positions)


def _penalty(is_ours: bool, team_id: int, atk_x: float, def_x: float, mode: str) -> SetPieceInfo:
    sign = 1 if atk_x > 0 else -1
    if is_ours:
        positions = {
            0: (def_x * 0.9,  0.0),
            1: (sign *  5.0, -5.0),
            2: (sign * 10.0,  0.0),
            3: (atk_x * 0.85, 0.0),   # taker
            4: (sign * 20.0, 10.0),
        }
        hint = "PENALTY (ours) — FWD1 is the taker. Everyone else hold position."
    else:
        positions = {
            0: (def_x * 0.92, 0.0),   # GK saves
            1: (def_x * 0.7, -5.0),
            2: (def_x * 0.5,  0.0),
            3: (sign * 20.0, -5.0),
            4: (sign * 20.0,  5.0),
        }
        hint = "PENALTY (theirs) — GK make the save. Everyone outside the box for rebound."
    return SetPieceInfo(mode=mode, is_ours=is_ours, instruction=hint, positions=positions)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _is_our_set_piece(mode: str, team_id: int) -> bool:
    """Infer possession from the mode string when the server embeds HOME/AWAY."""
    if team_id == 0:
        if "HOME" in mode: return True
        if "AWAY" in mode: return False
    else:
        if "AWAY" in mode: return True
        if "HOME" in mode: return False
    # No team qualifier — default to ours so agents get into attacking shape
    return True


def format_set_piece_for_prompt(info: SetPieceInfo, my_player_id: int) -> str:
    """Return a single-line string to inject into the LLM state summary."""
    pos = info.positions.get(my_player_id)
    if pos:
        return f"⚡ {info.instruction} → your target position: ({pos[0]:.1f}, {pos[1]:.1f})"
    return f"⚡ {info.instruction}"
