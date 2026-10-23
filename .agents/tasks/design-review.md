# Design Review — Static/Dynamic Prompt Split with Controlled ReAct Flow

Reviewed: `.agents/tasks/design.md` (Revision 2) in worktree
`c:\Users\FelipeCortes\agentic_ai_football_competition\.worktrees\static-dynamic-prompt`.

This is a fresh review against the actual source. Every load-bearing claim in the design
was checked against the files it cites. The design is unusually well-grounded: most of its
"verified in source this revision" statements hold up. Findings below are the gaps that
remain.

---

## Verdict inputs

Count of blocking findings: **0 HIGH, 0 MEDIUM**. NITs only. Verdict: **APPROVED**.

---

## Findings

### 1. NIT — `type: strategy` frontmatter is a silent hard requirement for a dropped-in strategy, but AC-N1 / T-DROP only say "valid frontmatter"

Where: §2 AC-N1, §9 T-DROP.

The north-star test drops `strategies/<new>.md` with "valid frontmatter" and asserts
`plugin_loader.strategy_names()` includes `<new>`. Verified in `src/plugins/registry.py`:
`strategy_names()` → `registry.strategies()` filters `{n: m for ... if m.type ==
"strategy"}`. A `strategies/<new>.md` that omits `type: strategy` (default `type` falls to
`"skill"` in `_meta_from_frontmatter`) is discovered by `discover()` but **silently dropped
by `strategies()`**, so the planner never sees it — the exact north-star regression the
test exists to catch would pass or fail confusingly depending on the fixture.

Concrete fix: make the required frontmatter explicit in AC-N1 and T-DROP. State that the
dropped-in `strategies/<new>.md` MUST carry `name: <new>` and `type: strategy` (and
optionally `formation:`), mirroring the verified `strategies/balanced.md`:

```
---
name: <new>
type: strategy
formation: 1-2-1
description: >
  ...
---
```

Add a sentence to T-DROP: "the fixture's `strategies/<new>.md` uses `type: strategy` (the
discovery filter in `registry.strategies()` requires it)."

### 2. NIT — "built once / not recomposed per tick" is asserted but not fully proven by the described T-STATIC

Where: §3 (Built once, reused), §9 T-STATIC, AC-S1.

T-STATIC monkeypatches `plugin_loader.build_static_base` (and `load_guardrails`) to raise
*after* `register()`, then runs a tick and asserts success. Verified against
`unified_agent.register`: the closure does capture register-time locals
(`skill_descriptions`, `known_strategies`, `cached_tools`), so capturing `static_base` the
same way is consistent and the raise-after-register spy is a valid "not recomputed" proof.
The one gap: the design's planned `compose_tick_prompt(static_base, ...)` still calls
`load_skill_prompt(...)` per tick, which itself calls `registry.strategies()` and a file
read every tick. That is correct and intended (the dynamic layer), but T-STATIC as written
only proves the *base* is not rebuilt — it does not guard against a future refactor
accidentally calling `build_static_base()` inside `compose_tick_prompt`.

Concrete fix: in T-STATIC, additionally assert `compose_tick_prompt` does not call
`build_static_base` — e.g. spy a call-counter on `build_static_base`, run N ticks after
register, and assert the counter stayed at its register-time value (1). One extra assertion,
same test.

### 3. NIT — `limits={"turns": 2}` enforcement is relied upon but explicitly not re-verified against the installed Strands 1.13.0

Where: §4 (Strands version note, "NB:" sentence), AC-A3, AC-R2.

The design is honest that it does not re-verify whether `limits={"turns": 2}` is actually
enforced by real Strands `Agent.__call__` on 1.13.0 — it calls this "pre-existing behavior."
Verified against `tests/test_e2e_tick.py`: the cap is only ever exercised by a *fake* agent
that voluntarily honors `kw["limits"]["turns"]`
(`test_tool_iteration_cap_stops_a_would_be_looping_model`). So the entire anti-infinite-loop
guarantee for the real runtime rests on an unproven assumption about the vended library.
This is pre-existing (not introduced here) and the wall-clock `asyncio.wait_for(3.5s)` is a
real independent backstop, so it does not block — but the design should name the wall-clock
timeout as the *authoritative* loop bound and the turns cap as best-effort.

Concrete fix: in AC-A3 add: "Infinite-loop safety is guaranteed by the 3.5s wall-clock
`asyncio.wait_for` (authoritative), with `limits={'turns':2}` as a best-effort early stop
whose real-library enforcement is not verified here." No code change.

### 4. NIT — `effective_pid = my_players[0] if my_players else my_player_id` can still take a wrong id when `myPlayers` is present but does not contain this agent's own id

Where: §4 PHASE 1 snippet, §7, §8 input-validation summary.

Verified against `unified_agent.invoke`: current code does `my_players =
prompt_data.get("myPlayers", [my_player_id]); effective_pid = my_players[0] ...`. The design
preserves this verbatim. For a single-agent-per-runtime deployment where the server sends
`myPlayers=[thisAgentId]`, `[0]` is correct. But `myPlayers[0]` blindly trusts the payload:
if the server ever sends the full roster (e.g. `myPlayers=[0,1,2,3,4]`) to every runtime,
every agent would resolve to position GK (id 0) and all five would load `gk/<strategy>.md` —
a silent cross-wiring that T-ROUTE's `myPlayers=[pid]` parametrization would not catch
because it only ever puts the matching id in the list.

This is pre-existing behavior the design chose to keep, and the game-domain note confirms
each agent gets its own payload, so it is a NIT not a blocker. But the routing additive (B)
is precisely where it should be pinned down.

Concrete fix: either (a) document in AC-B3 that `myPlayers` is contractually a single-element
list `[thisAgentId]` and T-ROUTE need not cover multi-element lists; or (b) harden the
resolution to prefer the pinned id when present in the list:
`effective_pid = my_player_id if my_player_id in (my_players or []) else (my_players[0] if
my_players else my_player_id)`, and add a T-ROUTE case with `myPlayers=[0,1,2,3,4]` asserting
the agent still resolves to its pinned position. Pick one and state it.

### 5. NIT — the "softening" optional edits to skill bodies are listed as touching files the design elsewhere says it will not behaviorally require, with no guard that they stay optional

Where: §6 item 2, §11 (files to touch — OPTIONAL bodies), AC-N3.

The resolution of the old Finding 3 (catalog is the *sufficient* driver) is sound and
verified consistent: T-TOOL uses a tool-free body to prove it. But §11 still lists
`src/plugins/<pos>/<strategy>.md` as optional reinforcement edits. If the implementer makes
those edits, nothing in the test plan prevents a future contributor from *relying* on them
and regressing AC-N3. The design says per-body wording is optional; the tests should pin
that bodies remain non-load-bearing.

Concrete fix: T-TOOL already does this implicitly (tool-free body). Make it explicit in
AC-N3: "No skill body under `src/plugins/<pos>/` may be the sole source of decide-with-facts;
T-TOOL enforces this by using a body with zero tool mentions." Optionally, skip the §11
body edits entirely to keep the change surface to `tool_catalog.md` + the two Python modules
+ docs + tests.

---

## Verified Assumptions

These design claims were checked against source and hold:

1. **guardrails.md §8 exists and item 4 reads "consult the tactical tools, then PASS or
   SHOOT."** — VERIFIED in `src/governance/guardrails.md`. §8 "Decision Priority (Every
   Tick)" is present and item 4 is verbatim as quoted. §8 names no tool for MOVE_TO or
   MARK/PRESS_BALL, exactly as the design states.
2. **`DEFAULT_STRATEGY = "balanced"` and `PLAYER_POSITIONS` (0=GK..4=FWD2) and
   `position_for` default to MID exist.** — VERIFIED in `constants.py`. Also confirmed
   `TICK_TIMEOUT_SECONDS=3.5`, `MAX_TOOL_ITERATIONS=2`, `PER_TOOL_TIMEOUT_SECONDS=1.0`, and
   `max_attempts=1` (retries off) in `bedrock_model_kwargs`.
3. **`invoke()` wraps its body in `except Exception` → fallback.** — VERIFIED in
   `unified_agent.py`. The broad `except` is present and an `assert` in PHASE 1 would indeed
   be swallowed by it (and stripped by `-O`), so the design's choice of an explicit logged
   guard over `assert` is correct.
4. **All five main.py pin the correct id and call `register(app, MY_PLAYER_ID)`.** —
   VERIFIED: gk=0, def=1, mid=2, fwd1=3, fwd2=4. The `register(app, my_player_id,
   agent_factory=None)` signature matches.
5. **`deploy_all.py` stages `("commons","plugins","governance","requirements.txt",
   *SHARED_MODULES)` and `SHARED_MODULES = ["constants.py","planner.py","plugin_loader.py",
   "unified_agent.py","runtime_guards.py"]`.** — VERIFIED. A new `governance/*.md` ships
   automatically; no module change needed. AC-R5's no-op claim holds.
6. **`plugin_loader.strategy_names()` → `registry.strategies()` with no argument (reads
   module-level `PLUGINS_DIR`); `load_skill_prompt` resolves bodies from module-level
   `_PLUGINS_ROOT`.** — VERIFIED. The design's T-DROP correctly monkeypatches BOTH
   `registry.PLUGINS_DIR` and `plugin_loader._PLUGINS_ROOT`.
7. **`load_skill_prompt` falls back unknown-strategy → DEFAULT_STRATEGY and
   unknown-position → `mid/<strategy>.md`, never raising.** — VERIFIED in `plugin_loader.py`.
8. **`docs/per-tick-workflow.md` exists and shows the OLD single-step `build_system_prompt`
   with no static/dynamic split and no phase gate.** — VERIFIED; the mermaid flow uses
   `plugin_loader.build_system_prompt()` = guardrails + skill, so AC-C1's UPDATE (not
   duplicate) is correct.
9. **`strategies/` folder exists with per-strategy frontmatter files
   (`strategies/balanced.md`).** — VERIFIED. `balanced.md` carries `name/type:
   strategy/formation/description` frontmatter; `registry.discover()` handles the
   `strategies/` dirname by globbing `*.md`.
10. **test_e2e_tick.py asserts `"JSON array"`, `"Formation"`, and `"1-0-3"` via
    `build_system_prompt("aggressive","FWD1",3)`, plus tool-used / single-command /
    cap-stops-loop / timeout-fallback.** — VERIFIED. The design's Finding-5 requirement
    (wrapper must keep full guardrails + `{formation}`) correctly protects these assertions.
11. **Option X requires registering a new MCP tool on the gateway, which lives in the
    off-limits `cdk/` vended package.** — VERIFIED by the deploy flow: the gateway and its
    4 Lambda tools are declared in `agentcore/agentcore.json` and created by `agentcore
    deploy` via CDK; `deploy_all.py` does not stand up new MCP endpoints from OUR code. The
    design correctly chooses Option Y (local `.md` read, zero network, both tool turns
    preserved) and correctly treats the cdk/ constraint as decisive and latency as
    corroborating. No `cdk/` edit is required by the chosen design.
12. **No code interpreter / no new dependency.** — VERIFIED consistent: the design uses only
    the existing 4 MCP tactical tools and `strands-agents>=1.13.0`. `discover_strategy.py`'s
    web-research path is confirmed out of the tick path (not imported by `unified_agent`).
13. **3-layer fallback (LLM → rule_based → last_resort) is preserved.** — VERIFIED against
    `invoke()` (timeout→fallback_fn, parse-fail→fallback_fn, except→fallback_fn then
    last_resort) and `planner.select_strategy` (LLM → `rule_based_strategy`).

## Unverified / Wrong Assumptions

1. **`limits={"turns": 2}` is actually enforced by the real Strands `Agent.__call__` on
   1.13.0.** — NOT VERIFIED (the design itself flags this). Only a fake agent honors the cap
   in tests; the real-library behavior was not checked against the installed package. Not
   introduced by this design, and the 3.5s wall-clock is an independent backstop. See
   Finding 3.

2. **`myPlayers[0]` always equals this agent's own pinned id when `myPlayers` is present.** —
   NOT VERIFIED against a server contract. Current code and the design trust it; a
   full-roster `myPlayers` would misroute. See Finding 4. The game-domain steering implies
   per-agent payloads but does not pin the `myPlayers` shape to a single element.

No wrong assumptions were found — every concrete claim the design cites as "verified this
revision" checked out against source.
