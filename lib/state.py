"""Game state summarization utilities for AI soccer agents.

Enriched with six tactical skill modules that inject situational context into
the LLM prompt automatically:
  - game_phase  : named tactical phase (COUNTER, DEFENDING, …) + action hint
  - threat      : per-opponent threat score so DEF/GK can prioritise
  - set_pieces  : position overrides + instruction during set pieces
  - stamina     : contextualised stamina label relative to game time
  - coordination: coach instructions (teamChat) + inferred teammate intent from positions
  - tactics     : dynamic formation home-zone per player based on score/time
"""

import math


# ---------------------------------------------------------------------------
# Format-agnostic helpers — handle both new (agentId/teamCode/possessionAgentId)
# and old (playerId/teamId/possessionPlayerId) game server formats.
# ---------------------------------------------------------------------------

def _player_idx(p: dict) -> int:
    """Numeric index (0-4) from a player dict — new agentId or old playerId."""
    if "agentId" in p:
        try:
            return int(p["agentId"].rsplit("_", 1)[-1])
        except (ValueError, IndexError):
            return 0
    return p.get("playerId", 0)


def _is_my_team(p: dict, team_id: int) -> bool:
    """True if player belongs to team_id — new teamCode or old teamId.

    teamCode is compared case-insensitively: the game server documents the
    teams as HOME/AWAY while the payload has been observed as home/away, and
    a case mismatch here is catastrophic rather than cosmetic — every player
    reads as an opponent, the agent's own player drops out of the prompt
    entirely, and the fallback degrades to SET_STANCE for the whole match.
    """
    code = p.get("teamCode")
    if isinstance(code, str):
        return code.strip().lower() == ("home" if team_id == 0 else "away")
    return p.get("teamId") == team_id


def _ball_is_free(ball: dict):
    """True/False from the server's own isFree flag, or None when absent.

    The server supplies isFree alongside possessionAgentId. Inferring
    looseness from a failed possession lookup instead makes any id we cannot
    parse look like a loose ball, which tells a player carrying the ball to
    go and fetch it.
    """
    free = ball.get("isFree")
    return free if isinstance(free, bool) else None


def _resolve_holder(ball: dict, players: list):
    """Return the player dict holding the ball, or None.

    agentId is not unique across teams — the same agentId_N appears once per
    team — so an id match alone cannot always identify the player. When the
    id is ambiguous we keep the long-standing behaviour of taking the first
    match in players[], rather than guessing: a positional tie-break on
    distance to the ball looks appealing but picks the wrong team whenever
    possession has just changed and the ball has not yet caught up.

    Ambiguity is therefore no worse than before. What changes is that the
    team is now checked against the resolved holder (see holder_is_me), so a
    player can no longer act on a ball the opposing player of the same index
    is carrying.

    TODO: drop the ambiguity entirely once the server exposes a globally
    unique player id, or sends a team discriminator alongside possession.
    """
    holder_agent = ball.get("possessionAgentId")
    if isinstance(holder_agent, str):
        matches = [p for p in players if p.get("agentId") == holder_agent]
    else:
        pid = ball.get("possessionPlayerId")
        if pid is None:
            return None
        matches = [p for p in players if p.get("playerId") == pid]
        team = ball.get("possessionTeamId")
        if team is not None:
            matches = [p for p in matches if p.get("teamId") == team]

    return matches[0] if matches else None


def _possession_idx(ball: dict):
    """Numeric possession player index from ball dict — new possessionAgentId or old possessionPlayerId.
    Returns int or None."""
    agent_id = ball.get("possessionAgentId")
    if agent_id is not None:
        try:
            return int(agent_id.rsplit("_", 1)[-1])
        except (ValueError, IndexError):
            return None
    return ball.get("possessionPlayerId")


def get_goal_positions(team_id: int) -> tuple[float, float]:
    """Return (my_goal_x, opp_goal_x) based on team."""
    if team_id == 0:
        return -55.0, 55.0
    return 55.0, -55.0


def get_possession_info(ball: dict, players: list, team_id: int) -> tuple:
    """Return (possession_id, ball_status_str, we_have_ball).

    possession_id is the holder's per-team index, which is NOT on its own
    enough to identify a player — use holder_is_me() for that rather than
    comparing it to your own id.
    """
    if _ball_is_free(ball) is True:
        return None, "free", False

    claimed = (
        isinstance(ball.get("possessionAgentId"), str)
        or ball.get("possessionPlayerId") is not None
    )
    holder = _resolve_holder(ball, players)
    if holder is None:
        # A ball with no possession claim is genuinely loose. A claim we
        # cannot resolve is reported as unknown and never as loose, so a
        # carrier is not told to go and fetch a ball it already has.
        return None, ("unknown" if claimed else "free"), False

    is_mine = _is_my_team(holder, team_id)
    idx = _player_idx(holder)
    side = "MY" if is_mine else "OPP"
    return idx, f"{side} player {idx}", is_mine


def holder_is_me(ball: dict, players: list, team_id: int, my_player_id: int) -> bool:
    """True only when this specific player holds the ball.

    Both the index and the team must match. Comparing the possession index
    alone is true for two players at once — one per team — which lets a
    player act on a ball an opponent is carrying.
    """
    holder = _resolve_holder(ball, players)
    if holder is None:
        return False
    return _player_idx(holder) == my_player_id and _is_my_team(holder, team_id)


def dist(pos1: dict, pos2: dict) -> float:
    """Euclidean distance between two position dicts with x,y keys."""
    return math.sqrt(
        (pos1.get("x", 0) - pos2.get("x", 0)) ** 2
        + (pos1.get("y", 0) - pos2.get("y", 0)) ** 2
    )


def summarize_state(
    game_state: dict,
    team_id: int,
    my_player_id: int,
    position_label: str,
) -> str:
    """Build a concise text summary of the game state for a single-player agent.

    Integrates all six tactical skills so the LLM receives:
      - A named game phase with an action hint (game_phase)
      - Contextualised stamina label (stamina)
      - Tactical formation home zone (tactics)
      - Set-piece position override when applicable (set_pieces)
      - Threat-ranked opponent list (threat)
      - Teammate coordination signals (coordination)
    """
    # ---- lazy imports keep the module importable even when skill modules are
    #      absent during isolated unit tests.
    try:
        from game_phase import detect_phase
    except ImportError:
        detect_phase = None  # type: ignore[assignment]

    try:
        from stamina import stamina_context, format_for_prompt as fmt_stamina
    except ImportError:
        stamina_context = None  # type: ignore[assignment]
        fmt_stamina = None      # type: ignore[assignment]

    try:
        from tactics import get_formation, format_formation_for_prompt
    except ImportError:
        get_formation = None               # type: ignore[assignment]
        format_formation_for_prompt = None # type: ignore[assignment]

    try:
        from set_pieces import detect_set_piece, format_set_piece_for_prompt
    except ImportError:
        detect_set_piece = None              # type: ignore[assignment]
        format_set_piece_for_prompt = None   # type: ignore[assignment]

    try:
        from threat import assess_threats, format_threats_for_prompt
    except ImportError:
        assess_threats = None              # type: ignore[assignment]
        format_threats_for_prompt = None   # type: ignore[assignment]

    try:
        from coordination import (
            read_coach_instructions,
            infer_teammate_context,
            format_coordination_for_prompt,
        )
    except ImportError:
        read_coach_instructions = None        # type: ignore[assignment]
        infer_teammate_context = None         # type: ignore[assignment]
        format_coordination_for_prompt = None # type: ignore[assignment]

    ball      = game_state.get("ball", {})
    ball_pos  = ball.get("position", {"x": 0, "y": 0})
    score     = game_state.get("score", {})
    game_time = float(game_state.get("gameTime", 0))
    play_mode = game_state.get("playMode", "OPEN_PLAY")
    players   = game_state.get("players", [])

    my_team   = sorted(
        [p for p in players if _is_my_team(p, team_id)],
        key=lambda p: _player_idx(p),
    )
    opponents = sorted(
        [p for p in players if not _is_my_team(p, team_id)],
        key=lambda p: _player_idx(p),
    )

    me = next((p for p in my_team if _player_idx(p) == my_player_id), None)
    possession_id, ball_status, _ = get_possession_info(ball, players, team_id)
    my_goal_x, opp_goal_x = get_goal_positions(team_id)

    # ---- Skill 1: Game phase -------------------------------------------------
    phase_line = ""
    phase_obj  = None
    if detect_phase:
        phase_obj  = detect_phase(game_state, team_id)
        phase_line = f"Phase: {phase_obj.phase.value} — {phase_obj.action_hint}"

    # ---- Skill 2: Tactics / formation ----------------------------------------
    formation_line = ""
    if get_formation and phase_obj:
        formation = get_formation(team_id, score, game_time, phase_obj)
        formation_line = format_formation_for_prompt(formation, my_player_id)  # type: ignore[misc]

    # ---- Skill 5: Set pieces --------------------------------------------------
    set_piece_line = ""
    if detect_set_piece:
        sp_info = detect_set_piece(game_state, team_id)
        if sp_info:
            set_piece_line = format_set_piece_for_prompt(sp_info, my_player_id)  # type: ignore[misc]

    # ---- Build header lines --------------------------------------------------
    lines = [
        f"Time: {game_time:.0f}s | Score: {score.get('home',0)}-{score.get('away',0)} | "
        f"Team: {team_id} ({'HOME' if team_id == 0 else 'AWAY'}) | PlayMode: {play_mode}",
        f"Ball: ({ball_pos.get('x',0):.1f}, {ball_pos.get('y',0):.1f}) held by {ball_status}",
        f"Your goal at x={my_goal_x:.0f} | Opponent goal at x={opp_goal_x:.0f}",
    ]

    if phase_line:
        lines.append(phase_line)
    if formation_line:
        lines.append(formation_line)
    if set_piece_line:
        lines.append(set_piece_line)

    lines.append("")

    # ---- My player info with Skill 4: Stamina context ------------------------
    if me:
        pos       = me.get("position", {})
        stam      = me.get("stamina", 1.0)
        dist_ball = dist(pos, ball_pos)
        has_ball  = holder_is_me(ball, players, team_id, my_player_id)
        extra     = (
            f" distOppGoal={abs(pos.get('x', 0) - opp_goal_x):.1f}"
            if position_label in ("MID", "FWD1", "FWD2") else ""
        )

        stam_annotation = ""
        if stamina_context and fmt_stamina:
            stam_ctx = stamina_context(stam, game_time)
            stam_annotation = " " + fmt_stamina(stam_ctx)

        # Shoot hint — injected when the player has the ball and is in range
        shoot_hint = ""
        if has_ball and position_label in ("FWD1", "FWD2", "MID"):
            dist_to_opp_goal = abs(pos.get("x", 0) - opp_goal_x)
            if dist_to_opp_goal < 35.0:
                player_y = pos.get("y", 0)
                if player_y > 3:
                    hint_aim = "TR or BR (you are above center — aim far post right)"
                elif player_y < -3:
                    hint_aim = "TL or BL (you are below center — aim far post left)"
                else:
                    hint_aim = "TL or TR (you are central — aim top corners)"
                shoot_hint = (
                    f"\n⚽ SHOOT HINT: distOppGoal={dist_to_opp_goal:.1f} — "
                    f"YOU ARE IN RANGE. SHOOT NOW. Recommended aim: {hint_aim}. Power: 0.9."
                )

        lines.append(
            f">>> YOUR PLAYER ({position_label}, id={my_player_id}): "
            f"pos=({pos.get('x',0):.1f},{pos.get('y',0):.1f}) "
            f"stam={stam:.2f}{stam_annotation} distBall={dist_ball:.1f}{extra} hasBall={has_ball}"
            f"{shoot_hint}"
        )
    lines.append("")

    # ---- Teammates -----------------------------------------------------------
    lines.append("Teammates:")
    for p in my_team:
        if _player_idx(p) == my_player_id:
            continue
        pos = p.get("position", {})
        pid = _player_idx(p)
        role  = "GK" if pid == 0 else f"P{pid}"
        extra = (
            f" distOppGoal={abs(pos.get('x', 0) - opp_goal_x):.1f}"
            if position_label == "MID" else ""
        )
        lines.append(f"  {role}(id={pid}): ({pos.get('x',0):.1f},{pos.get('y',0):.1f}){extra}")

    # ---- Skill 6: Coach instructions + inferred teammate context -----------
    if read_coach_instructions and infer_teammate_context and format_coordination_for_prompt:
        coach_msgs    = read_coach_instructions(game_state, team_id)
        teammate_ctx  = infer_teammate_context(game_state, team_id, my_player_id)
        lines.append(format_coordination_for_prompt(coach_msgs, teammate_ctx))  # type: ignore[misc]

    lines.append("")

    # ---- Skill 3: Threat-ranked opponents ------------------------------------
    opp_header = "Opponents (threat-ranked):"
    lines.append(opp_header)

    if assess_threats and format_threats_for_prompt:
        threats = assess_threats(game_state, team_id)
        lines.append(format_threats_for_prompt(threats))  # type: ignore[misc]
    else:
        # Fallback: original flat list
        for p in opponents:
            pos   = p.get("position", {})
            pid   = _player_idx(p)
            d_goal = abs(pos.get("x", 0) - my_goal_x)
            d_me   = dist(pos, me.get("position", {})) if me else 0
            lines.append(
                f"  P{pid}: ({pos.get('x',0):.1f},{pos.get('y',0):.1f}) "
                f"distToMyGoal={d_goal:.1f} distToMe={d_me:.1f}"
            )

    return "\n".join(lines)
