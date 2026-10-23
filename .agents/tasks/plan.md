# Implementation Plan — Trace-Driven Tactics Fix (P0 + P1–P5)

Environment: Windows, PowerShell. The project uses `uv` — always `uv run pytest`, never bare
`python`. All paths below are absolute inside the worktree
`c:\Users\FelipeCortes\agentic_ai_football_competition\.worktrees\trace-fixes` (branch
`fix/trace-driven-tactics`). Relative paths would land in the parent repo — do not use them.

## Context discovered during exploration (read before implementing)

- **Baseline is GREEN: `uv run pytest -q` = 173 passed in ~10s.** This number must stay 173+
  and all green after the work, PLUS the new parse-guard test added in step 2.
- **The P0 templating bug is REAL and present in ALL 15 position bodies.** Every
  `src/plugins/<pos>/<strategy>.md` ends with an `Example:` line whose JSON uses DOUBLED
  braces `{{ ... }}` (str.format style). `plugin_loader.load_skill_prompt` only does
  `.replace("{player_id}", ...)` / `.replace("{formation}", ...)` and NEVER calls
  `.format()`, so `{{`/`}}` reach the model verbatim as invalid JSON. The model parrots the
  malformed shape and `parse_commands` rejects it → fallback every tick. Fixing this is the
  prerequisite for everything else. Confirmed via grep: 15 matches of `Example: [{{`.
- **CHOSEN APPROACH for P0 (md-first):** rewrite the Example lines to SINGLE braces so plain
  `str.replace` leaves VALID JSON. KEEP the single-token `{player_id}` / `{formation}`
  placeholders intact — those ARE meant to be replaced. Do NOT change
  `load_skill_prompt`'s replace-based approach (the new test in step 2 proves it is not
  necessary). This matches the loader's actual behavior and the test at
  `tests/test_plugin_loader.py::test_mid_aggressive_loads_position_file_and_composes_prompt`
  which already asserts `{player_id}`/`{formation}` are gone after render.
- **Much of the P1–P5 PROSE is already tuned in the bodies** (a prior pass). Current bodies
  already say: call `evaluate_shot` FIRST and only shoot on a good chance; use the tool's
  recommended aim corner (not a fixed corner); "Orient first: HOME attacks +x / AWAY -x,
  aim at the opponent goal for YOUR side"; phase cues (MY holds → ATTACK, OPP holds →
  defend, loose → nearest recovers); identity discipline (MARK/PRESS/INTERCEPT target an
  OPPONENT, PASS targets a teammate MY); possession-first + "press purposefully, not
  constant chasing"; `calculate_pass_options` before passing. So P1–P3/P4 are mostly
  satisfied in prose. The plan's prose steps are therefore SMALL reinforcements/audits, not
  rewrites — do not regress the existing good language.
- **`CARRY_FORWARD` does NOT appear anywhere** in `src/` (grep confirmed). The only `KICK`
  occurrences are `method:"KICK"` in the GK Example / "long KICKs" prose — `KICK` is a valid
  `GK_DISTRIBUTE` *parameter value*, NOT a command name, so it is fine. P5's invalid-command
  cleanup is already effectively done; step 7 is a verification audit, not an edit, unless a
  new invalid name is found.
- **`VALID_COMMANDS`** (`src/commons/parsing.py`): MOVE_TO, PASS, SHOOT, SLIDE_TACKLE,
  PRESS_BALL, INTERCEPT, MARK, FOLLOW_PLAYER, GK_DISTRIBUTE, SET_STANCE, CLEAR_OVERRIDE,
  RESET. (These are command TYPES; `aim_location`, `method`, `type`, `tightness`,
  `stance` values are separate and unconstrained by this set.)
- **`fallback.py` aim constants (P1 target):** `FWD1_CONFIG.shoot_aim="TR"`,
  `FWD2_CONFIG.shoot_aim="BL"`, `MID_CONFIG.shoot_aim="TR"` — blind constants. The
  deterministic shoot path is `_on_ball` → `SHOOT_OR_PASS`/`SHOOT_OR_ADVANCE`, which reads
  only `cfg.shoot_aim`. `fallback.py` is in `commons/` which ships as a whole folder, so it
  is SAFE to edit under the deploy contract.
- **`state.py::summarize_state` (P2 optional):** already emits `Your goal at x=… | Opponent
  goal at x=…`, per-player coords, `hasBall=…`, and possession as `MY player N` / `OPP
  player N` (direction-correct for HOME and AWAY). It does NOT emit an explicit
  `Phase: ATTACK/DEFEND` line. `state.py` is in `commons/` → safe to edit. Phase derives
  from possession: a teammate (MY) or self holding → ATTACK; an opponent (OPP) holding →
  DEFEND; loose/unknown → CONTEST (keep neutral).
- **`evaluate_shot` pure tool** (`src/plugins/general/scripts/evaluate_shot.py`) returns a
  situational `recommended_aim` (TL/TR/BL/BR) derived from GK y-offset and shooter y, plus
  `should_shoot = probability > 0.25`. This grounds the bodies' "use its recommended aim"
  language and informs the direction-aware fallback default in step 3.
- **Deploy contract (MUST preserve):** runtime `.py` under `src/agents/players/` imported at
  runtime must be in `deploy_all.py` `SHARED_MODULES` = `["constants.py", "planner.py",
  "plugin_loader.py", "unified_agent.py", "runtime_guards.py"]`. `commons/` ships as a
  folder, so `fallback.py` and `state.py` are already covered — NO `SHARED_MODULES` change
  is needed and none is allowed as part of this task.
- **Do NOT touch:** the entire `cdk/` tree, `node_modules/`, `agentcore.json` schema,
  `Makefile`, `.env`, `src/governance/guardrails.md` rules, `ai-team-strands-balanced/`,
  `sample-ai-possibilities/`. Do NOT touch `unified_agent.py`, `planner.py` (unless step 6
  proves it necessary), `plugin_loader.py`, `constants.py`, the 3.5s / 2-turn / 0-retry caps,
  or the 3-layer fallback structure. Preserve the single-JSON-array `## Response` contract,
  strategy frontmatter (`type: strategy` + `formation`), position `skill.md` (`type:
  position`-style), and all `tests/test_e2e_tick.py` guarantees.
- **Tests:** live in `tests/`, path-wired by `tests/conftest.py` (commons, src root,
  `src/agents/players`, general scripts all on `sys.path`). Reuse fixtures from
  `tests/test_helpers.py` (`GAME_STATE`, `TEAM_ID`, `mock_agentcore*`). Import modules bare
  (e.g. `import plugin_loader`, `from state import ...`). TDD: write/adjust the test alongside
  the change.

---

## Plan

- [ ] 1. **(P0 — ROOT CAUSE, prerequisite) Rewrite the `Example:` line in ALL 15 position
      bodies to use SINGLE braces so plain `str.replace` renders valid JSON.** In each file,
      change every `{{` → `{` and `}}` → `}` that wraps the JSON object and its nested
      `parameters` object ON THE `Example:` LINE ONLY. Leave the single-token `{player_id}`
      and `{formation}` placeholders exactly as they are (they ARE replaced by the loader).
      Do not touch any other line or any prose. Example of the fixed FWD1 line:
      `Example: [{"commandType":"SHOOT","playerId":{player_id},"parameters":{"aim_location":"TR","power":0.9}},"duration":0}]`
      — i.e. single braces around the array's object and around `parameters`, placeholders
      intact. Apply the identical single-brace transform to each file's own Example (keeping
      that file's existing command/params/values):
      Files:
        - src/plugins/gk/aggressive.md  (GK_DISTRIBUTE … method:"KICK")
        - src/plugins/gk/balanced.md    (GK_DISTRIBUTE … method:"THROW")
        - src/plugins/gk/defensive.md   (GK_DISTRIBUTE … method:"THROW")
        - src/plugins/def/aggressive.md (MOVE_TO … target_x/target_y/sprint)
        - src/plugins/def/balanced.md   (MARK … target_player_id/tightness)
        - src/plugins/def/defensive.md  (MARK … target_player_id/tightness)
        - src/plugins/mid/aggressive.md (SHOOT … aim_location:"TR"/power)
        - src/plugins/mid/balanced.md   (PASS … target_player_id/type:"THROUGH")
        - src/plugins/mid/defensive.md  (MARK … target_player_id/tightness)
        - src/plugins/fwd1/aggressive.md (SHOOT … "TR"/0.9)
        - src/plugins/fwd1/balanced.md   (SHOOT … "TR"/0.9)
        - src/plugins/fwd1/defensive.md  (MARK … target_player_id:1/tightness)
        - src/plugins/fwd2/aggressive.md (SHOOT … "BL"/0.9)
        - src/plugins/fwd2/balanced.md   (SHOOT … "BL"/0.85)
        - src/plugins/fwd2/defensive.md  (MARK … target_player_id:1/tightness)
      Verify: after step 2's test exists, `uv run pytest -q tests/test_prompt_examples_parse.py`
      passes; interim manual check — `uv run python -c "import sys; sys.path.insert(0,'src/commons'); sys.path.insert(0,'src'); sys.path.insert(0,'src/agents/players'); import json, plugin_loader; s=plugin_loader.load_skill_prompt('aggressive','FWD1',3); line=[l for l in s.splitlines() if l.startswith('Example:')][0]; json.loads(line.split('Example:',1)[1].strip()); print('OK')"`
      prints `OK` (no `{{`/`}}`, placeholders resolved, valid JSON).

- [ ] 2. **(P0 guard) Add a new parse-guard unit test that renders every position × strategy
      body via `plugin_loader.load_skill_prompt` and asserts the `Example:` JSON is valid.**
      Create `tests/test_prompt_examples_parse.py`. For each position in
      `("GK","DEF","MID","FWD1","FWD2")` × each strategy in `plugin_loader.strategy_names()`
      (and spot-check the real folder set `aggressive/balanced/defensive`), render with a
      sample `player_id` (e.g. GK→0, DEF→1, MID→2, FWD1→3, FWD2→4), extract the line starting
      with `Example:`, strip the `Example:` prefix, and assert: (a) no `{{` and no `}}`
      remain anywhere in the rendered body; (b) no literal `{player_id}` or `{formation}`
      remain; (c) `json.loads(...)` of the extracted array succeeds, returns a 1-element list
      whose single object has `commandType` in `parsing.VALID_COMMANDS`, an int `playerId`
      equal to the sample id, and a dict `parameters`. This test MUST fail on the old
      doubled-brace templates and pass after step 1. Import bare (`import plugin_loader`,
      `from parsing import VALID_COMMANDS`) — conftest wires the paths.
      Files: tests/test_prompt_examples_parse.py
      Verify: `uv run pytest -q tests/test_prompt_examples_parse.py` — all new cases pass
      (15+ renders green). Confirm it is a real guard by temporarily reverting one file's
      braces and seeing it fail (then restore) — or trust that step 1 is what turns it green.

- [ ] 3. **(P1 — fallback shoot aim) Make `fallback.py` shoot aim direction/position-aware
      instead of a blind constant, surgically, with a test.** In
      `src/commons/fallback.py`, replace the role of the fixed `shoot_aim` string in the
      deterministic shoot path (`_on_ball` → `SHOOT_OR_PASS` and `SHOOT_OR_ADVANCE`) with a
      small helper that picks the aim from the shooter's y relative to goal center so the
      shot is placed toward a corner away from the middle, consistent for both HOME and AWAY
      (attacking direction is already encoded by `opp_goal_x` sign from
      `get_goal_positions`). Concretely: add a helper (e.g. `_fallback_aim(pos, cfg)` or a
      module function `pick_shoot_aim(shooter_y, prefer_top)`) that returns a corner code —
      e.g. shooter in the lower half (y ≤ 0) aims to a TOP corner, upper half aims to a
      BOTTOM corner, and left/right of the corner follows a per-forward side preference so
      FWD1 and FWD2 still differ (preserve their distinct flank identity) — rather than
      returning a constant `TR`/`BL`. Keep `shoot_aim` on the config as a LAST-RESORT default
      only (used when position is unavailable). Keep the change minimal: do not alter
      `shoot_threshold`, `shoot_power`, the possession/press/mark logic, the 3-layer fallback,
      or the `last_resort_*` fields. Do NOT touch `unified_agent`/`planner`/`plugin_loader`,
      the caps, `cdk/`, `Makefile`, `.env`, or `guardrails.md`.
      Files: src/commons/fallback.py
      Verify: new test in step 4 passes; plus `uv run pytest -q tests/test_e2e_tick.py` stays
      green (the e2e fallback path still returns a valid, correctly-tagged command).

- [ ] 4. **(P1 — fallback aim test) Add a test proving FWD1/FWD2/MID fallback shots aim toward
      the correct opponent goal for BOTH HOME and AWAY and are not a blind constant.** Create
      `tests/test_fallback_shoot_aim.py`. Build a game state (deep-copy `GAME_STATE`) where
      the fallback shooter HOLDS the ball inside shoot range of the opponent goal, for each of
      FWD1 (id 3), FWD2 (id 4), MID (id 2). Build the fallback via
      `fallback.build_fallback(fallback.FWD1_CONFIG)` etc., call
      `fallback_commands(state, team_id, player_id)` for `team_id=0` (HOME, opp goal +55) and
      `team_id=1` (AWAY, opp goal -55), and assert: (a) the returned command is `SHOOT` with
      an `aim_location` in the valid corner set {TL,TR,BL,BR}; (b) the aim is chosen from the
      shooter's position (e.g. place the shooter with y>0 vs y<0 and assert the top/bottom
      half of the corner flips accordingly), demonstrating it is situational, not a fixed
      constant; (c) FWD1 and FWD2 still differ by flank preference for the same y. Reuse
      `holder_is_me`/possession helpers from `state` only as needed to set up possession
      (`possessionAgentId = "agentId_<id>"`, `isFree=False`, matching `teamCode`). Import
      bare (`import fallback`, `from state import ...`).
      Files: tests/test_fallback_shoot_aim.py
      Verify: `uv run pytest -q tests/test_fallback_shoot_aim.py` — all cases pass for HOME
      and AWAY.

- [ ] 5. **(P1–P3 prose audit — bodies) Audit and lightly reinforce the FWD/MID (and press)
      prose; only edit where a gap remains — do NOT rewrite already-good language.** The
      current bodies already: require `evaluate_shot` first, use the tool's recommended aim
      (no fixed corner), define aim relative to the opponent goal for YOUR side, carry phase
      cues, enforce identity discipline, say "press purposefully, not constant chasing", and
      require `calculate_pass_options` before passing. Make only these targeted edits if (and
      only if) the exact phrasing is still missing in a given file:
        - FWD/MID shoot DISTANCE gating in prose: ensure it says shoot when CLOSE/in range
          (roughly inside ~18–22 units of the opponent goal), not "within ~40"; if any body
          still implies long-range/speculative shooting or "always power 1.0", remove that
          phrasing. (Current `fwd*/aggressive.md` already say "no speculative blind blasts" —
          leave as-is if already compliant.)
        - Possession-first / less-press: ensure FWD/MID bodies say that when WE hold the ball,
          prefer PASS (via `calculate_pass_options`) and press only when close to the ball AND
          out of possession. Add the one missing clause only where absent.
      Do not change the `## Response` contract line, the Example line (step 1 owns it), the
      formation posture block, or the frontmatter. Keep diffs minimal and prose-only.
      Files (edit ONLY where a gap is found): src/plugins/fwd1/aggressive.md,
      src/plugins/fwd1/balanced.md, src/plugins/fwd2/aggressive.md, src/plugins/fwd2/balanced.md,
      src/plugins/mid/aggressive.md, src/plugins/mid/balanced.md
      Verify: `uv run pytest -q tests/test_prompt_examples_parse.py tests/test_plugin_loader.py`
      stays green (bodies still render and compose correctly); `uv run pytest -q` stays 173+.

- [ ] 6. **(P2 — optional, only if clearly safe) Add an explicit `Phase: ATTACK/DEFEND` line
      to `summarize_state`, plus matching tool_catalog/body wording; keep HOME/AWAY
      perspective correct.** Preferred: do it as a small deterministic helper in
      `src/commons/state.py`. Derive phase from the already-resolved possession:
      `get_possession_info(...)` returns `we_have_ball` and a `MY/OPP` holder; emit one line
      near the goal-orientation line — `Phase: ATTACK` when `we_have_ball` is true (a MY
      player, including self, holds), `Phase: DEFEND` when an OPP player holds, `Phase:
      CONTEST` when the ball is free/unknown. Do not change any existing line's text or
      ordering beyond inserting the new line; preserve stamina/`hasBall`/coords formatting.
      Also add to `src/governance/tool_catalog.md` (shared static) and, where not already
      present, to the bodies, the plain rule: "hasBall=True or a teammate (MY) holds the ball
      → ATTACK; an opponent (OPP) holds it or the ball is near YOUR goal → DEFEND" and the
      identity note: "teammate ids are YOUR team's 0–4; opponents are the other team's 0–4
      with the same numbers; agentId_N is per-team — never PASS to / MARK a player without
      confirming team; prefer calculate_pass_options / get_defensive_assignment to pick
      targets." (tool_catalog already covers most of this — add only the missing phrasing.)
      If the `summarize_state` change feels at all risky to existing `test_state.py`
      assertions, SKIP the code change and keep phase guidance in markdown only — that is an
      acceptable, explicitly-allowed outcome. Do NOT edit `guardrails.md`.
      Files: src/commons/state.py (optional), src/governance/tool_catalog.md, and any body
      missing the phase/identity clause.
      Verify: if `state.py` changed, add/extend a case in `tests/test_state.py` asserting the
      `Phase:` line reads `ATTACK` for the holder's team and `DEFEND` for the opponent team on
      the shared fixture (ball held by home agentId_3 → HOME sees ATTACK, AWAY sees DEFEND),
      and run `uv run pytest -q tests/test_state.py`. Then `uv run pytest -q` stays 173+ (+ new
      cases).

- [ ] 7. **(P4 — strategy/formation mix) Verify the strategy descriptions steer a level/early
      scoreline to `balanced` (1-2-1), not a constant `aggressive` (1-0-3); adjust
      descriptions first, and only touch `planner.py` with a minimal tested tweak if evidence
      shows descriptions alone cannot.** The three `src/plugins/strategies/<name>.md`
      descriptions already state: balanced is the DEFAULT for level/slim-margin with time
      left and that low/early `gameTime` (SECONDS, e.g. ~120) is NOT late; aggressive is for
      chasing or going to win (not a constant); defensive is ONLY for a clear late lead. Audit
      them for any wording that would push `aggressive` on a level/early state and tighten it
      if found (prose-only). Then inspect `planner.py::rule_based_strategy`: for a level score
      (`diff == 0`) it already returns `DEFAULT_STRATEGY` (balanced) regardless of clock, and
      only goes aggressive when trailing (late or by ≥2) — which is correct. Change
      `planner.py` ONLY if a concrete test shows a level/early state resolves to aggressive;
      if so, make a minimal, well-tested adjustment to `select_strategy`/`rule_based_strategy`
      preserving the existing thresholds' intent and the e2e guarantees. Prefer description
      rewrite first.
      Files: src/plugins/strategies/balanced.md, src/plugins/strategies/aggressive.md,
      src/plugins/strategies/defensive.md (prose audit); src/agents/players/planner.py (only
      if proven necessary, with a test in tests/test_planner.py).
      Verify: `uv run pytest -q tests/test_planner.py tests/test_e2e_tick.py` stays green; if
      `planner.py` changed, add a `tests/test_planner.py` case asserting a level/early state
      (`diff==0`, small `gameTime`) → `balanced` (DEFAULT_STRATEGY) and a trailing-late state →
      `aggressive`. (Note: `test_e2e_tick.py` asserts losing-late→aggressive and
      winning-late→defensive — must not regress.)

- [ ] 8. **(P5 — housekeeping audit) Confirm no invalid command names appear in any prompt
      text or Example, and fix any that do.** Grep all bodies, `skill.md` files, and
      `src/governance/tool_catalog.md` for command-name-looking tokens and confirm every one
      used as a COMMAND is in `VALID_COMMANDS`. `CARRY_FORWARD` is already absent (confirmed);
      `KICK`/`THROW` are `GK_DISTRIBUTE` `method` VALUES (not commands) and stay. If any
      genuinely invalid command name is found, replace it with the correct valid command or
      remove it. This step is an audit; edit only if a violation is found.
      Files: src/plugins/**/*.md, src/governance/tool_catalog.md (only if a violation found).
      Verify: `uv run pytest -q tests/test_prompt_examples_parse.py` (every Example command is
      in `VALID_COMMANDS`, enforced by step 2's assertion) plus a grep showing no
      `CARRY_FORWARD` / other non-VALID command token remains in prompt text.

- [ ] 9. **(Final gate) Run the full suite and confirm green.** Run `uv run pytest -q` from
      the worktree root and confirm the total is 173 (original) PLUS the new tests from steps
      2 and 4 (and any added in 6/7), with zero failures and zero regressions, especially
      `tests/test_e2e_tick.py`, `tests/test_plugin_loader.py`, `tests/test_state.py`,
      `tests/test_planner.py`, and `tests/test_deploy_contract.py` /
      `tests/test_deploy_all.py` (deploy-contract guarantees unchanged — no `SHARED_MODULES`
      edit was made). If anything fails, fix the cause before declaring done.
      Files: none (verification only).
      Verify: `uv run pytest -q` — all tests pass; count ≥ 175 (173 + at least the two new
      test files).

## Notes / assumptions

- The task prompt described the OLD prompt bodies (fixed-corner, "within ~40", "always power
  1.0", `CARRY_FORWARD`). Exploration shows most of that prose was ALREADY fixed in a prior
  pass. The plan therefore treats P1–P5 prose as an AUDIT-AND-REINFORCE pass (edit only where
  a gap remains) rather than a rewrite, to avoid regressing good language. P0 (step 1) and the
  `fallback.py` aim (step 3) are the substantive code/template changes; the two new test files
  (steps 2, 4) are the hard guards required by the task.
- `fallback.py` and `state.py` live under `commons/`, which `deploy_all.py` ships as a whole
  folder — no `SHARED_MODULES` change is needed or permitted.
- The P2 `summarize_state` phase line and the P4 `planner.py` tweak are both explicitly
  OPTIONAL and gated on "only if clearly safe / proven necessary"; markdown-only is an
  acceptable outcome for each. This keeps `.py` edits minimal: `fallback.py` aim is the only
  mandatory runtime change, with `state.py`/`planner.py` touched only if their guarding tests
  are added and stay green.
