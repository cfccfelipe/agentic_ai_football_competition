"""Fallback command factory for AI soccer position agents.

Each position defines a FallbackConfig, and build_fallback() returns a
fallback_commands(game_state, team_id, my_player_id) function.

Tactical skill integrations
---------------------------
- threat.py     : DEF/GK fallback marks the highest-threat opponent rather
                  than simply the one closest to the goal.
- set_pieces.py : All positions override their MOVE_TO target during set
                  pieces so rule-based players sprint to the right spot.
- tactics.py    : Default MOVE_TO positions use the formation home zone
                  instead of hardcoded x_factor values.
- stamina.py    : Pressing intensity and sprint decisions are scaled by the
                  player's current stamina relative to game time.
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Callable

from state import (
    get_goal_positions,
    get_possession_info,
    holder_is_me,
    dist,
    _player_idx,
    _is_my_team,
    _possession_idx,
)


@dataclass
class FallbackConfig:
    """Per-position fallback behaviour."""

    # What to do when we have the ball
    possession_action: str = "PASS"
    """One of: GK_DISTRIBUTE, PASS, SHOOT_OR_PASS, SHOOT_OR_ADVANCE."""

    # Default position when nothing else applies
    default_x_factor: float = 0.0
    """Multiplied by my_goal_x or opp_goal_x (see default_x_ref)."""
    default_x_ref: str = "my_goal"
    """'my_goal' or 'opp_goal' — which goal x to multiply."""
    default_y: float | str = 0
    """Fixed y, or 'track_ball' to follow ball y * 0.5 (clamped ±10)."""

    # Pressing
    press_distance: float = 20.0
    press_intensity: float = 0.7
    press_duration: int = 3

    # Shoot threshold (distance to opp goal)
    shoot_threshold: float = 25.0
    shoot_aim: str = "TR"
    shoot_power: float = 0.9

    # Advance with ball (for forwards)
    advance_x_factor: float = 0.6
    advance_y: float = 0.0
    advance_sprint: bool = True

    # Run into space when teammate has ball
    support_x_factor: float = 0.5
    support_y: float = 0.0
    support_sprint: bool = True

    # DEF-specific: mark opponents near our goal
    mark_threshold: float = 0.0
    """If > 0, mark the opponent closest to our goal when within this distance."""
    mark_tightness: str = "TIGHT"

    # Pass target filter (player IDs to exclude from pass targets)
    pass_exclude_ids: list[int] = field(default_factory=list)

    # Default stance when player not found
    default_stance: int = 0

    # Last-resort command — used when BOTH the LLM and fallback function crash.
    # Only commandType, playerId, parameters, and duration are used.
    last_resort_command_type: str = "SET_STANCE"
    last_resort_params: dict = field(default_factory=lambda: {"stance": 0})
    last_resort_duration: int = 0


# ---------------------------------------------------------------------------
# Pre-built configs for each position
# ---------------------------------------------------------------------------

GK_CONFIG = FallbackConfig(
    possession_action="GK_DISTRIBUTE",
    default_x_factor=0.9, default_x_ref="my_goal", default_y="track_ball",
    default_stance=2,
    last_resort_command_type="SET_STANCE", last_resort_params={"stance": 2},
)

DEF_CONFIG = FallbackConfig(
    possession_action="PASS",
    pass_exclude_ids=[0],  # don't pass back to GK
    default_x_factor=0.6, default_x_ref="my_goal", default_y=0,
    mark_threshold=30.0, mark_tightness="TIGHT",
    default_stance=2,
    last_resort_command_type="SET_STANCE", last_resort_params={"stance": 2},
)

MID_CONFIG = FallbackConfig(
    possession_action="SHOOT_OR_PASS",
    default_x_factor=0.5, default_x_ref="ball_x", default_y="track_ball_30",
    press_distance=20.0, press_intensity=0.6,
    shoot_threshold=25.0, shoot_aim="TR", shoot_power=0.8,
    default_stance=0,
    last_resort_command_type="PRESS_BALL", last_resort_params={"intensity": 0.5},
    last_resort_duration=3,
)

FWD1_CONFIG = FallbackConfig(
    possession_action="SHOOT_OR_ADVANCE",
    advance_x_factor=0.75, advance_y=-8, advance_sprint=True,   # push deeper before advancing
    support_x_factor=0.65, support_y=-10, support_sprint=True,  # run into the box, not midfield
    default_x_factor=0.55, default_x_ref="opp_goal", default_y=-8,  # default pos higher up
    press_distance=18.0, press_intensity=0.7,
    shoot_threshold=30.0,   # shoot from further out
    shoot_aim="TR", shoot_power=0.9,
    default_stance=1,
    last_resort_command_type="PRESS_BALL", last_resort_params={"intensity": 0.6},
    last_resort_duration=3,
)

FWD2_CONFIG = FallbackConfig(
    possession_action="SHOOT_OR_ADVANCE",
    advance_x_factor=0.75, advance_y=8, advance_sprint=True,    # push deeper before advancing
    support_x_factor=0.65, support_y=10, support_sprint=True,   # run into the box, not midfield
    default_x_factor=0.55, default_x_ref="opp_goal", default_y=8,   # default pos higher up
    press_distance=18.0, press_intensity=0.7,
    shoot_threshold=30.0,   # shoot from further out
    shoot_aim="BL", shoot_power=0.9,
    default_stance=1,
    last_resort_command_type="PRESS_BALL", last_resort_params={"intensity": 0.6},
    last_resort_duration=3,
)


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

def build_last_resort(cfg: FallbackConfig, player_id: int) -> dict:
    """Build the last-resort command dict from a FallbackConfig.

    This command is only used when BOTH the LLM and the fallback function crash.
    """
    return {
        "commandType": cfg.last_resort_command_type,
        "playerId": player_id,
        "parameters": dict(cfg.last_resort_params),
        "duration": cfg.last_resort_duration,
    }


def build_fallback(cfg: FallbackConfig) -> Callable[[dict, int, int], list[dict]]:
    """Return a fallback_commands(game_state, team_id, my_player_id) function."""

    def fallback_commands(game_state: dict, team_id: int, my_player_id: int) -> list[dict]:
        ball      = game_state.get("ball", {})
        ball_pos  = ball.get("position", {"x": 0, "y": 0})
        players   = game_state.get("players", [])
        game_time = float(game_state.get("gameTime", 0))
        score     = game_state.get("score", {})
        my_goal_x, opp_goal_x = get_goal_positions(team_id)

        me = next(
            (p for p in players if _player_idx(p) == my_player_id and _is_my_team(p, team_id)),
            None,
        )
        if not me:
            return [_cmd("SET_STANCE", my_player_id, team_id, {"stance": cfg.default_stance})]

        pos   = me.get("position", {"x": 0, "y": 0})
        stam  = me.get("stamina", 1.0)

        # ---- Skill 4: stamina-aware press intensity + sprint ----------------
        effective_press_intensity = cfg.press_intensity
        effective_sprint          = True
        try:
            from stamina import stamina_context
            stam_ctx = stamina_context(stam, game_time)
            effective_press_intensity = stam_ctx.press_intensity
            effective_sprint          = stam_ctx.sprint_ok
        except ImportError:
            pass

        # ---- Skill 5: set-piece position override ---------------------------
        try:
            from set_pieces import detect_set_piece
            sp_info = detect_set_piece(game_state, team_id)
            if sp_info:
                sp_pos = sp_info.positions.get(my_player_id)
                if sp_pos:
                    # Only MOVE_TO the set-piece position if we don't have the ball
                    if not holder_is_me(ball, players, team_id, my_player_id):
                        tx, ty = sp_pos
                        return [_cmd("MOVE_TO", my_player_id, team_id,
                                     {"target_x": tx, "target_y": ty,
                                      "sprint": effective_sprint})]
        except ImportError:
            pass

        # --- We have the ball ---
        if holder_is_me(ball, players, team_id, my_player_id):
            return _on_ball(cfg, game_state, players, team_id, my_player_id,
                            pos, my_goal_x, opp_goal_x)

        # ---- Skill 3: threat-aware marking for DEF/GK -----------------------
        if cfg.mark_threshold > 0:
            try:
                from threat import assess_threats
                threats = assess_threats(game_state, team_id)
                if threats:
                    top = threats[0]
                    if (not top.is_marked
                            and top.distance_to_goal < cfg.mark_threshold
                            and top.score >= 0.4):
                        return [_cmd("MARK", my_player_id, team_id,
                                     {"target_player_id": top.player_id,
                                      "tightness": cfg.mark_tightness}, duration=3)]
            except ImportError:
                # Fallback to original distance-only logic
                opponents = [p for p in players if not _is_my_team(p, team_id)]
                if opponents:
                    dangerous = min(opponents,
                                    key=lambda p: abs(p.get("position", {}).get("x", 0) - my_goal_x))
                    if abs(dangerous.get("position", {}).get("x", 0) - my_goal_x) < cfg.mark_threshold:
                        return [_cmd("MARK", my_player_id, team_id,
                                     {"target_player_id": _player_idx(dangerous),
                                      "tightness": cfg.mark_tightness}, duration=3)]

        # --- Teammate has ball → support run (forwards) ---
        if cfg.possession_action in ("SHOOT_OR_ADVANCE",):
            _, _, we_have_ball = get_possession_info(ball, players, team_id)
            if we_have_ball:
                return [_cmd("MOVE_TO", my_player_id, team_id,
                             {"target_x": opp_goal_x * cfg.support_x_factor,
                              "target_y": cfg.support_y, "sprint": effective_sprint})]

        # --- Press if close to ball and opponent has it ---
        _, _, we_have_ball = get_possession_info(ball, players, team_id)
        if not we_have_ball and dist(pos, ball_pos) < cfg.press_distance:
            return [_cmd("PRESS_BALL", my_player_id, team_id,
                         {"intensity": effective_press_intensity},
                         duration=cfg.press_duration)]

        # ---- Skill 2: tactics-aware default position ------------------------
        tx, ty = _tactical_default_pos(
            cfg, my_goal_x, opp_goal_x, ball_pos,
            my_player_id, team_id, score, game_time,
        )
        return [_cmd("MOVE_TO", my_player_id, team_id,
                     {"target_x": tx, "target_y": ty, "sprint": False})]

    return fallback_commands


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _cmd(cmd_type: str, pid: int, tid: int, params: dict, duration: int = 0) -> dict:
    return {"commandType": cmd_type, "playerId": pid, "teamId": tid,
            "parameters": params, "duration": duration}


# Aim location cycling — vary aim so the GK can't read the pattern.
# Each tuple is (top_option, bottom_option) chosen by player y-position.
_AIM_CYCLE = [("TL", "BL"), ("TR", "BR"), ("TL", "BR"), ("TR", "BL")]
_aim_counter: dict[int, int] = {}   # player_id → cycle index


def _pick_aim(player_id: int, player_y: float) -> str:
    """Choose an aim corner based on player position and a rotation counter.

    - Players to the left of goal (y < -3) aim at the far post → right corners.
    - Players to the right of goal (y > 3) aim at the far post → left corners.
    - Central players rotate through all four corners.
    The cycle prevents the GK from reading a fixed pattern.
    """
    idx = _aim_counter.get(player_id, 0)
    _aim_counter[player_id] = (idx + 1) % len(_AIM_CYCLE)
    top, bottom = _AIM_CYCLE[idx]

    # Prefer top corners (harder for GK to reach) unless player is below goal center
    if player_y < -3:
        # Left of goal → favor right side (far post)
        return "TR" if idx % 2 == 0 else "BR"
    elif player_y > 3:
        # Right of goal → favor left side (far post)
        return "TL" if idx % 2 == 0 else "BL"
    else:
        # Central → pure rotation, prefer top
        return top


def _on_ball(cfg, game_state, players, team_id, my_player_id, pos, my_goal_x, opp_goal_x):
    """Handle possession for all position types."""
    if cfg.possession_action == "GK_DISTRIBUTE":
        teammates = [p for p in players if _is_my_team(p, team_id) and _player_idx(p) != my_player_id]
        opponents = [p for p in players if not _is_my_team(p, team_id)]

        def _nearest_opp_dist(player):
            """Distance from a teammate to the nearest opponent."""
            p_pos = player.get("position", {})
            if not opponents:
                return 999.0
            return min(dist(p_pos, o.get("position", {})) for o in opponents)

        if teammates:
            # Try forwards first — only kick if they have a clear lane (nearest
            # opponent is further than 8 units away so we don't gift possession).
            forwards = [p for p in teammates if _player_idx(p) in (3, 4)]
            free_forwards = [p for p in forwards if _nearest_opp_dist(p) > 8.0]
            if free_forwards:
                # Pick the forward closest to the opponent goal
                target = min(free_forwards, key=lambda p: abs(p.get("position", {}).get("x", 0) - opp_goal_x))
                return [_cmd("GK_DISTRIBUTE", my_player_id, team_id,
                             {"target_player_id": _player_idx(target), "method": "KICK"})]

            # No free forward — throw to the safest (most space) nearby teammate
            safest = max(teammates, key=_nearest_opp_dist)
            method = "THROW" if dist(safest.get("position", {}), pos) < 20.0 else "KICK"
            return [_cmd("GK_DISTRIBUTE", my_player_id, team_id,
                         {"target_player_id": _player_idx(safest), "method": method})]

        return [_cmd("GK_DISTRIBUTE", my_player_id, team_id,
                     {"target_player_id": 3, "method": "KICK"})]

    if cfg.possession_action == "PASS":
        exclude = set(cfg.pass_exclude_ids) | {my_player_id}
        teammates = [p for p in players if _is_my_team(p, team_id) and _player_idx(p) not in exclude]
        if teammates:
            target = min(teammates, key=lambda p: dist(p.get("position", {}), pos))
            return [_cmd("PASS", my_player_id, team_id,
                         {"target_player_id": _player_idx(target), "type": "GROUND"})]
        return [_cmd("PASS", my_player_id, team_id,
                     {"target_player_id": 2, "type": "GROUND"})]

    if cfg.possession_action == "SHOOT_OR_PASS":
        if abs(pos.get("x", 0) - opp_goal_x) < cfg.shoot_threshold:
            aim = _pick_aim(my_player_id, pos.get("y", 0))
            return [_cmd("SHOOT", my_player_id, team_id,
                         {"aim_location": aim, "power": cfg.shoot_power})]
        forwards = [p for p in players if _is_my_team(p, team_id) and _player_idx(p) in (3, 4)]
        if forwards:
            target = min(forwards, key=lambda p: abs(p.get("position", {}).get("x", 0) - opp_goal_x))
            return [_cmd("PASS", my_player_id, team_id,
                         {"target_player_id": _player_idx(target), "type": "GROUND"})]
        return [_cmd("PASS", my_player_id, team_id,
                     {"target_player_id": 3, "type": "GROUND"})]

    if cfg.possession_action == "SHOOT_OR_ADVANCE":
        if abs(pos.get("x", 0) - opp_goal_x) < cfg.shoot_threshold:
            aim = _pick_aim(my_player_id, pos.get("y", 0))
            return [_cmd("SHOOT", my_player_id, team_id,
                         {"aim_location": aim, "power": cfg.shoot_power})]
        return [_cmd("MOVE_TO", my_player_id, team_id,
                     {"target_x": opp_goal_x * cfg.advance_x_factor,
                      "target_y": cfg.advance_y, "sprint": cfg.advance_sprint})]

    # Shouldn't reach here
    return [_cmd("SET_STANCE", my_player_id, team_id, {"stance": 0})]


def _default_pos(cfg, my_goal_x, opp_goal_x, ball_pos):
    """Calculate default x,y from config (original hardcoded logic)."""
    if cfg.default_x_ref == "my_goal":
        tx = my_goal_x * cfg.default_x_factor
    elif cfg.default_x_ref == "opp_goal":
        tx = opp_goal_x * cfg.default_x_factor
    elif cfg.default_x_ref == "ball_x":
        tx = ball_pos.get("x", 0) * cfg.default_x_factor
    else:
        tx = 0

    if cfg.default_y == "track_ball":
        ty = max(-10, min(10, ball_pos.get("y", 0) * 0.5))
    elif cfg.default_y == "track_ball_30":
        ty = ball_pos.get("y", 0) * 0.3
    else:
        ty = cfg.default_y

    return tx, ty


def _tactical_default_pos(
    cfg,
    my_goal_x: float,
    opp_goal_x: float,
    ball_pos: dict,
    my_player_id: int,
    team_id: int,
    score: dict,
    game_time: float,
) -> tuple[float, float]:
    """Skill 2: Use tactics.py formation home zone when available, else fall back."""
    try:
        from game_phase import detect_phase, GamePhase
        from tactics import get_formation, get_player_home

        # Build a minimal game_state dict for phase detection
        _gs = {"score": score, "gameTime": game_time, "playMode": "OPEN_PLAY", "ball": {}, "players": []}
        phase = detect_phase(_gs, team_id)
        formation = get_formation(team_id, score, game_time, phase)
        home = get_player_home(formation, my_player_id)
        if home:
            return home
    except (ImportError, Exception):
        pass

    # Original logic as fallback
    return _default_pos(cfg, my_goal_x, opp_goal_x, ball_pos)
