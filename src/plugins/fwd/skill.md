---
name: fwd
type: position
description: >
  Index for the FORWARD role. ANY player assigned the FWD role (not just one fixed id)
  reads these per-strategy prompt files. Navigation only — not loaded into the runtime
  prompt. One forward body works for 1, 2, or 3 forwards: spread across lanes, do not
  crowd the same channel.
---

# Forward (FWD) — Strategy Index

This ROLE has one prompt file per team strategy. The authoritative strategy is chosen
ONCE per tick by the planner for the whole team (it reads the scoreline and clock and
coordinates all five players). Do NOT pick your own strategy here — read the file the
planner selected. Picking per-agent modes independently would break the team
coordination the guardrails require.

Any outfield player resolved to the FWD role loads this folder, so it must work whether
the team fields ONE forward or THREE. Spread out: pick a lane (left / center / right)
based on where your teammates already are, and never crowd the same channel.

## Strategy files for this role

- `aggressive.md` — formation 1-1-2 (one back, one mid, two forward). Read when the team
  is chasing (losing by any margin) OR level and going for the win. Forwards press
  purposefully and take ON-target shots (evaluate_shot first), not speculative blasts.
- `balanced.md` — formation 2-1-1 (two defenders, the structured DEFAULT). Read whenever
  no clear late-lead condition holds: level or slim margin with time left. gameTime is in
  seconds, so ~120s is early, not late. Forwards attack ambitiously and keep the ball.
- `defensive.md` — formation 2-1-1 (a solid two-defender block to protect a lead). Read
  ONLY when protecting a CLEAR lead LATE in the match (not on a slim or early lead; ~120s
  is early). Forwards track back to help defend.
