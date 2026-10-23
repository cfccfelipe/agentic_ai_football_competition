---
name: balanced
type: skill
description: >
  The default strategy. Each player holds its natural role — the GK guards, defenders
  defend, midfielders link play, forwards attack. Balanced risk. Choose this when no
  specific scoreline condition applies: the game is early, the score is level, or you
  lead/trail by one goal with plenty of time left.
---

# Balanced Strategy

Natural position roles. Balance attack and defense. Do not over-commit forward or sit
too deep — react to the state of play.

## Position References

Load the file matching the agent's positionLabel:

- `gk.md`   — positionLabel = GK   (player 0)
- `def.md`  — positionLabel = DEF  (player 1)
- `mid.md`  — positionLabel = MID  (player 2)
- `fwd1.md` — positionLabel = FWD1 (player 3)
- `fwd2.md` — positionLabel = FWD2 (player 4)

## Scripts

Use all tools from the `general` plugin.
