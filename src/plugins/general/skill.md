---
name: general
type: scripts
auto_load: true
description: >
  Deterministic tactical analysis tools available to every agent regardless of
  strategy. Use these to replace guessing with math before acting on the ball.
---

# General Tactical Scripts

These tools are exposed over MCP and are available to all agents at all times.
Call them before committing to a pass, a shot, or a defensive assignment.

## Scripts

- **calculate_pass_options** — CALL BEFORE passing. Returns success probability and
  interception risk per teammate. Pass to the highest `success_probability` target.
  Inputs: `passer_position`, `teammates`, `opponents`.

- **evaluate_shot** — CALL BEFORE shooting. Returns goal probability, recommended aim
  location (TL/TR/BL/BR) and power. Only shoot when `should_shoot` is true
  (`success_probability > 0.25`). Inputs: `shooter_position`, `goalkeeper_position`,
  `team_side`, `blocker_positions`.

- **find_open_space** — CALL when repositioning without the ball. Returns the best
  coordinates to move to in a given zone. Inputs: `opponent_positions`, `zone`
  (attack/midfield/defense), `team_side`, `my_position`.

- **get_defensive_assignment** — CALL when defending. Returns opponent threats ranked by
  danger and the recommended mark. Mark the top threat with the returned tightness.
  Inputs: `opponents`, `ball`, `team_side`, `my_position`.
