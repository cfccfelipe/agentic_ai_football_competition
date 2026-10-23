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

- `aggressive.md` — formation 1-0-3. Read when the team is chasing goals: losing by
  1+ with less than ~20 minutes left, losing by 2+ at any time, or level with time
  running out. The defender joins attacks.
- `balanced.md` — formation 1-2-1. The default. Read when no scoreline condition
  applies: early game, level score, or a one-goal margin with plenty of time left.
  The defender holds its natural defending role.
- `defensive.md` — formation 3-0-1. Read when protecting a lead: winning by 1+ with
  less than ~15 minutes left, or winning by 2+ with under ~25 minutes remaining. The
  defender sits deep in a back-heavy block.
