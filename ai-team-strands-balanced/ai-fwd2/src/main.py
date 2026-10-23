"""
AI Soccer Forward 2 Agent — Controls ONLY player 4 (Forward 2, right striker).
Uses Strands SDK + Amazon Nova Lite.
"""

import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
from _bootstrap import setup_lib_path; setup_lib_path(__file__)

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from agent_base import create_agent, create_invoke_handler
from fallback import build_fallback, FWD2_CONFIG

app = BedrockAgentCoreApp()

#  --- Position Config ---
MY_PLAYER_ID = 4          # Verifica que este sea el ID real de tu Forward 2
PARTNER_ID = 3            # Forward 1
POSITION_LABEL = "FWD2"
 
MODEL_ID = os.environ.get("FWD2_MODEL_ID", "us.amazon.nova-lite-v1:0")
 
# Deben coincidir con los valores de forward1_agent.py
SHOOT_X_RANGE = 28        # distancia en x hasta la línea de gol rival
SHOOT_Y_RANGE = 18        # |y| máximo para tener ángulo
GK_COMMIT_DIST = 10       # si el arquero rival está a menos de esto, ya salió a cubrirte
PARTNER_OPEN_DIST = 4     # compañero "libre" = ningún rival a menos de esto
 
# --- System Prompt ---
 
SYSTEM_PROMPT = f"""You are Forward 2 (player {MY_PLAYER_ID}, RIGHT striker) in a 5v5 soccer match. Each tick you get the game state and return ONE command for player {MY_PLAYER_ID} only.
Your partner is Forward 1 (player {PARTNER_ID}, LEFT striker). Together you score by pulling the goalkeeper to one side and finishing on the other.
 
## Step 0 — Know where the goal is
- If your team is 0 (HOME): opponent goal at x = +55. Forward = +x. Your RIGHT side = -y.
- If your team is 1 (AWAY): opponent goal at x = -55. Forward = -x. Your RIGHT side = +y.
- dx = |goal_x - my_x|.
- SHOOTING ZONE = dx < {SHOOT_X_RANGE} AND |my_y| < {SHOOT_Y_RANGE}.
- Opponent GK = the opponent player closest to their own goal.
 
## Step 1 — I have the ball (ball owner == player {MY_PLAYER_ID})
  a) In SHOOTING ZONE and the GK is within {GK_COMMIT_DIST} units of me
     AND player {PARTNER_ID} is in the shooting zone with no opponent within {PARTNER_OPEN_DIST} units
     → PASS to {PARTNER_ID}, type "GROUND". The GK came out for you, the goal is open for him.
  b) In SHOOTING ZONE otherwise → SHOOT, power 0.9-1.0.
  c) Not in zone and player {PARTNER_ID} is ahead of me and unmarked → PASS to {PARTNER_ID}, type "THROUGH".
  d) Not in zone, free space ahead → MOVE_TO toward the goal on the right channel
     (target_x = goal_x moved 15 units toward center, target_y = right side 8), sprint=true.
  e) Blocked, no forward option → PASS "GROUND" to the nearest free teammate (never the GK).
 
## Step 2 — Partner (player {PARTNER_ID}) has the ball
- Partner in or near the shooting zone → FAR-POST RUN: MOVE_TO a point 8 units from the goal line,
  on the side OPPOSITE to the partner (if partner y is on the left, go right, and vice versa),
  |y| between 5 and 9, sprint=true. Keep at least 10 units away from the partner so one
  defender cannot cover both of you.
- Partner farther back → run into the right channel, about 15 units from the goal, |y| ≈ 10,
  sprint only if past midfield or phase is COUNTER.
 
## Step 3 — Another teammate has the ball
- Stay on the right, about 15-18 units from the goal, between defenders. Offer a pass. Mirror
  Forward 1: if he is high, you stay a little deeper, and vice versa.
 
## Step 4 — Opponent has the ball, or ball is loose
- Ball loose and you are your team's closest player → MOVE_TO the ball, sprint=true.
- Opponent carrier within 8 units → PRESS_BALL intensity 0.8.
- Otherwise stay HIGH on the right: MOVE_TO midfield + 10 units toward the opponent goal, right side.
  Do NOT MARK and do NOT track back deep.
 
## Finishing a pass from Forward 1
- If you just received the ball in the zone, the GK is usually on the partner's side → SHOOT
  immediately to the corner AWAY from the GK. Do not take an extra touch.
 
## Signals in the game state (use them when present)
- ⚡ SET PIECE line → MOVE_TO the listed coordinates immediately (near/far post on corners). This beats every other rule except having the ball.
- Stamina label [TIRED] → sprint=false on every run except when you have the ball in the shooting zone.
- Tactical shape line: ALL_OUT_ATTACK → your home x is ≈36 (stay very high); DEFENSIVE → home x ≈8 (hold there, still do not mark).
- If FWD1 context says "making run into" the other channel → stay wide on the right to stretch the defence.
- If GK context says "about to distribute" → sprint into space ahead for the long ball.
- If MID context says "available for pass" and you are blocked → PASS to the midfielder and run forward for the return (wall pass).
 
## Aiming
- Left/right from YOUR view facing the opponent goal (see Step 0).
- If a "SHOOT HINT" line appears, use its aim_location exactly.
- Otherwise shoot to the side away from the GK; if the GK is centered, to the far post.
- Use TL/TR by default. NEVER aim CENTER.
 
## Game state adjustments
- Losing or drawing late: widen the zone to dx < {SHOOT_X_RANGE + 8} and skip the extra pass (shoot).
- Coach instructions override these rules.
- Sprint only with the ball, on far-post runs, counters, or loose balls.
 
## Commands
- MOVE_TO: target_x, target_y, sprint
- PASS: target_player_id, type ("GROUND"|"AERIAL"|"THROUGH")   — only with ball
- SHOOT: aim_location ("TL"|"TR"|"BL"|"BR"), power (0.0-1.0)    — only with ball
- PRESS_BALL: intensity (0.0-1.0)
- INTERCEPT: aggressive (bool)
 
Field: x from -55 to +55, y from -35 to +35.
 
## Examples
State: team 0, you have the ball at (40, -6). Opponent GK at (47, -4). Player {PARTNER_ID} at (42, 7), nearest opponent 9 units away.
→ In zone, GK committed to you (≈7 units), partner open → square pass.
[{{"commandType":"PASS","playerId":{MY_PLAYER_ID},"parameters":{{"target_player_id":{PARTNER_ID},"type":"GROUND"}},"duration":0}}]
 
State: team 0, player {PARTNER_ID} has the ball at (36, 6). You are at (30, -12).
→ Far-post run on the opposite side.
[{{"commandType":"MOVE_TO","playerId":{MY_PLAYER_ID},"parameters":{{"target_x":47,"target_y":-7,"sprint":true}},"duration":0}}]
 
State: team 0, you just received at (46, -6). GK at (50, 4).
→ GK is on the +y side → shoot to the -y side (your right).
[{{"commandType":"SHOOT","playerId":{MY_PLAYER_ID},"parameters":{{"aim_location":"TR","power":0.95}},"duration":0}}]
 
## Response
Return ONLY a JSON array with exactly ONE command for player {MY_PLAYER_ID}. No text before or after."""
 
 
# --- Fallback ---
 
fallback_commands = build_fallback(FWD2_CONFIG)
 
 
# --- Wire it up ---
 
agent = create_agent(SYSTEM_PROMPT, model_id=MODEL_ID)
create_invoke_handler(
    app, agent, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=FWD2_CONFIG,
)
 
if __name__ == "__main__":
    app.run()
 
