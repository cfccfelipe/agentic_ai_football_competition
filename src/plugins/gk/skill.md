---
name: gk
type: position
description: >
  Index for the goalkeeper (player 0). Points to the per-strategy prompt files for
  this position and documents when each team strategy applies. Navigation only — not
  loaded into the runtime prompt.
---

# Goalkeeper (GK) — Strategy Index

This position has one prompt file per team strategy. The authoritative strategy is
chosen ONCE per tick by the planner for the whole team (it reads the scoreline and
clock and coordinates all five players). Do NOT pick your own mode here — read the
file the planner selected. Picking per-agent modes independently would break the
team coordination the guardrails require.

## Strategy files for this position

- `aggressive.md` — formation 1-1-2 (one back, one mid, two forward). Read when the team is
  chasing (losing by any margin) OR level and going for the win. The GK is a PROACTIVE
  sweeper-keeper but stays inside its defensive third.
- `balanced.md` — formation 2-1-1 (two defenders, the structured DEFAULT). Read whenever no
  clear late-lead condition holds: level or slim margin with time left. gameTime is in
  seconds, so ~120s is early, not late. The GK guards and distributes to keep possession.
- `defensive.md` — formation 2-1-1 (a solid two-defender block to protect a lead). Read
  ONLY when protecting a CLEAR lead LATE in the match (not on a slim or early lead; ~120s is
  early). The GK stays deep and never leaves its line.
