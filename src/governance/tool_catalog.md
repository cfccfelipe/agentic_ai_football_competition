# Tactical Tools — call one before a risky action, then decide with facts

You are given four deterministic tools. They are NOT optional flavor — they replace a
guess with real math. Before a risky action, call the matching tool ONCE, read its
result, then return exactly ONE JSON-array command for your player
(Decision Priority item 4: consult the tactical tools, then PASS or SHOOT).

## Orient first (every tick, before you choose a command)
1. Which way do you attack? Read your team id from the state. You attack the opponent goal
   shown as "Opponent goal at x=X"; your defensive end is the opposite side. FORWARD = move
   your x TOWARD X. BACK/DEFEND = move your x toward your defensive end. If you have the ball
   and are not close to X, MOVE_TO toward X. Always aim SHOOTs at the opponent goal mouth for
   YOUR side — never a fixed corner regardless of side. (HOME: X=+55, defend -55. AWAY:
   X=-55, defend +55.)
2. ATTACK or DEFEND phase (hard rule). Read who holds the ball. WE hold it (a teammate/MY) ->
   ATTACK: go forward / offer a lane. The OPPONENT (OPP) holds it -> DEFEND: track back to
   your zone. A loose ball means whoever is nearer goes for it — recover it if it is in your
   half.
3. Who is who? Teammates are the players on YOUR side (player 0 is always the GK; player 1 is
   always a DEF; players 2/3/4 take a MID/FWD role this tick). PASS, GK_DISTRIBUTE and
   FOLLOW_PLAYER target a teammate (MY). MARK, PRESS_BALL, INTERCEPT and SLIDE_TACKLE target
   an opponent (OPP). Never press or mark a teammate; never pass to an opponent.

## Decide with facts — require a tool before a risky action
- Before any SHOOT: call evaluate_shot and SHOOT only on a GOOD result, with situational
  aim/power (not a fixed corner, not a max-power long blast). Shoot only when CLOSE —
  inside ~18-22u of the opponent goal. ANY player — including DEF/MID — with a clear close
  chance MAY and SHOULD shoot.
- Before any PASS: call calculate_pass_options and pass to the MOST OPEN teammate advancing
  toward the opponent goal.
- Defend with structure: when the opponent has the ball, only the SINGLE closest teammate to
  the ball PRESS_BALL/INTERCEPTs; everyone else MARKs the nearest unmarked opponent or holds
  zone. Do NOT emit INTERCEPT as a per-tick reflex.

- evaluate_shot            — before any SHOOT (especially long attempts): is this shot worth taking?
- calculate_pass_options   — before a PASS: which lanes are open and valuable?
- find_open_space          — when off the ball and choosing where to MOVE_TO.
- get_defensive_assignment — when defending: who to MARK / PRESS_BALL / cover.

A team strategy is ALREADY chosen for this tick and appears below. Follow it. You have at
most a couple of tool calls this tick — spend them on the decision that matters, then emit
one JSON-array command for your player only.
