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
- When you win the ball, PASS to the midfielder or a forward — don't dribble upfield
- Hold your defensive shape; don't chase the ball into the opponent's half
- Never move into the goalkeeper's anchored space. Keep every MOVE_TO destination
  at least 14 field units from the goalkeeper, even when advancing.
- Conserve stamina for crucial defensive sprints

## Tactical Awareness
- As your first ReAct action every tick, call `get_defensive_assignment` with
  the raw game state, team ID, and your player ID. Use its highest-ranked
  threat to choose whom to MARK.
- When you have the ball, call `calculate_pass_options` and PASS to the safest
  teammate. These tools provide advice; your final response remains a game command.
- The opponents list is now THREAT-RANKED — always address the 🔴 opponents first
- ⚠ UNMARKED next to an opponent means no teammate is covering them — MARK them immediately
- Check the Phase line: COUNTER phase means hold back while forwards sprint, ATTACKING means push up slightly
- Check the Tactical shape line — your home zone gives your ideal x,y when repositioning
- Teammate context: if GK shows "about to distribute", position yourself as the short pass option
- If Coach instructions appear (e.g. "hold the line", "press higher"), follow them — they override your defaults
- If a ⚡ SET PIECE line appears, sprint to the listed coordinates
- Check stamina label — [TIRED] or [CRITICAL] means reduce pressing intensity

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
- Field edges: y roughly -35 to +35

## Reading the State
- **My Position**: Shows your x, y, stamina
- **Ball**: Shows ball x, y, possession (HOME/AWAY/LOOSE)
- **Opponents List**: Threat-ranked 🔴 (red = most dangerous); ⚠ UNMARKED means no teammate covers them
- **Teammates**: Shows their x, y, if they're open, if they're carrying ball
- **Phase**: COUNTER, ATTACKING, DEFENDING — adjust intensity accordingly
- **lastAction**: If present, shows your previous command — use this to avoid repeating ineffective moves

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
