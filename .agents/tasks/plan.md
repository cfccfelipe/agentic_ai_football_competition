# Implementation Plan — Final Consolidation (feat/dynamic-roles)

## OVERALL GOAL (state of the world when this lands)

When this work lands, the **ONLY thing the user ever changes going forward is the STRATEGY
MARKDOWN**: `src/plugins/strategies/*.md` plus `src/plugins/<role>/*.md` for the **4 roles**
`gk / def / mid / fwd`. Everything else — tactical tool calls actually working, dynamic roles
(player 0 = GK and player 1 = DEF **hard-pinned forever**, players 2/3/4 **flexible-by-flag**),
a stronger planner model with Nova Micro execution, schema discipline, forward/back direction +
attack/defend phase, defend-with-structure (cut reflexive INTERCEPT), and per-line team/pos/role
logging — must be **wired in CODE** so no future code edit is needed to adjust tactics. Adding or
improving a strategy stays **markdown-only**: drop `strategies/<name>.md` + `<role>/<name>.md` for
each of the 4 roles, and the registry folder-scan makes it selectable with ZERO Python change.

## MATCH EVIDENCE THAT SHARPENS PRIORITIES (we WON 2-1 — first win)

Confirmed by a real won match (our team "Lighting Cloud"):
- **KEEP:** PASS schema fix works (PASS rose to ~13%, possession 57%, won on possession/passing).
  DEF scored (min 1) and MID scored (min 2) — the **any-player-may-shoot/score** direction already
  pays off. GK (MVP, fastest, most tactical) must stay fast/decisive — apply ONLY proximity + zone
  gates, do NOT make it passive.
- **FIX HARDEST:** INTERCEPT is still 31% of commands (coach: cut ≥15%) — the reflexive ball-magnet.
  Defend-with-structure must be **blunt and strong** in the prompts.
- **FIX:** SHOOT ≈ 0 (only 2 all match) — forwards still don't reach close range and shoot. The
  forward-advance + require-`evaluate_shot` + situational-aim fixes are high priority.
- The GK being the most active player is a FLAG the outfield under-contributes; the real win is
  lifting DEF/MID/FWD decision quality, not tweaking the GK.

## HARD CONSTRAINTS (every item must respect)

- **Do NOT touch:** the entire `cdk/` folder, `node_modules/`, `agentcore.json` schema, `Makefile`,
  `.env`, `ai-team-strands-balanced/`, `sample-ai-possibilities/`.
- **guardrails.md RULE TEXT stays** — reference its §5/§8 intent from bodies, do NOT rewrite the rules.
- **Preserve:** single-brace `Example:` convention (P0), `{player_id}` / `{formation}` tokens, the
  single-JSON-array `## Response` contract, strategy frontmatter (`type: strategy` + `formation`),
  position `skill.md` (`type: position`), the 3.5s tick / 2-turn / 0-retry caps + 3-layer fallback,
  and all `tests/test_e2e_tick.py` guarantees.
- **Any NEW `players/` runtime module MUST be added to `deploy_all.py` `SHARED_MODULES`** (currently
  `constants.py, planner.py, plugin_loader.py, unified_agent.py, runtime_guards.py`).
- **TDD + uv** (code-conventions): write/adjust a `tests/` test first, run `uv run pytest`. Bodies are
  prompt files, not logic — their regression guard is `test_prompt_examples_parse.py` +
  `test_drop_strategy_zero_code.py` + the registry/loader tests.

## GROUNDING NOTES (read before editing — discovered in the worktree)

- **Agent runtime dirs stay 5.** `src/agents/players/ai-{gk,def,mid,fwd1,fwd2}/src/main.py` each pin a
  fixed `MY_PLAYER_ID` (0..4) and call `unified_agent.register(app, MY_PLAYER_ID)`. The fwd1/fwd2
  collapse is about **plugin folders and the role model**, NOT the agent dirs. `deploy_all.py`
  `ALL_AGENTS = ["ai-gk","ai-def","ai-mid","ai-fwd1","ai-fwd2"]` stays unchanged.
- **Role→folder resolution** lives in `plugin_loader.load_skill_prompt(strategy, position_label, pid)`
  which does `position_label.lower()` to pick the folder. Today `constants.position_for(3)="FWD1"` /
  `position_for(4)="FWD2"` → folders `fwd1`/`fwd2`. After the collapse, players 3 and 4 must resolve to
  the single `fwd` folder.
- **Parser is the schema source of truth** (`src/commons/parsing.py` `VALID_COMMANDS` + `_tag_commands`):
  PASS/GK_DISTRIBUTE use `target_player_id` + (`type` for PASS, `method` for GK_DISTRIBUTE); MOVE_TO uses
  `target_x`/`target_y`; MARK uses `target_player_id`/`tightness`. **Do NOT change the parser's accepted
  keys — fix the prompts to match it.**
- Tests hard-coding `fwd1`/`fwd2` that MUST be updated: `test_registry.py`, `test_discover_strategy.py`
  (`POSITIONS`), `test_drop_strategy_zero_code.py` (`POSITIONS`), and the e2e/invoke fixtures that pass
  `player_id=3`/`4`. `discover_strategy.py` `POSITIONS=("gk","def","mid","fwd1","fwd2")` must become the
  4-role set.
- Baseline is green: `uv run pytest -q` → **202 passed**. Keep it green after every item.

---

# PART A — CONFIRMED CODE BUGS (.py + tests, highest priority)

- [ ] 1. **(.py) A1/P1b — Fix the tool-registration bug so the 4 tactical tools actually register.**
      In `runtime_guards.py`, make the per-tool timeout wrapper a VALID Strands tool. Approach (most
      surgical, per finding a2): subclass `strands.types.tools.AgentTool` (import lazily inside the
      module so offline tests that fake `strands` still import — guard the import and fall back to the
      current proxy only if `AgentTool` is unavailable). The subclass must expose the wrapped tool's
      real `tool_name` and `tool_spec` (delegate the `@property` accessors the base requires) and
      override the invoke/stream entry point (`stream`/`invoke` per the installed `strands-agents`
      API) to run the underlying call through `call_with_timeout(..., PER_TOOL_TIMEOUT_SECONDS)`,
      returning the existing benign `{"status":"error",...}` sentinel on timeout. Keep
      `call_with_timeout` unchanged. `unified_agent.register` keeps wrapping `cached_tools` the same
      way (no change needed there if the wrapper is now a valid AgentTool), and the existing 3.5s tick
      `asyncio.wait_for` + `MAX_TOOL_ITERATIONS=2` cap are untouched.
      Files: `src/agents/players/runtime_guards.py`, `tests/test_runtime_guards.py`.
      Verify: `uv run pytest tests/test_runtime_guards.py -q` — existing pass-through/timeout tests
      still pass, PLUS a new test asserting (a) `isinstance(wrap_tool_with_timeout(raw, 1.0), AgentTool)`
      is True and the wrapper exposes `tool_name` + a `tool_spec` the registry accepts, and (b) a slow
      wrapped tool still returns the benign timeout sentinel. If the installed Strands `AgentTool`
      requires methods that cannot be satisfied offline, add a focused test that constructs the real
      `AgentTool` from the agent venv (document the exact base-class method signatures used).

- [ ] 2. **(.py) A1/P1b — Confirm the registry accepts the wrapped tool end-to-end.**
      Extend `tests/test_e2e_tick.py` (or add a small test) so the injected `_FakeTool` path proves a
      wrapped tool is still offered to the agent and callable (the existing e2e already asserts a tool
      is used; make sure it exercises the real `wrap_tool_with_timeout` rather than bypassing it).
      Keep all five e2e guarantees intact.
      Files: `tests/test_e2e_tick.py` (and `src/agents/players/unified_agent.py` only if the wrap call
      site needs adjustment).
      Verify: `uv run pytest tests/test_e2e_tick.py -q` — all tests pass.

- [ ] 3. **(.md + no-parser-change) A2/P1 — Schema discipline in EVERY role body (4 roles × 3 strategies
      = 12 files, applied as ONE consistent edit pattern).** In each body add a short "## Command schema
      (use THESE keys only)" block showing the EXACT accepted JSON per command the role uses, with a
      correct single-brace worked example, and an explicit line forbidding the invented keys. Required
      corrections (from the trace): `PASS` → `{"target_player_id": <id>, "type": "GROUND|THROUGH|..."}`
      — FORBID `targetId/target/targetPlayerId/passType/pass_type/power/target_x`; `MOVE_TO` →
      `{"target_x": <x>, "target_y": <y>, "sprint": <bool>}` — FORBID `x/y`; `GK_DISTRIBUTE` →
      `{"target_player_id": <id>, "method": "THROW|KICK"}` — FORBID `method:"PASS"/"SHORT_PASS"`; `MARK`
      → `{"target_player_id": <id>, "tightness": "TIGHT|LOOSE"}`; `SHOOT` →
      `{"aim_location": "TL|TR|BL|BR|CENTER", "power": <0..1>}`. Keep every existing `Example:` single-brace
      and the `## Response` contract. (After Part B collapse the forward files are `plugins/fwd/*.md`, not
      `fwd1`/`fwd2`.)
      Files: `src/plugins/{gk,def,mid,fwd}/{aggressive,balanced,defensive}.md`.
      Verify: `uv run pytest tests/test_prompt_examples_parse.py tests/test_drop_strategy_zero_code.py -q`
      — every body's example still parses to a valid command and schema tokens are present.

- [ ] 4. **(.py) A3/P8 — Per-line team/pos/role log prefix including TEAM NAME when available.**
      In `unified_agent.py` build a prefix ONCE inside `register()`/at the start of `invoke()` from
      `team_id`, the team NAME (pulled from the payload/gameState when present — e.g.
      `prompt_data`/`gameState` team-name field; fall back to just `team0`/`team1` when absent),
      `effective_pid`, and the role label, e.g. `[team0 'Lighting Cloud' pos0 GK] ...`. Prepend it to
      every `log.info/warn/error` emitted from `invoke()`. Also apply to `agent_base.py` log lines if
      that path still logs (it is the legacy handler). Build a tiny helper so the format is defined once
      (DRY). Do not change control flow or the returned commands.
      Files: `src/agents/players/unified_agent.py`, `src/commons/agent_base.py`,
      `tests/test_unified_agent_invoke.py` (assert the prefix appears on a captured log line via a
      capturing fake logger).
      Verify: `uv run pytest tests/test_unified_agent_invoke.py -q` — new log-prefix assertion passes,
      existing invoke tests still pass.

---

# PART B — DYNAMIC FORMATION & ROLES

## B0 — Collapse fwd1 + fwd2 into a single `fwd` role folder (STRUCTURAL)

- [ ] 5. **(.md move) Create `src/plugins/fwd/` by MERGING fwd1 + fwd2 into one role body per strategy.**
      Create `plugins/fwd/{aggressive,balanced,defensive}.md` + `plugins/fwd/skill.md` (`type: position`,
      formation notes like the fwd1/fwd2 index). Merge the two near-duplicate bodies into ONE generic
      forward body that: refers to "the opponent goal at x=X" generically (no left/right identity),
      tells forwards to **SPREAD / not crowd the same channel** and to pick a lane (left/center/right)
      based on where teammates are, so it works for 1, 2, or 3 forwards. Preserve ALL merged fwd tactical
      content: situational aim, `evaluate_shot`-first, forward/back direction, schema discipline (Part A
      item 3 applies here), the single-brace `Example:`, `{player_id}`/`{formation}` tokens, and the
      `## Response` single-JSON-array contract. Then DELETE `plugins/fwd1/` and `plugins/fwd2/` entirely.
      Files: create `src/plugins/fwd/aggressive.md`, `.../balanced.md`, `.../defensive.md`,
      `.../skill.md`; delete `src/plugins/fwd1/` and `src/plugins/fwd2/` (bodies + skill.md).
      Verify: `Get-ChildItem src/plugins` shows `fwd` present and `fwd1`/`fwd2` gone; defer test run to
      item 8 (role wiring) so the suite is green as a unit.

- [ ] 6. **(.py) Add role model: role label → folder, with FWD players resolving to `fwd`.**
      In `constants.py` introduce the 4-role set `ROLES = ("GK","DEF","MID","FWD")` and a mapping from a
      role label to its plugin folder (`GK→gk, DEF→def, MID→mid, FWD→fwd`). Keep `PLAYER_POSITIONS`/
      `position_for` for backward-compat but add a `role_folder(role_label)` helper (lowercases to the
      folder; FWD1/FWD2 both map to `fwd` for a transition period). Update
      `plugin_loader.load_skill_prompt` to resolve the folder via this helper instead of a raw
      `position_label.lower()`, so a `FWD`/`FWD1`/`FWD2` label all load `plugins/fwd/<strategy>.md`.
      Files: `src/agents/players/constants.py`, `src/agents/players/plugin_loader.py`,
      `tests/test_constants.py`, `tests/test_plugin_loader.py`.
      Verify: `uv run pytest tests/test_constants.py tests/test_plugin_loader.py -q` — new tests assert
      `role_folder("FWD")=="fwd"` and `load_skill_prompt("aggressive","FWD",3)` loads the merged forward
      body; update the existing `load_skill_prompt(...,"FWD1",3)` expectation to the `fwd` body.

- [ ] 7. **(.py) Update `discover_strategy.py` + its registry-facing validators to the 4-role set.**
      Change `POSITIONS` to `("gk","def","mid","fwd")`, update `REQUIRED_FILES`, `_target_paths`, the
      `_ALLOWED_UPPER_WORDS` set (drop `FWD1`/`FWD2`, add `FWD`), and any docstring/messages referencing
      five position bodies → four role bodies. This keeps "drop-a-strategy" generating the 4 role bodies.
      Files: `src/agents/players/discover_strategy.py`, `tests/test_discover_strategy.py`.
      Verify: `uv run pytest tests/test_discover_strategy.py -q` — all generator tests pass with the
      4-role spec (good spec writes `strategies/<name>.md` + `{gk,def,mid,fwd}/<name>.md`).

- [ ] 8. **(.py) Update registry + drop-strategy tests to the 4-role folder set.**
      Update `tests/test_registry.py` (`test_discovers_all_plugins`, `test_position_indexes_are_not_strategies`)
      and `tests/test_drop_strategy_zero_code.py` (`POSITIONS`) to expect `gk/def/mid/fwd` (not fwd1/fwd2).
      Confirm the **drop-a-strategy-is-zero-code** north star still holds with 4 roles: a new strategy =
      `strategies/<name>.md` + `<role>/<name>.md` for each of gk/def/mid/fwd, discovered by folder-scan,
      no Python change.
      Files: `tests/test_registry.py`, `tests/test_drop_strategy_zero_code.py`.
      Verify: `uv run pytest tests/test_registry.py tests/test_drop_strategy_zero_code.py -q` — pass.

## B1 — Dynamic roles: 0=GK / 1=DEF hard-pinned, 2/3/4 flexible-by-flag

- [ ] 9. **(.py, NEW SHARED MODULE) Create `formation_roles.py` — the single source of truth for roles.**
      New module `src/agents/players/formation_roles.py` exposing a pure function
      `formation_roles(formation: str, flex: bool = False) -> dict[int, str]` returning `{player_id: role}`
      for ids 0..4, roles drawn from `{GK, DEF, MID, FWD}`. Invariants:
      - **ALWAYS** `0 → "GK"` and `1 → "DEF"` regardless of formation or flag (guarantees ≥1 GK and ≥1 DEF).
      - Players **2, 3, 4**: when `flex=False`, assign them per the formation's **remaining DEF-MID-FWD
        distribution after reserving player0=GK and player1=DEF** (see mapping table below); when
        `flex=True`, return a sentinel role `"FLEX"` (or the formation default plus a `flex=True` marker)
        so `unified_agent` knows to let the agent reason about its own role this tick while still loading a
        concrete body (default to the formation's remaining distribution as the starting point).
      Decision/rationale (recorded here, not a separate doc): the function derives roles by subtracting the
      pinned GK+DEF from the formation's outfield DEF-MID-FWD counts, then fills ids 2→3→4 in DEF, then MID,
      then FWD order; this is deterministic and formation-agnostic. Add the module to `deploy_all.py`
      `SHARED_MODULES`.
      Files: create `src/agents/players/formation_roles.py`; edit
      `src/agents/players/deploy_all.py` (`SHARED_MODULES` list); create `tests/test_formation_roles.py`;
      update `tests/test_deploy_contract.py` — `test_shared_modules_is_the_expected_five` hard-codes the
      exact 5-module list and will FAIL until `formation_roles.py` is added to it (rename/adjust the
      assertion to include the new module; six modules now). Also check `tests/test_deploy_all.py`.
      Verify: `uv run pytest tests/test_formation_roles.py tests/test_deploy_all.py tests/test_deploy_contract.py -q`
      — for EVERY `ALLOWED_FORMATIONS` value with `flex=False`, assert `roles[0]=="GK"`, `roles[1]=="DEF"`,
      and that ids 2/3/4 match the mapping table below and the counts stay consistent; with `flex=True`
      assert `roles[0]=="GK"` and `roles[1]=="DEF"` still hold while 2/3/4 are flexible; and assert
      `formation_roles.py` is in `SHARED_MODULES`.

- [ ] 10. **(.py) Wire `formation_roles` into `unified_agent.invoke` + add the FLEX flag.**
      In `unified_agent.invoke`, after the strategy is confirmed, resolve this agent's role via
      `formation_roles(meta.formation, flex=<flag>)[effective_pid]` instead of `constants.position_for`.
      Read the flex flag from env `FLEX_ROLES` (truthy) OR a per-payload flag (`prompt_data.get("flexRoles")`),
      defaulting OFF so deploy never changes behavior unexpectedly. Use the resolved role label to pick the
      fallback config and to call `plugin_loader.compose_tick_prompt(..., role_label, ...)` → loads
      `plugins/<role_folder>/<strategy>.md`. When flex is ON for players 2/3/4, the composed prompt (from the
      role body) already lets the agent reason about its best role for the situation (see item 14 body text);
      the formation still informs the starting role. GK(0)/DEF(1) are unaffected by the flag.
      Files: `src/agents/players/unified_agent.py`, `tests/test_unified_agent_invoke.py`,
      `tests/test_unified_agent_phases.py`.
      Verify: `uv run pytest tests/test_unified_agent_invoke.py tests/test_unified_agent_phases.py tests/test_e2e_tick.py -q`
      — assert player 0 always loads the gk body and player 1 the def body regardless of flag; with flex OFF a
      given formation loads the mapped role body for players 2/3/4; with flex ON players 0/1 are still GK/DEF.
      Keep the `FALLBACK_CONFIGS` lookup working for the resolved role (map FWD→a forward config; see item 11).

- [ ] 11. **(.py) Reconcile fallback configs with the 4-role model.**
      `FALLBACK_CONFIGS` currently keys on `GK/DEF/MID/FWD1/FWD2`. Add a `FWD` key (reuse/merge the FWD1/FWD2
      configs into one forward fallback config — keep situational `pick_shoot_aim`; a single forward config is
      fine since the merged body no longer distinguishes flanks, but preserve a sensible `advance_y`/support
      spread). Keep FWD1/FWD2 keys as aliases to the FWD config for the transition so player ids 3/4 still
      resolve a config. Ensure `register()` selects the config by the resolved role label.
      Files: `src/commons/fallback.py`, `src/agents/players/unified_agent.py`, `tests/test_fallback_shoot_aim.py`.
      Verify: `uv run pytest tests/test_fallback_shoot_aim.py tests/test_unified_agent_invoke.py -q` — pass;
      a forward-role fallback still produces a situational SHOOT aim.

### Formation → role mapping table (every `ALLOWED_FORMATIONS` value)

GK(0) and DEF(1) are ALWAYS pinned. The table shows the role assigned to players **2, 3, 4** under
**flag OFF** (the formation's remaining DEF-MID-FWD distribution after subtracting the pinned GK + 1 DEF).
Under **flag ON**, 0→GK and 1→DEF are unchanged; players 2/3/4 start from the same distribution but the
body lets each agent reason about and adapt its role for the situation.

| Formation | Outfield DEF-MID-FWD | After pinning 1 DEF (player 1), remaining for 2/3/4 | player 2 | player 3 | player 4 |
|-----------|----------------------|------------------------------------------------------|----------|----------|----------|
| `0-4-0`   | 0 DEF, 4 MID, 0 FWD   | 0 DEF* / 3 MID (player1 counts as the structural back) | MID | MID | MID |
| `1-0-3`   | 1 DEF, 0 MID, 3 FWD   | 0 DEF / 0 MID / 3 FWD                                 | FWD | FWD | FWD |
| `1-1-2`   | 1 DEF, 1 MID, 2 FWD   | 0 DEF / 1 MID / 2 FWD                                 | MID | FWD | FWD |
| `1-1-1-1` | 1 DEF,1 MID,1 FWD (+1 staggered) | 0 DEF / ~1 MID / ~2 FWD (spread)           | MID | FWD | FWD |
| `1-2-1`   | 1 DEF, 2 MID, 1 FWD   | 0 DEF / 2 MID / 1 FWD                                 | MID | MID | FWD |
| `2-0-2`   | 2 DEF, 0 MID, 2 FWD   | 1 DEF / 0 MID / 2 FWD                                 | DEF | FWD | FWD |
| `2-1-1`   | 2 DEF, 1 MID, 1 FWD   | 1 DEF / 1 MID / 1 FWD                                 | DEF | MID | FWD |
| `3-0-1`   | 3 DEF, 0 MID, 1 FWD   | 2 DEF / 0 MID / 1 FWD                                 | DEF | DEF | FWD |

*Notes: player 1 is the one pinned DEF and counts toward the formation's DEF line. The fill order for
players 2→3→4 is DEF slots first, then MID, then FWD, consuming the formation's remaining counts. The
implementer must encode this fill rule in `formation_roles` and the test must assert each row exactly
(for `1-1-1-1`/`0-4-0`, pick a single deterministic fill and assert it — document the chosen fill in the
module docstring). Under flag ON the same row is the starting point; the agent may adapt within
`{DEF,MID,FWD}` but never to GK, and players 0/1 never change.

## B2 — Stronger planner model for the decision, Nova Micro for execution

- [ ] 12. **(.py) Add `PLANNER_MODEL_ID` and build the planner agent from it.**
      In `constants.py` add `PLANNER_MODEL_ID`, resolved from env `PLANNER_MODEL_ID` and defaulting to
      `MODEL_ID` (so deploy never breaks when no stronger model is confirmed). Add a
      `planner_model_kwargs()` mirroring `bedrock_model_kwargs()` but using `PLANNER_MODEL_ID`. Change
      `planner._default_agent` to build its `BedrockModel` from `planner_model_kwargs()`. Keep the
      planner's `call_with_timeout(..., TICK_TIMEOUT_SECONDS)` and the rule-based fallback unchanged.
      Research note: a stronger Bedrock model id (e.g. a Nova Lite/Pro or Claude Haiku id) could not be
      confirmed as enabled in account 937592087229 / us-east-1 from the plan step; therefore default to
      `MODEL_ID` and keep it env-overridable (`PLANNER_MODEL_ID`) — the implementer may set a confirmed
      stronger id in `.env.example` as a comment only (NEVER edit `.env`). Document: execution = Nova Micro
      (`MODEL_ID`), planning = `PLANNER_MODEL_ID` (stronger when configured).
      Files: `src/agents/players/constants.py`, `src/agents/players/planner.py`, `tests/test_constants.py`,
      `tests/test_planner.py`.
      Verify: `uv run pytest tests/test_constants.py tests/test_planner.py -q` — assert `PLANNER_MODEL_ID`
      defaults to `MODEL_ID` when env unset, honors the env override, and that `_default_agent` uses the
      planner kwargs; existing planner rule/selection tests still pass.

## B3 — Tactical fixes (markdown-first; fallback.py alignment)

- [ ] 13. **(.md) P2 — Forward/Back direction + Attack/Defend phase, spelled out numerically.**
      In `governance/tool_catalog.md` "Orient first" block AND every role body, state the direction
      computation bluntly for a small model: "You attack the opponent goal at x=X. FORWARD = move your x
      toward X; BACK/DEFEND = move your x toward your own goal at the opposite end. If you have the ball and
      are not close to X, MOVE_TO toward X. NEVER move toward your own goal to attack." Add a hard phase
      rule: we hold → ATTACK (go forward / offer a lane); they hold → DEFEND (drop to your zone). Do NOT
      rewrite `guardrails.md`. Keep examples single-brace.
      Files: `src/governance/tool_catalog.md`, `src/plugins/{gk,def,mid,fwd}/{aggressive,balanced,defensive}.md`.
      Verify: `uv run pytest tests/test_prompt_examples_parse.py tests/test_plugin_loader_static.py -q` — pass
      (catalog still composes into the static base; examples still parse).

- [ ] 14. **(.md) P3 — Defend-with-structure / anti-ball-magnet (CUT reflexive INTERCEPT, hard).**
      In every role body add a blunt rule reinforcing guardrails §5/§8 (reference them, don't rewrite):
      "When the opponent has the ball (DEFEND phase): only the SINGLE closest teammate to the ball
      PRESS_BALL/INTERCEPTs. Everyone else MARK the nearest unmarked opponent or hold your zone. Do NOT
      emit INTERCEPT as a per-tick reflex — INTERCEPT only a ball you can actually win in your zone." Make
      it strong because the LLM over-emits INTERCEPT (31% of commands). Add the "am I the closest?" self-check
      to def/mid/fwd bodies. Keep the any-player-may-score behavior (item 15) — this item is about defending.
      Files: `src/plugins/{gk,def,mid,fwd}/{aggressive,balanced,defensive}.md`.
      Verify: `uv run pytest tests/test_prompt_examples_parse.py tests/test_drop_strategy_zero_code.py -q`
      — bodies still parse / drop-strategy still zero-code.

- [ ] 15. **(.md) P5/P7 — Require tools before risky actions; any player may SHOOT a clear close chance.**
      In every role body: require `evaluate_shot` before SHOOT (shoot only on a good result, situational aim,
      inside ~18-22u of the opponent goal); require `calculate_pass_options` before PASS and pass to the MOST
      OPEN teammate advancing toward the opponent goal; use `find_open_space` for off-ball MOVE_TO. Add an
      explicit SHOOT branch to the `def` and `mid` bodies: "ANY player — including DEF/MID — with a clear close
      chance (inside ~18-22u, confirmed by evaluate_shot) SHOULD SHOOT" (preserves the DEF/MID goals that won
      the match). Add the same license to `tool_catalog.md`. This item DEPENDS on item 1 (tools must register).
      Files: `src/governance/tool_catalog.md`, `src/plugins/{gk,def,mid,fwd}/{aggressive,balanced,defensive}.md`.
      Verify: `uv run pytest tests/test_prompt_examples_parse.py -q` — the def/mid SHOOT example parses; all
      bodies still valid.

- [ ] 16. **(.md) P6 — GK under pressure: proximity gate + zone discipline (minimal, keep GK fast).**
      In all three `gk/*.md` bodies: "If an opponent is within ~8-10u of you or the ball, do NOT GK_DISTRIBUTE
      — hold/shield (SET_STANCE 2 or a short MOVE_TO toward your goal) or distribute ONLY to a clearly open
      teammate; `method` ∈ {THROW,KICK} only." Keep the GK in the defensive third: remove the "halfway line /
      beyond / extra attacker" language from `gk/aggressive.md` and cap forward MOVE_TO to the defensive third
      (≈ x ≤ -35 HOME / x ≥ +35 AWAY). Per match evidence, keep the GK decisive — it should still
      INTERCEPT/clear genuine threats near our goal; the gate only stops distributing into pressure and
      wandering upfield. Do NOT make it passive.
      Files: `src/plugins/gk/aggressive.md`, `src/plugins/gk/balanced.md`, `src/plugins/gk/defensive.md`.
      Verify: `uv run pytest tests/test_prompt_examples_parse.py -q` — pass; manual read confirms no
      "halfway line / extra attacker" text remains in `gk/aggressive.md`.

- [ ] 17. **(.py) B3 — `fallback.py` alignment (secondary layer, keep it consistent).**
      Align the deterministic fallback so a fallback tick does not re-introduce old behavior: (a) GK branch —
      soften `_on_ball` GK_DISTRIBUTE so it prefers a clearly-open teammate (keep `method:"THROW"`), keep
      `GK_CONFIG.default_x_factor=0.9` (deep); (b) make DEF able to SHOOT in fallback when within
      `shoot_threshold` of the opponent goal (give `DEF_CONFIG` a `SHOOT_OR_PASS`-style branch or add a shoot
      check), keeping `pick_shoot_aim`; (c) keep GK default_x deep and DEF as a defensive line (not the goal
      line, not the opponent half). Do NOT change `pick_shoot_aim` behavior.
      Files: `src/commons/fallback.py`, `tests/test_fallback_shoot_aim.py` (+ a small new test for the DEF
      fallback shoot branch).
      Verify: `uv run pytest tests/test_fallback_shoot_aim.py -q` — new DEF-can-shoot-when-close test passes;
      GK fallback still distributes deep with THROW/KICK.

## B4 — Strategy descriptions + formation mapping (P4)

- [ ] 18. **(.md) P4 — Remap formations to two defenders by default + rewrite strategy descriptions.**
      Edit the three `strategies/*.md` frontmatter + descriptions:
      - `balanced.formation: 2-1-1` (two real defenders — the default structured shape).
      - `aggressive.formation: 1-1-2` (NOT `1-0-3` — too thin).
      - `defensive.formation: 2-1-1` (or keep `3-0-1`; choose `2-1-1` for a solid block consistent with the
        default — RECORD the choice in the description). Recommendation: use `2-1-1` for defensive so the
        team always has ≥2 defenders in structured shapes, and reserve `3-0-1` only if a park-the-bus body is
        desired later.
      Rewrite descriptions to be crystal clear and decision-relevant: `gameTime` is SECONDS (≈120 is NOT late);
      do NOT pick aggressive at kickoff 0-0 by default — start structured (balanced/2-1-1); pick aggressive
      only when genuinely chasing (losing, or level and deliberately pushing late). All three formations here
      are in `ALLOWED_FORMATIONS`. Update the fwd/skill.md (and any role skill.md) formation references that
      cite the old `1-0-3`/`1-2-1`/`3-0-1` to the new mapping.
      Files: `src/plugins/strategies/{balanced,aggressive,defensive}.md`, `src/plugins/fwd/skill.md`
      (and `gk/def/mid` skill.md if they cite formations).
      Verify: `uv run pytest tests/test_registry.py tests/test_e2e_tick.py -q` — NOTE: `test_e2e_tick.py`
      currently asserts `"1-0-3" in prompt` for aggressive; **update that assertion to the new aggressive
      formation `1-1-2`** as part of this item, then confirm green. Registry still discovers 3 strategies
      with valid formations.

- [ ] 19. **(.py) P4 — Planner thresholds so aggressive is NOT picked ~85-95% of ticks.**
      Review `planner.rule_based_strategy` and the description-driven `select_strategy`: ensure the default at
      level/early scorelines is the structured `balanced` (2-1-1), and aggressive only when truly chasing.
      The rule already returns `DEFAULT_STRATEGY` (balanced) at level/early — confirm it matches the rewritten
      descriptions so the LLM planner and the rule agree. Adjust thresholds only if a test shows aggressive is
      selected at kickoff 0-0. Keep the planner timeout/caps.
      Files: `src/agents/players/planner.py`, `tests/test_planner.py`.
      Verify: `uv run pytest tests/test_planner.py -q` — add/adjust a test asserting kickoff (0-0, low
      gameTime) → `balanced`, and losing-late → `aggressive`, winning-late → `defensive`; all pass.

---

# FINAL INTEGRATION & VERIFICATION

- [ ] 20. **Full suite + green-tree check.** Run the entire test suite and confirm no regressions across the
      runtime-code changes (Part A, B0-B2), the prompt changes (B3-B4), the collapsed `fwd` folder, the new
      `formation_roles` module in `SHARED_MODULES`, and the updated fixtures. Ensure the e2e five-point tick,
      drop-strategy-zero-code (4 roles), deploy-contract (SHARED_MODULES includes `formation_roles.py`), and
      prompt-examples-parse all pass. Leave no scratch files in the tree.
      Files: none (verification only).
      Verify: `uv run pytest -q` — all tests pass (baseline was 202; expect ≥202 with the new tests), and
      `git status` shows only intended changes (new `plugins/fwd/`, deleted `plugins/fwd1,fwd2/`, new
      `formation_roles.py`, edited runtime + bodies + strategies + tests).

## Dependency order (summary)
A1/P1b tool-fix (items 1-2) FIRST → it unblocks tool-require prompts (item 15). B0 collapse (5-8) before
B1 wiring (9-11). B1 before B3 bodies that mention roles. B4 formation remap (18) updates the e2e
assertion. Logging (4) and planner model (12) are independent and can land anytime. Item 20 is last.

## Assumptions / gaps (reasonable choices made, not blockers)
- Stronger planner model: no stronger Bedrock id confirmed enabled in-account at plan time → default
  `PLANNER_MODEL_ID` to `MODEL_ID`, env-overridable. Implementer may note a candidate id as a comment in
  `.env.example` only.
- `defensive.formation`: chose `2-1-1` for a consistent two-defender block (over `3-0-1`); recorded in the
  description. Implementer may keep `3-0-1` if a distinct park-the-bus is explicitly wanted — but default to
  `2-1-1`.
- `1-1-1-1` / `0-4-0` fill for players 2/3/4: pick ONE deterministic fill, document it in the
  `formation_roles` docstring, and assert it exactly in the test.
- Team name source: pulled from the payload/gameState if the server provides it; otherwise the prefix falls
  back to `team0`/`team1`. Implementer confirms the exact field name when wiring item 4; absence is handled.
