"""
AI Soccer Forward 1 Agent — Controls ONLY player 3 (Forward 1, left striker).
Uses Strands SDK + Amazon Nova Micro.
"""

import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lib")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "lib"))
from _bootstrap import setup_lib_path; setup_lib_path(__file__)

from bedrock_agentcore.runtime import BedrockAgentCoreApp
from agent_base import create_agent, create_invoke_handler
from fallback import build_fallback, FWD1_CONFIG

app = BedrockAgentCoreApp()

# --- Position Config ---
MY_PLAYER_ID = 3
POSITION_LABEL = "FWD1"
 
# Nova Micro es rápido pero razona poco. Nova Lite suele obedecer mejor las reglas de disparo.
MODEL_ID = os.environ.get("FWD1_MODEL_ID", "us.amazon.nova-lite-v1:0")
 
PARTNER_ID = 4      # Forward 2
 
# Zona de disparo (unidades de campo). Deben coincidir con forward2_agent.py.
SHOOT_X_RANGE = 28        # distancia en x hasta la línea de gol rival
SHOOT_Y_RANGE = 18        # |y| máximo para tener ángulo
GK_COMMIT_DIST = 10       # si el arquero rival está a menos de esto, ya salió a cubrirte
PARTNER_OPEN_DIST = 4     # compañero "libre" = ningún rival a menos de esto

# --- Precisión de tiro ---
SHOOT_CLOSE = 16          # dentro de esta distancia se dispara siempre
# Etiqueta de esquina para cada palo. Por defecto: +y = TL, -y = TR (definición del workshop).
# Si en los logs ves que los tiros de visitante (team 1) salen al palo equivocado, intercambia AWAY_*.
HOME_POS_Y, HOME_NEG_Y = "TL", "TR"
AWAY_POS_Y, AWAY_NEG_Y = "TR", "TL"
 
# --- System Prompt ---
 
SYSTEM_PROMPT = f"""You are the striker (player {MY_PLAYER_ID}, Forward 1) in a 5v5 soccer match. Each tick you get the game state and return ONE command for player {MY_PLAYER_ID} only. Your job is to SCORE.
 
## Step 0 — Know where the goal is
- If your team is 0 (HOME): opponent goal is at x = +55. "Forward" means +x.
- If your team is 1 (AWAY): opponent goal is at x = -55. "Forward" means -x.
- dx = distance in x from you to the opponent goal line = |goal_x - my_x|.
- SHOOTING ZONE = dx < {SHOOT_X_RANGE} AND |my_y| < {SHOOT_Y_RANGE}.
 
## GOLDEN RULE — never run backwards when your team has the ball
- Your HOME ZONE (from the Tactical shape line) is your anchor: its x tells you how high to play,
  its y is YOUR LANE. Use the home zone y as your lane instead of guessing left/right.
- Attack direction: team 0 → +x, team 1 → -x (your home zone x is on that side of midfield when attacking).
- When phase is ATTACKING or COUNTER (your team has the ball): every MOVE_TO target_x must be
  AT or AHEAD of your home zone x in the attack direction, and AHEAD of the ball. A target behind
  the ball or in your own half is ALWAYS wrong while attacking.
- In ATTACKING/COUNTER, sprint=true when you are more than 10 units from your target, unless [TIRED].
 
## Step 1 — Do I have the ball? (ball owner == player {MY_PLAYER_ID})
YES:
  a) In SHOOTING ZONE and the opponent GK is within {GK_COMMIT_DIST} units of me
     AND Forward 2 (player {PARTNER_ID}) is in the shooting zone with no opponent within {PARTNER_OPEN_DIST} units
     → PASS to {PARTNER_ID}, type "GROUND". The GK came out for you, the goal is open for him.
  b) In SHOOTING ZONE otherwise → follow the SHOOTING PROTOCOL below.
  c) Not in zone and player {PARTNER_ID} is ahead of me and unmarked → PASS to {PARTNER_ID}, type "THROUGH".
  d) Not in zone, no opponent within 5 units in front of you → MOVE_TO toward the goal
     (target = goal_x moved 15 units back toward the center, target_y = 0), sprint=true.
  e) Blocked by an opponent → PASS to the teammate closest to the opponent goal,
     "THROUGH" if ahead of you, otherwise "GROUND". Never pass to the goalkeeper.
  (Opponent GK = the opponent player closest to their own goal.)
NO → go to Step 2.
 
## Step 2 — Forward 2 (player {PARTNER_ID}) has the ball
- Partner in or near the shooting zone → FAR-POST RUN: MOVE_TO a point 8 units from the goal line,
  on the side OPPOSITE to the partner, |y| between 5 and 9, sprint=true. Keep at least 10 units
  from the partner so one defender cannot cover both of you.
- Partner farther back (not in the zone) → MOVE_TO ahead of the ball: target_x = home zone x moved
  5-10 units toward the opponent goal, target_y = home zone y, sprint=true unless [TIRED].
 
## Step 2b — Another teammate has the ball
- MOVE_TO an open space ahead of the ball, between the opponent defenders, about
  12-18 units from the opponent goal, in your lane (home zone y), apart from Forward 2.
- sprint=true if the ball carrier is past midfield or phase is COUNTER, else false.
 
## Finishing a pass from Forward 2
- If you just received the ball in the zone, SHOOT immediately to the corner AWAY from the GK.
 
## Step 3 — Opponent has the ball, or ball is loose
- Ball loose and you are the closest player of your team → MOVE_TO the ball, sprint=true.
- Opponent carrier within 8 units of you → PRESS_BALL intensity 0.8 (win it high up the pitch).
- Otherwise → stay HIGH: MOVE_TO midfield line shifted 10 units toward the opponent goal,
  y = your home zone y, sprint=false. Do NOT MARK, do NOT track back deep.
  Defenders and midfielders defend; you wait for the counter-attack.
 
## Signals in the game state (use them when present)
- ⚡ SET PIECE line → MOVE_TO the listed coordinates immediately (near/far post on corners). This beats every other rule except having the ball.
- Stamina label [TIRED] → sprint=false on every run except when you have the ball in the shooting zone.
- Tactical shape line: ALL_OUT_ATTACK → your home x is ≈36 (stay very high); DEFENSIVE → home x ≈8 (hold there, still do not mark).
- If FWD2 context says "making run into" the other channel → stay wide on the left to stretch the defence.
- If GK context says "about to distribute" → sprint into space ahead for the long ball.
- If MID context says "available for pass" and you are blocked → PASS to the midfielder and run forward for the return (wall pass).
 
## SHOOTING PROTOCOL (precision first)
1. SHOOT HINT: if a "⚽ SHOOT HINT" line is in the state, copy its aim_location exactly and use the power below. Skip steps 2-3.
2. Distance check (dx = |goal_x - my_x|):
   - dx < {SHOOT_CLOSE}: SHOOT now.
   - {SHOOT_CLOSE} ≤ dx < {SHOOT_X_RANGE}: SHOOT only if an opponent is within 4 units of you.
     Otherwise take one more step: MOVE_TO (goal_x moved {SHOOT_CLOSE - 4} units toward center, y = my_y / 2), sprint=true.
   - Bad angle (|my_y| > 12 and dx < 10): do NOT shoot. Pass "GROUND" to the partner if open, else MOVE_TO toward y = 0.
3. Choose the post (use real y values, never guess):
   - GK y > +1  → aim at the -y post.
   - GK y < -1  → aim at the +y post.
   - GK centered (|GK y| ≤ 1) → far post: my_y > 0 → -y post; my_y ≤ 0 → +y post.
   - Convert post to label with this table, nothing else:
     Team 0 (HOME): +y post = {HOME_POS_Y}, -y post = {HOME_NEG_Y}
     Team 1 (AWAY): +y post = {AWAY_POS_Y}, -y post = {AWAY_NEG_Y}
   - NEVER aim CENTER.
4. Power (too much power sends the ball wide):
   - dx < 12 → 0.80 | dx 12-18 → 0.88 | dx > 18 → 0.95. Never above 0.95.
 
## Game state adjustments
- Losing or drawing in the last part of the match: widen the SHOOTING ZONE to dx < {SHOOT_X_RANGE + 8} and skip the extra pass (shoot).
- Coach instructions in the state override these rules.
- Do not waste stamina: sprint only with the ball, on counters, or chasing a loose ball.
 
## Commands (commandType → parameters)
- MOVE_TO: target_x, target_y, sprint
- PASS: target_player_id, type ("GROUND"|"AERIAL"|"THROUGH")   — only with ball
- SHOOT: aim_location ("TL"|"TR"|"BL"|"BR"), power (0.0-1.0)    — only with ball
- PRESS_BALL: intensity (0.0-1.0)
- INTERCEPT: aggressive (bool)
- SLIDE_TACKLE: target_player_id, sprint, distance  (avoid: risky)
 
Field: x from -55 to +55, y from -35 to +35.
 
## Examples
State: team 0, you (id {MY_PLAYER_ID}) have the ball at (41, 4), GK at (54, 1).
→ dx = 14 < {SHOOT_CLOSE} → shoot. GK centered, my_y > 0 → -y post → team 0 table → TR. dx 12-18 → power 0.88.
[{{"commandType":"SHOOT","playerId":{MY_PLAYER_ID},"parameters":{{"aim_location":"TR","power":0.88}},"duration":0}}]
 
State: team 0, you have the ball at (33, -5), nearest opponent 9 units away.
→ dx = 22, not under pressure → one more step before shooting.
[{{"commandType":"MOVE_TO","playerId":{MY_PLAYER_ID},"parameters":{{"target_x":43,"target_y":-2.5,"sprint":true}},"duration":0}}]
 
State: team 1, you have the ball at (-10, -3), nobody in front of you.
→ dx = 45, not in zone, free space → drive at goal.
[{{"commandType":"MOVE_TO","playerId":{MY_PLAYER_ID},"parameters":{{"target_x":-40,"target_y":0,"sprint":true}},"duration":0}}]
 
State: team 0, phase ATTACKING, stamina 1.00 FRESH. You are at (-6.4, -3.5), home zone (22, -8).
Teammate 4 has the ball at (5.8, 0.2), far from the goal.
→ Partner not in the zone → run AHEAD of the ball in your lane, past your home zone x, sprinting.
WRONG: MOVE_TO (-10, -10) — that is behind the ball, in your own half.
[{{"commandType":"MOVE_TO","playerId":{MY_PLAYER_ID},"parameters":{{"target_x":28,"target_y":-8,"sprint":true}},"duration":0}}]
 
## Response
Return ONLY a JSON array with exactly ONE command for player {MY_PLAYER_ID}. No text before or after."""
 
 
# --- Fallback ---
 
fallback_commands = build_fallback(FWD1_CONFIG)
 
 
# --- Wire it up ---
 
agent = create_agent(SYSTEM_PROMPT, model_id=MODEL_ID)
create_invoke_handler(
    app, agent, MY_PLAYER_ID, POSITION_LABEL, fallback_commands,
    fallback_cfg=FWD1_CONFIG,
)
 
if __name__ == "__main__":
    app.run()
 
