---
name: def
type: position
description: >
  Index for the defender (player 1). Points to the per-strategy prompt files for this
  position and documents when each team strategy applies. Navigation only — not loaded
  into the runtime prompt.
---

# Defender (DEF) — Strategy Index

This position has one prompt file per team strategy. The authoritative strategy is
chosen ONCE per tick by the planner for the whole team (it reads the scoreline and
clock and coordinates all five players). Do NOT pick your own mode here — read the
file the planner selected. Picking per-agent modes independently would break the
team coordination the guardrails require.

## Strategy files for this position

- `aggressive.md` — formation 1-0-3. Read when the team is chasing (losing by any
  margin) OR level and going for the win. The defender joins attacks and builds out.
- `balanced.md` — formation 1-2-1. The confident default. Read whenever no clear
  late-lead condition holds: level or slim margin with time left. gameTime is in
  seconds, so ~120s is early, not late. The defender holds shape and builds possession out.
- `defensive.md` — formation 3-0-1. Read ONLY when protecting a CLEAR lead LATE in the
  match (not on a slim or early lead; ~120s is early). The defender sits deep in a back-heavy block.
