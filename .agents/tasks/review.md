# Review — feat/dynamic-roles (final consolidation)

Diff reviewed: `feat/unified-agent-architecture..feat/dynamic-roles` (57 files, +1581/-739).
Recorded verification evidence (commit `7e0c40f3`): `uv run pytest -q => 265 passed`
(baseline 202 + fwd-collapse parametrization + new tests). Evidence read, not re-run per
the step instructions. No articulable doubt justified a spot-check beyond the targeted
reads below.

Verdict: **APPROVED** — no blocking findings.

## Gate-by-gate evidence

**Gate 1 — A1/P1b tool-registration fix.** `runtime_guards.wrap_tool_with_timeout` now
produces a real Strands `AgentTool` subclass (`_TimeoutAgentTool`) when the base is
importable, delegating `tool_name`/`tool_spec`/`tool_type` to the wrapped tool and bounding
the async `stream` with `asyncio.wait_for(self._timeout)`, yielding a benign `ToolResultEvent`
error on timeout; it falls back to the legacy proxy only offline. `tests/test_runtime_guards.py`
installs a faithful abstract `AgentTool`+`ToolResultEvent` and asserts `isinstance(wrapped,
AgentTool)`, an accepted `tool_spec` (`name`+`inputSchema`), fast stream-through, and a slow
tool timing out benignly (`status=="error"`, prompt return). The 3.5s tick cap
(`TICK_TIMEOUT_SECONDS=3.5` via `asyncio.wait_for` in `unified_agent.invoke`) and
`MAX_TOOL_ITERATIONS=2` (threaded as `limits={"turns":...}`) are preserved; `test_e2e_tick`
exercises the real wrap path and asserts a tool is offered and used.

**Gate 2 — Schema discipline (A2/P1) in all 4 role bodies × 3 strategies.** Every body
carries a "Command schema (use THESE parameter keys ONLY)" block with correct worked keys and
an explicit FORBIDDEN list: PASS `target_player_id`+`type` (forbids targetId/passType/power/
target_x), MOVE_TO `target_x`/`target_y` (forbids x/y), GK_DISTRIBUTE `method` THROW/KICK
(forbids method:PASS). Confirmed in `fwd/aggressive.md`, `def/balanced.md`, `gk/aggressive.md`,
`mid/balanced.md`. `parsing.py` is NOT in the diff — accepted keys unchanged.

**Gate 3 — 4-role collapse (B0).** `src/plugins` now holds only `gk/def/mid/fwd` role folders
(+`general` tools, `strategies` frontmatter); `fwd1`/`fwd2` folders are gone. `fwd/` is a single
generic forward body referencing "opponent goal at x=X" and spread/pick-a-lane for 1–3 forwards.
`plugin_loader.load_skill_prompt` resolves via `constants.role_folder` (FWD/FWD1/FWD2→`fwd`);
`discover_strategy.POSITIONS=("gk","def","mid","fwd")`; registry/fixtures/e2e updated.
`test_drop_strategy_zero_code.py` asserts a brand-new strategy is selectable + loadable for all
four roles with zero Python change. Residual `fwd1`/`fwd2` strings are all intentional
(transition aliases in constants/fallback/unified_agent, the `ai-fwd1`/`ai-fwd2` runtime dirs the
plan keeps, and the off-limits `guardrails.md`).

**Gate 4 — Dynamic roles (B1).** New `formation_roles.py` (pure `formation_roles(formation,
flex)`) hard-pins `0→GK`, `1→DEF` for every formation and both flag states; players 2/3/4 take
the formation's remaining DEF→MID→FWD fill (flag OFF) and are marked flexible via `is_flexible`
(flag ON) while never becoming GK. `unified_agent.invoke` resolves the per-tick role from it
(+player_id+formation+flex) and composes `plugins/<role>/<strategy>.md`, appending a flex prompt
for 2/3/4 when ON. `test_formation_roles.py` asserts the 0=GK/1=DEF invariant under both flags
for every `ALLOWED_FORMATIONS`, the exact flag-OFF table, the 4-role set, flag-ON flexibility,
and `formation_roles.py ∈ SHARED_MODULES`. `deploy_all.SHARED_MODULES` includes it.

**Gate 5 — Planner model split (B2).** Execution stays `MODEL_ID` (Nova Micro).
`constants.planner_model_id()`/`planner_model_kwargs()` resolve `PLANNER_MODEL_ID` from env,
defaulting to `MODEL_ID` so deploy never breaks. `planner._default_agent` builds from
`planner_model_kwargs()`; `select_strategy` keeps `call_with_timeout(..., TICK_TIMEOUT_SECONDS)`
and the rule fallback. `test_constants.py` + `test_planner.py` cover default, env override,
kwargs source, and `_default_agent` using the planner kwargs. Documented in `.env.example`.

**Gate 6 — Tactical fixes (B3).** `tool_catalog.md` + every body spell out numeric FORWARD/BACK
and a hard ATTACK/DEFEND phase rule; one-presser/anti-ball-magnet ("am I the closest?"); require
`evaluate_shot` before SHOOT (situational aim, ~18–22u) with an explicit DEF/MID shoot branch;
require `calculate_pass_options` before PASS (most-open). `gk/*` adds the under-pressure gate
(~8–10u), THROW/KICK only, and stays in the defensive third — the "halfway line / extra attacker"
text is removed from `gk/aggressive.md`. `fallback.py`: DEF now `SHOOT_OR_PASS` (shoots when
within `shoot_threshold=22`, else builds out, never to GK via `pass_exclude_ids=[0]`), GK
distributes deep with THROW. `test_fallback_shoot_aim.py` adds DEF-shoots-close and
DEF-builds-out-never-to-GK.

**Gate 7 — Formation remap (B4/P4).** `balanced.formation=2-1-1`, `aggressive=1-1-2`,
`defensive=2-1-1`. Descriptions are explicit that gameTime is SECONDS (~120s is early) and to
START structured, not aggressive, at kickoff. Role `skill.md` formation references updated.

**Gate 8 — Logging flag (A3/P8).** `unified_agent` builds a `[team<id> '<name>' pos<id> <ROLE>]`
prefix once per tick (team name from payload/gameState, falls back to `team<id>`), prepended to
info/warn/error. `test_unified_agent_invoke.py` asserts the prefix with and without a team name.

**Gate 9 — Tests green / e2e intact.** Recorded `265 passed`. `test_e2e_tick.py` keeps the five
guarantees and updates the aggressive assertion to `1-1-2`.

**Gate 10 — No forbidden-path edits.** Diff name-list contains none of cdk/, node_modules,
agentcore.json, Makefile, `.env`, ai-team-strands-balanced/, sample-ai-possibilities/, or
guardrails.md. (`.env.example` and `docs/`/`src/eval` are editable.) Conventions preserved:
single-brace `Example:`, `{player_id}`/`{formation}` tokens, single-JSON-array `## Response`,
strategy frontmatter, caps + 3-layer fallback.

## Notes (non-blocking, no action required)
- `constants.position_for(3)`/`(4)` now return `"FWD"` (not FWD1/FWD2); the FWD1/FWD2 aliases in
  `FALLBACK_CONFIGS`/`role_folder` keep any id-3/4 caller resolving a config/body. Intentional
  transition shim, consistent with the plan.
