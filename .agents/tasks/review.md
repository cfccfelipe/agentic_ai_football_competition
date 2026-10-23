# Review — static/dynamic per-tick prompt split with controlled ReAct flow

Branch: `refactor/static-dynamic-prompt` @ `2eb6b85`
Base: `feat/unified-agent-architecture`
Verdict: **APPROVED**

## Scope reviewed

Diff `feat/unified-agent-architecture...refactor/static-dynamic-prompt` (14 files,
+1967/-214). Production changes are confined to:
- `src/agents/players/plugin_loader.py` — new `load_tool_catalog`, `build_static_base`,
  `compose_tick_prompt`; `build_system_prompt` retired to a thin wrapper.
- `src/agents/players/unified_agent.py` — static base built once in `register()`;
  `invoke()` restructured into 3 phases with a logged strategy gate.
- `src/governance/tool_catalog.md` — new static catalog of the four MCP tools.
- Tests + `docs/per-tick-workflow.md` + `.agents/tasks/*`.

Working tree clean (no uncommitted changes).

## Evidence relied on

Commit message records `uv run pytest -q`: **170 passed (134 baseline + 36 new)**, e2e
intact. I did not re-run the suite. One narrow spot-check was warranted for the central
ADDITIVE A gate: `uv run pytest tests/test_unified_agent_phases.py -q` → **5 passed**.

## Gate-by-gate findings

**Tests green / e2e intact — PASS.** Recorded 170 passed. `tests/test_e2e_tick.py`
retains all five guarantees: state-aware selection (losing-late→aggressive,
winning-late→defensive), formation threaded into the prompt, a tactical tool offered AND
used, exactly one VALID correctly-tagged command, and both infinite-loop protections
(turns cap == `MAX_TOOL_ITERATIONS`, and a hanging model tripping the 3.5s wall-clock
fallback). Only additive `evaluate_shot` assertions were added to it.

**Budget / loop caps — PASS (unchanged).** `constants.py` still has
`TICK_TIMEOUT_SECONDS = 3.5`, `MAX_TOOL_ITERATIONS = 2`, `PER_TOOL_TIMEOUT_SECONDS = 1.0`,
`retries={"max_attempts": 1}`. `invoke()` PHASE 3 still runs under
`asyncio.wait_for(..., timeout=TICK_TIMEOUT_SECONDS)` with `limits={"turns":
MAX_TOOL_ITERATIONS}`, per-tool timeout wrapping intact, and the 3-layer fallback
(LLM → `fallback_fn` → `last_resort`) preserved. No unbounded loop introduced — the phase
control is ordered Python, not a new loop.

**Forbidden paths — PASS.** Diff name list contains no `cdk/`, `node_modules/`,
`agentcore.json`, `ai-team-strands-balanced/`, `sample-ai-possibilities/`, `Makefile`,
`.env`, `registry.py`, `deploy_all.py`, or `guardrails.md`. Guardrail RULES are untouched;
only a new, separate `tool_catalog.md` was added (presentation of tool-awareness, not a
rule change).

**No code-execution surface — PASS.** No code interpreter / code-agent / new dependency.
Calculation stays on the four existing MCP tools; `tool_catalog.md` names exactly those
four and no others (enforced by `test_tool_catalog_names_exactly_the_four_tools`).

**.md-only tuning promise — PASS.** Registry folder-scanning discovery untouched
(`strategy_names`/`strategy_descriptions` still delegate to `registry`).
`test_drop_strategy_zero_code.py` drops a brand-new strategy folder set (strategies/ meta +
all five position bodies, tool-free) and proves via the runtime entry points that it is
planner-selectable and loadable for all five positions with zero Python edit.

**New-module deploy contract — PASS.** No new module under `players/` was added; the
catalog ships inside the already-staged `governance/` folder.
`test_deploy_contract.py` guards that `SHARED_MODULES` stays exactly the five runtime
modules and that `governance` is in the staged set.

**Static built once / dynamic after decision / tool before risky action — PASS.**
`build_static_base()` is called once in `register()` and captured in the closure;
`invoke()` never recomposes it. `test_static_base_built_once_not_per_tick` breaks
`build_static_base` after register() and the tick still succeeds. Dynamic body is appended
only in PHASE 2 after the strategy is confirmed. `test_tool_catalog_drives_tool_use_with_tool_free_body`
proves a tool call precedes a SHOOT driven by the static catalog alone.

**ADDITIVE A — phase gate enforced + tested — PASS.** PHASE 1 resolves position + confirms
strategy with a logged coercion guard (not `assert`); PHASE 2 composes; PHASE 3 builds the
agent with tools. `test_phase_order_select_then_compose_then_factory` asserts
`events == ["select", "compose", "factory"]`. `test_unknown_strategy_is_coerced_not_raised`
proves coercion to `DEFAULT_STRATEGY` on the normal path.
`test_raising_planner_falls_back_without_compose_or_factory` proves neither compose nor
factory fires when the planner raises. No unbounded loop added.

**ADDITIVE B — routing — PASS.** Single-source `constants.position_for` /
`PLAYER_POSITIONS` (0=GK..4=FWD2). `effective_pid = myPlayers[0] if myPlayers else
my_player_id`. `test_routing_by_agentid.py` parametrizes all agentId 0..4 × both teams ×
both branches (payload-supplied myPlayers and pinned-id/myPlayers-absent), asserting the
correct position marker is present AND cross-wiring markers are absent, and that the output
is tagged with the right playerId/teamId. AWAY perspective handled via `summarize_state`.

**ADDITIVE C — flow doc — PASS.** `docs/per-tick-workflow.md` updated to the static/dynamic
split, the 3-phase gate (with the logged coercion), the settled MCP-tools-only calculation
decision (explicit "no code-interpreter"), the md-only promise, and where each cap applies.
Accurate to the implemented code; includes a keep-in-sync note and a mermaid diagram.

**Approved Option — PASS.** Option Y (inject chosen strategy `.md` into the tick prompt, no
in-tick network) is implemented. Decisive justification is the OFF-LIMITS `cdk/` rule
(Option X needs a new gateway MCP tool registered in `cdk/`); latency corroborates. The
no-extra-network claim holds against the 3.5s budget — both tool turns stay for PHASE 3.

## Non-blocking note

The commit message describes `test_unified_agent_phases.py` as "6" tests (T-ORDER x3,
T-STATIC-b, T-TOOL, phase-order). The file actually contains 5 test functions and all 5
pass (spot-checked). Every required category (phase ordering, coercion-not-raise,
raising-planner fallback, static-built-once, catalog-drives-tool-use) is present and green;
this is a narrative miscount in the commit message, not a behavioral or coverage gap. Not
blocking.

## Conclusion

No blocking findings. All hard gates satisfied, caps and fallback intact, forbidden paths
untouched, every ADDITIVE requirement implemented and tested, and the approved Option Y is
correctly realized.
