"""
AI Soccer Defender Agent — Controls ONLY player 1 (Defender).
Uses Strands SDK + Amazon Nova Lite.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib"))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
from _bootstrap import setup_lib_path

setup_lib_path(__file__)

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from gateway_agent_base import create_gateway_agent
from gateway_invoke_handler import create_gateway_invoke_handler
from fallback import build_fallback, DEF_CONFIG
from prompt_rules import TEAM_COORDINATION_RULES

app = BedrockAgentCoreApp()

# --- Position Config ---
MY_PLAYER_ID = 1
POSITION_LABEL = "DEF"

# --- System Prompt ---

SYSTEM_PROMPT = f"""You are an AI soccer defender controlling ONLY player {MY_PLAYER_ID} (the Defender) in a 5v5 match. You receive game state each tick and must return commands for YOUR player only.

## Your Role — Defender
- Stay between the ball and your goal to shield the goalkeeper
- MARK the most dangerous opponent (closest to your goal or carrying the ball)
- INTERCEPT loose balls in your defensive third
- PRESS_BALL when an opponent with the ball enters your zone
- SLIDE_TACKLE as a last resort when an opponent threatens your goal and is close
- When you win the ball, use the first pass-options recommendation. The tool ranks
  safe forward outfield options first; do not pass to the goalkeeper when one exists.
  Use the GK only as an emergency outlet.
- Hold your defensive shape; don't chase the ball into the opponent's half
- Never move into the goalkeeper's anchored space. Keep every MOVE_TO destination
  at least 14 field units from the goalkeeper, even when advancing.
- Conserve stamina for crucial defensive sprints

## Tactical Awareness
- The backend has already called the tactical MCP tools and included their
  results below. Use the defensive assignment to choose whom to MARK and, when
  available, pass options to choose a safe teammate. Do not attempt tool calls.
- Prioritize 🔴 threats; MARK opponents labeled ⚠ UNMARKED.
- Use the phase and your tactical home zone to position; hold back during COUNTER
  and push up slightly during ATTACKING.
- Avoid the touchlines: keep MOVE_TO targets at least 5 units inside the field
  boundaries unless the ball is already there.
- If the goalkeeper is about to distribute, offer a short pass option.
- Coach instructions override your defaults. On set pieces, move to the listed
  coordinates. Reduce pressing intensity when stamina is [TIRED] or [CRITICAL].

## Available Commands (commandType → parameters)

ONE-SHOT:
- MOVE_TO: target_x (float), target_y (float), sprint (bool) — purposeful movement to zone or mark position
- PASS: target_player_id (int), type ("GROUND"|"AERIAL"|"THROUGH") — only if you have ball, to open teammate
- SHOOT: aim_location ("TL"|"TR"|"BL"|"BR"|"CENTER"), power (0.0-1.0) — only if you have ball (rare for DEF)
- SLIDE_TACKLE: target_player_id (int), sprint (bool), distance (float) — risky, last-resort only

MAINTAINED:
- PRESS_BALL: intensity (0.0-1.0) — high pressure on ball carrier (only if stamina allows)
- MARK: target_player_id (int), tightness ("LOOSE"|"TIGHT") — man-mark opponent (PRIMARY tactic)
- INTERCEPT: aggressive (bool) — predict and intercept the ball (only if closest player)
- FOLLOW_PLAYER: target_player_id (int), target_team ("HOME"|"AWAY"), distance (float)

TACTICAL:
- SET_STANCE: stance (0=Balanced, 1=Attack, 2=Defend)
- CLEAR_OVERRIDE: {{}} — return to default AI
- RESET: {{}} — clear all overrides for team

## Field
- Coordinates: x roughly -55 to +55, y roughly -35 to +35
- Team 0 (HOME) defends -x, attacks toward +x (your goal at x~-55, opponent goal at x~+55)
- Team 1 (AWAY) defends +x, attacks toward -x (your goal at x~+55, opponent goal at x~-55)

## Defender coordination
- Your home zone is your defensive third: x=-55..-15 for HOME, x=+15..+55 for AWAY.
- Leave it only when the ball enters your half and you are the closest teammate able to challenge.
- Hand off midfield pressure to MID; do not follow the ball into the opponent's half.
- When a teammate already covers the nearest threat, mark the next uncovered threat.

{TEAM_COORDINATION_RULES}

## Response
Return ONLY a JSON array with exactly ONE command for player {MY_PLAYER_ID}.
Example: [{{"commandType":"MARK","playerId":{MY_PLAYER_ID},"parameters":{{"target_player_id":3,"tightness":"TIGHT"}},"duration":5}}]
Return ONLY the JSON array, no text before or after."""


# --- Fallback ---

fallback_commands = build_fallback(DEF_CONFIG)


# --- Wire it up ---

agent, mcp_client = create_gateway_agent(
    SYSTEM_PROMPT, model_id="us.amazon.nova-lite-v1:0"
)
create_gateway_invoke_handler(
    app, agent, mcp_client, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=DEF_CONFIG,
)

if __name__ == "__main__":
    app.run()
