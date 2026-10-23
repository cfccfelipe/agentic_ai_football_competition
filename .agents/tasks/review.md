# Review — fix/trace-driven-tactics (trace-driven tactics fix)

Scope reviewed: `git diff feat/unified-agent-architecture...fix/trace-driven-tactics`.
Changed files (19): `.agents/tasks/plan.md`, `src/commons/fallback.py`, 15 ×
`src/plugins/<pos>/<strategy>.md`, and two new test files
(`tests/test_prompt_examples_parse.py`, `tests/test_fallback_shoot_aim.py`).

## Verdict: APPROVED

No blocking findings. P0 genuinely parses (independently verified), the hard gate is met,
P1 is implemented and tested, P2–P5 are satisfied (prose already present / audit confirmed),
and every hard constraint holds.

---

## P0 — HARD GATE (independently verified: PASS)

Narrow spot-check performed directly from the worktree, not trusting the commit alone:

- `git grep "{{"` over `src/plugins/*/*.md` → **no matches** (exit 1). No body retains a
  doubled brace on any line, Example or otherwise.
- Rendered **all 15** position × strategy combos via
  `plugin_loader.load_skill_prompt(strategy, position, player_id)` and asserted, for each:
  no `{{`/`}}` anywhere in the rendered body, no leftover `{player_id}`/`{formation}`, and
  `json.loads` of the extracted `Example:` array yields a 1-element list whose single
  object has `playerId == sample id`. Result: `ALL 15 RENDERS OK; strategies=
  ('aggressive','balanced','defensive')`.
- The new guard `tests/test_prompt_examples_parse.py` is a real guard: it parametrizes all
  5 positions × `plugin_loader.strategy_names()`, strips the `Example:` prefix, and asserts
  (a) no `{{`/`}}`, (b) no unreplaced placeholders, (c) `json.loads` → single command whose
  `commandType ∈ VALID_COMMANDS`, int `playerId == sample`, dict `parameters`. It fails on
  the old doubled-brace templates and passes now. Ran it: 15 cases green.

The single-brace rewrite is applied consistently to all 15 Example lines while keeping the
single-token `{player_id}`/`{formation}` placeholders intact — matching the loader's
`str.replace` behavior. P0 hard gate satisfied.

## P1 — Shooting (PASS)

- FWD1/FWD2/MID aggressive + FWD1/FWD2 balanced bodies now gate distance explicitly:
  "only shoot when CLOSE — roughly inside 18-22 units of the opponent goal in x", keep
  "call evaluate_shot FIRST", use the tool's recommended aim corner (not a fixed corner),
  and removed "from any distance" / speculative-blast phrasing. aim is situational relative
  to the opponent goal for YOUR side ("Orient first: HOME +x / AWAY -x").
- `fallback.py`: `pick_shoot_aim(shooter_y, side)` replaces the blind constant in both
  deterministic shoot paths (`SHOOT_OR_PASS`, `SHOOT_OR_ADVANCE`). Vertical half from
  shooter y (y≤0 → top, y>0 → bottom), horizontal half from a per-config flank
  (`shoot_aim_side`: FWD1=L, FWD2=R, MID=R), so aim is a function of position and the
  attacking goal (aim_location is relative to the goal reached via `opp_goal_x`).
  `shoot_aim` retained only as a documented last-resort default. `shoot_threshold`,
  `shoot_power`, press/mark logic, the 3-layer fallback and `last_resort_*` fields are
  untouched.
- `tests/test_fallback_shoot_aim.py` covers FWD1(3)/FWD2(4)/MID(2) for **both** HOME
  (`team_id=0`) and AWAY (`team_id=1`): asserts a valid corner, that aim flips top/bottom
  with shooter y (situational, not constant), and that FWD1≠FWD2 flank. Ran it: 14 cases
  green.

## P2 — Phase + identity discipline (PASS)

`tool_catalog.md` carries the explicit ATTACK/DEFEND rule (teammate/MY holds → ATTACK,
opponent/OPP holds → DEFEND, loose → nearer recovers), the MY/OPP identity discipline
(teammates 0-4, opponents 0-4, "never press or mark a teammate; never pass to an
opponent"), and tool-first targeting (`calculate_pass_options` / `get_defensive_assignment`).
Bodies carry matching phase cues. `summarize_state` was intentionally left without a
`Phase:` line — the explicitly-allowed lower-risk markdown-only outcome — so no new
untested state code was introduced. Consistent with the plan.

## P3 — Command mix (PASS)

Bodies express possession-first/purposeful-press ("prefer forward/through balls via
calculate_pass_options", "a quick calculate_pass_options one-two … is better than a blind
blast"); no new aggressive-press language was added. Audit-only, no regression.

## P4 — Strategy/formation mix (PASS)

Audit only; no `planner.py` or strategy-description edit in the diff. Commit evidence states
level/early → balanced is already covered (`diff==0` → `DEFAULT_STRATEGY`,
`test_rule_early_level_is_balanced`). `planner.py` is unchanged, and the full suite
(including `test_planner.py` and `test_e2e_tick.py`) is green, so no regression.

## P5 — Housekeeping (PASS)

`git grep` for `CARRY_FORWARD|DRIBBLE|TACKLE_BALL|SHOOT_GOAL` across plugin bodies and
`tool_catalog.md` → no matches. Only valid command types appear in prompt text/examples.
`KICK`/`THROW` are `GK_DISTRIBUTE` method values, not commands.

## Hard constraints (all hold)

- Diff `--stat` shows no edits under `cdk/`, `node_modules/`, `agentcore.json`, `Makefile`,
  `.env`, `guardrails.md`, `ai-team-strands-balanced/`, or `sample-ai-possibilities/`.
- Only runtime `.py` touched is `src/commons/fallback.py` (ships as a folder → no
  `SHARED_MODULES` change needed, and none made). `deploy_all.py`, `planner.py`,
  `state.py`, `unified_agent.py`, `plugin_loader.py`, `constants.py` untouched. No new
  `players/` module added.
- `{player_id}`/`{formation}` tokens preserved; single-JSON-array `## Response` contract
  intact in all 15 bodies; strategy frontmatter and position skill types untouched; 3-layer
  fallback + caps preserved; `test_e2e_tick.py` green.

## Verification evidence

- Commit records `uv run pytest -q → 202 passed` (173 + 15 + 14). Re-ran the full suite
  from the worktree: **202 passed in ~13s**. Re-ran the two guard files: **29 passed**.
  Independent P0 render check: all 15 OK, no leftover braces/placeholders, valid JSON.
