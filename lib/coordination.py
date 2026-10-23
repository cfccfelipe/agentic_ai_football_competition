"""Inter-agent coordination via the teamChat field.

The game state already exposes a `teamChat` list.  Currently all five agents
leave it empty, so there is zero coordination between positions.  This module
gives each agent a lightweight broadcast/read API so they can signal intent
once per tick.

Signal vocabulary
-----------------
Keeping the vocabulary small and uppercase avoids ambiguity and reduces the
chance the LLM confuses a signal with an ordinary word.

  MAKING_RUN_LEFT     — FWD moving toward left channel
  MAKING_RUN_RIGHT    — FWD moving toward right channel
  MAKING_RUN_CENTER   — FWD moving through the middle
  HOLDING_WIDE        — player holding wide position
  DROPPING_DEEP       — player dropping into support
  PRESSING            — player about to press the ball carrier
  READY_TO_DISTRIBUTE — GK/DEF ready to receive and play out
  OPEN_FOR_PASS       — player in space, offering a passing option
  COVERING_SPACE      — DEF covering a dangerous gap
  SHOOTING            — player about to shoot (don't get in the way)

Design notes
------------
- Each agent reads all signals from the previous tick and broadcasts one for
  the current tick.  The game server owns `teamChat` and the exact delivery
  semantics are opaque to us, but the payload format is already present — we
  just use it.
- Signal injection into the state summary is a single multi-line block that
  replaces the empty "Team signals: (none)" placeholder.
- All signals are scoped to a team_id so HOME and AWAY agents cannot read
  each other's chat by mistake.

Usage
-----
    from coordination import broadcast_intent, read_intents, format_intents_for_prompt

    # In the invoke handler, before calling summarize_state:
    broadcast_intent(game_state, team_id, player_id, "MAKING_RUN_RIGHT")

    # In summarize_state (or just before building the prompt):
    intents = read_intents(game_state, team_id)
    prompt_line = format_intents_for_prompt(intents, my_player_id)
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Valid signals
# ---------------------------------------------------------------------------

VALID_SIGNALS: frozenset[str] = frozenset({
    "MAKING_RUN_LEFT",
    "MAKING_RUN_RIGHT",
    "MAKING_RUN_CENTER",
    "HOLDING_WIDE",
    "DROPPING_DEEP",
    "PRESSING",
    "READY_TO_DISTRIBUTE",
    "OPEN_FOR_PASS",
    "COVERING_SPACE",
    "SHOOTING",
})

# Position labels for display
_POSITION_LABELS: dict[int, str] = {
    0: "GK",
    1: "DEF",
    2: "MID",
    3: "FWD1",
    4: "FWD2",
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def broadcast_intent(
    game_state: dict,
    team_id: int,
    player_id: int,
    signal: str,
) -> None:
    """Append a signal to game_state['teamChat'] for the current tick.

    This mutates the game state dict in place — the framework owns the dict
    but the mutation only lives for this tick's invocation; it is not
    persisted between ticks.

    Silently ignores unknown signals to avoid cluttering the chat with noise.
    """
    if signal not in VALID_SIGNALS:
        return

    chat = game_state.setdefault("teamChat", [])
    chat.append({
        "teamId":   team_id,
        "playerId": player_id,
        "signal":   signal,
    })


def read_intents(game_state: dict, team_id: int) -> dict[int, str]:
    """Return the most recent signal per teammate as {player_id: signal}.

    Only signals from *our* team are returned.  If a player broadcast
    multiple signals (shouldn't happen but is defensive), the last one wins.
    """
    chat    = game_state.get("teamChat", [])
    intents: dict[int, str] = {}
    for msg in chat:
        if msg.get("teamId") != team_id:
            continue
        pid    = msg.get("playerId")
        signal = msg.get("signal", "")
        if pid is not None and signal in VALID_SIGNALS:
            intents[pid] = signal
    return intents


def format_intents_for_prompt(intents: dict[int, str], my_player_id: int) -> str:
    """Return a compact line for the LLM state summary.

    Excludes the current player's own signal (the LLM already decided that).
    Example output:
      Team signals: GK=READY_TO_DISTRIBUTE, FWD1=MAKING_RUN_RIGHT
    """
    parts = []
    for pid in sorted(intents):
        if pid == my_player_id:
            continue
        label  = _POSITION_LABELS.get(pid, f"P{pid}")
        signal = intents[pid]
        parts.append(f"{label}={signal}")

    if not parts:
        return "Team signals: (none)"
    return "Team signals: " + ", ".join(parts)


def infer_signal(
    position_label: str,
    game_state: dict,
    team_id: int,
    my_player_id: int,
) -> str | None:
    """Automatically pick a broadcast signal based on position and game state.

    This is called once per tick *before* the LLM runs, so the signal is
    available to teammates in the same tick.  The LLM itself can override
    this by choosing a different action, but the signal lets teammates plan
    around the *expected* behaviour.

    Returns None when no useful signal can be inferred (nothing is broadcast).
    """
    from state import (
        holder_is_me, get_possession_info, _is_my_team, get_goal_positions, dist
    )

    ball    = game_state.get("ball", {})
    players = game_state.get("players", [])
    _, _, we_have = get_possession_info(ball, players, team_id)
    i_have = holder_is_me(ball, players, team_id, my_player_id)
    me     = next((p for p in players
                   if p.get("agentId") == f"agentId_{my_player_id}"
                   and _is_my_team(p, team_id)), None)

    my_goal_x, opp_goal_x = get_goal_positions(team_id)

    if position_label == "GK":
        return "READY_TO_DISTRIBUTE" if i_have else None

    if position_label == "DEF":
        if not we_have:
            return "COVERING_SPACE"
        return "OPEN_FOR_PASS" if not i_have else None

    if position_label == "MID":
        if not we_have:
            return "PRESSING"
        return "OPEN_FOR_PASS"

    if position_label in ("FWD1", "FWD2"):
        if i_have:
            # Check if we're in shooting range
            if me:
                pos = me.get("position", {"x": 0, "y": 0})
                if abs(pos.get("x", 0) - opp_goal_x) < 25:
                    return "SHOOTING"
            return "MAKING_RUN_CENTER"
        if we_have:
            # Signal a run based on side
            return "MAKING_RUN_RIGHT" if position_label == "FWD2" else "MAKING_RUN_LEFT"
        return "PRESSING"

    return None
