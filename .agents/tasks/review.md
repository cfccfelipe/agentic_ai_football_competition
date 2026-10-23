# Review — tactics/md-tuning (markdown-only tactics tuning)

Base: `feat/unified-agent-architecture` · Head: `tactics/md-tuning` · Commit `52d6bff`

Verdict: **APPROVED**

Reviewed the branch diff (`git diff feat/unified-agent-architecture...tactics/md-tuning`),
the `--name-only` list, the recorded commit verification, and the actual on-disk files for
structural invariants. Did not re-run the suite; used the coder's recorded result.

## Gate 1 — ONLY markdown files changed — PASS

`--name-only` lists 25 paths, every one a `.md` file:
- `.agents/tasks/tactics-plan.md` (allowed plan artifact)
- `src/governance/tool_catalog.md` (markdown; NOT `guardrails.md`, so allowed)
- 3 × `src/plugins/strategies/*.md`
- 5 × `src/plugins/<pos>/skill.md`
- 15 × `src/plugins/<pos>/<strategy>.md`

No `.py`, nothing under `cdk/`, no `Makefile`, no `.env`, and `src/governance/guardrails.md`
is NOT in the diff. Gate passes.

## Gate 2 — Tests green — PASS

Commit `52d6bff` message records, under "Verification (run from worktree root)":
`uv run pytest -q -> 173 passed (no assertion edits needed)`. This matches the expected
~173 tests run from the worktree root. Evidence present; no articulable doubt (markdown-only
change), so no spot-check was warranted. Gate passes.

## Gate 3 — Structure intact across all files — PASS

- **3 strategies/*.md frontmatter**: all keep `type: strategy` and their valid formations —
  aggressive `1-0-3`, balanced `1-2-1`, defensive `3-0-1` (unchanged; verified by reading the
  frontmatter head of each file).
- **5 <pos>/skill.md**: all 5 position index files keep `type: position`
  (`def`, `fwd1`, `fwd2`, `gk`, `mid`). (`general/skill.md` is `type: scripts` and out of scope.)
- **15 <pos>/<strategy>.md bodies**: all contain `{player_id}`, `{formation}`, a `## Response`
  section, the "JSON array" wording and "exactly ONE" command contract (verified by scanning
  every file). SHOOT example power lowered 1.0 → 0.9 in the aggressive forward/mid bodies; the
  single-command array contract is preserved.
- **No cross-wiring**: role identity line is correct in every file — gk = goalkeeper,
  def = defender, mid = midfielder, fwd1 = "Forward 1", fwd2 = "Forward 2".

## Gate 4 — Decided tactical direction reflected — PASS

(a) **SHOOTING** — FWD1/FWD2/MID bodies now instruct the model to call `evaluate_shot` FIRST
and aim at the OPPONENT goal mouth for YOUR side (HOME→x=+55, AWAY→x=-55), explicitly "never a
fixed corner regardless of side". The "always power 1.0 / take speculative shots" instruction
is removed; aggressive SHOOT examples changed 1.0 → 0.9. Defensive forwards now shoot on-target
if the ball falls in the box (via evaluate_shot) instead of reflex pass-back. ✔

(b) **LESS PRESS / MORE PASS** — DEF and MID bodies and the balanced/defensive strategy bodies
reduce PRESS_BALL to "purposeful, not constant chasing" and raise PASS/possession via
`calculate_pass_options` (build out instead of hoofing/clearing). Pressing is kept purposeful,
not removed. ✔

(c) **AMBITION / STAMINA** — balanced bodies push the shape up ("push the shape up the pitch",
"do not camp in our half", "be progressive, not passive") and stamina guidance stops
over-conserving ("stop over-conserving stamina", "spend it where it matters"). ✔

(d) **PLANNER DESCRIPTIONS** — strategies descriptions and the 5 skill.md index narrations are
synced: balanced is the confident default for level/slim-margin with time left; aggressive
covers chasing OR level-and-wanting-to-win; defensive is ONLY for protecting a CLEAR lead LATE.
All three strategy descriptions and skill.md lines state gameTime is in SECONDS and ~120s is
early, not late — so a low gameTime no longer over-triggers defensive. ✔

## Conclusion

All four gates pass. Markdown-only, tests recorded green, structure and role mapping intact,
and the agreed tactical direction (fix shooting, less press / more possession, more ambition,
smarter planner) is reflected consistently across bodies, strategy descriptions and skill
indexes. APPROVED.
