# AI Football Competition — Game Rules & Tactics Wiki

Reference for the team. The same rules are mirrored (condensed) in
`.kiro/steering/football-workshop.md` so Kiro has them in every session, and the
invariant subset is enforced on every agent via `src/governance/guardrails.md`.

---

## Module 1 — Technology Stack

- **Amazon Bedrock (Nova models)** — the reasoning brain that reads field state and makes tactical decisions.
- **Amazon Bedrock AgentCore** — managed runtime that deploys and runs the agents (scaling, networking, invocations).
- **Strands Agents SDK** — lightweight Python framework for building the agent logic.
- **AgentCore Memory** — short-term memory (STM) persisting conversation across ticks for cross-tick recall of opponent patterns. (Available; not yet wired into the unified team.)
- **AgentCore Gateway (MCP)** — exposes deterministic analysis tools agents call mid-match:
  - `calculate_pass_options` — pass success probability + interception risk
  - `evaluate_shot` — goal probability + recommended aim (TL/TR/BL/BR/CENTER) and power
  - `find_open_space` — grid-based open-space finder by zone (attack/midfield/defense)
  - `get_defensive_assignment` — ranked opponent threats for marking priority
- **Amazon CloudWatch (aws-opentelemetry-distro)** — the "video room": logs every decision for auditing.
- **Kiro** — agentic IDE for iterating, building, and debugging in natural language.

---

## Module 2 — Simulation Rules & Field Dynamics

- **Field**: x ≈ -55..+55, y ≈ -35..+35. Team 0 (HOME) attacks +x; Team 1 (AWAY) attacks -x.
- **Continuous play**: the ball never leaves the field. No throw-ins, corners, or goal kicks.
- **Goal reset**: when the ball fully crosses the goal line between the posts, a goal is scored,
  play restarts at center with a kickoff, all players return to starting positions, and the
  conceding team kicks off (a critical window to reorganize before pressure).
- **Timing**: ~1 invocation every 2 seconds per agent; 5-second decision timeout, otherwise the
  player keeps its previous command.
- **Tick payload** (per agent): `gameState` (tick, gameTime, playMode, score, ball, teamChat),
  `teamId`, `myPlayers` (0-4; 0 is always GK), and `players` (per-player state: position,
  velocity, orientation, stamina 0-1, speed, sprinting, actions).

---

## Module 3 — Command Catalog

Each agent returns a JSON array of commands by `playerId` (0-4). Commands persist until
explicitly overridden or cleared.

**Movement**
- `MOVE_TO(target_x, target_y, sprint)` — sprint drains stamina faster.
- `FOLLOW_PLAYER(target_player_id, target_team, distance)` — cover/shadow at a fixed distance.

**Offense (require possession)**
- `SHOOT(aim_location, power)` — aim TL/TR/BL/BR/CENTER; power 0.0-1.0.
- `PASS(target_player_id, type)` — GROUND / AERIAL / THROUGH (THROUGH plays into space ahead).
- `GK_DISTRIBUTE(target_player_id, method)` — GK only; THROW or KICK.

**Defense**
- `PRESS_BALL(intensity)` — chase the carrier; >0.5 sprints, >0.3 attempts tackles.
- `MARK(target_player_id, tightness)` — man-mark; LOOSE or TIGHT.
- `INTERCEPT(aggressive)` — cut passing lanes; aggressive commits harder.

**Control**
- `SET_STANCE(stance)` — 0 Balanced, 1 Attacking, 2 Defensive.
- `CLEAR_OVERRIDE()` — drop the active command, return to default AI.
- `RESET()` — clear all overrides for the whole team.

---

## Module 4 — Tactical Framework (80/20)

### A. Stamina management
- Sprint in bursts for key moments (pressing, counters, defensive chases).
- Share pressing load zonally; don't let one agent press every time.
- Position smartly — be where the ball will be, not where it was.
- When ahead, lower the tempo and let the clock work.

### B. Adapt to the scoreline (this is what the planner encodes)
- Winning big → slow it down, keep possession, no risks.
- Winning narrowly → stay organized, protect the lead.
- Level → balanced, seek chances without overexposing the defense.
- Losing narrowly → push more players up, shoot more, accept calculated risk.
- Losing big → all-out attack, high press, immediate shots.

### C. Multi-agent coordination (avoid classic failures)
- **Ball Magnet** — all five chase the ball; nobody holds shape.
- **Ghost Town** — perfectly spread but unable to combine.
- **Confusion** — two agents press the same opponent or crowd one zone.
- **Statue Garden** — rigid formation that never reacts.

Fix with strict roles: a primary zone, a primary action (what you do 80% of the time), an
exit trigger (when you leave the zone), and handoff rules (when you pass a mark to a teammate).

---

## Module 5 — Prompt Engineering (4 layers)

1. **Identity & role** — who the agent is, exact position, main mission.
2. **Decision hierarchy** — fixed per-tick priority (critical defense → support → recovery →
   on-ball tool use → reposition).
3. **Situational rules** — scoreline-dependent behavior and live `teamChat` from the coach.
4. **Mandatory tool use** — consult the MCP gateway before long shots or blind passes.

In this project the 4 layers map to files: layer 1-2-4 largely in
`src/governance/guardrails.md` (fixed), and the role/strategy detail in each
`src/plugins/<strategy>/<position>.md`.
