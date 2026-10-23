# Implementation Plan — Static/Dynamic Prompt Split with Controlled ReAct Flow

Derived from the approved `design.md` (Revision 2). Python, Windows, `uv`, TDD,
SOLID/DRY/YAGNI. All work happens in the worktree
`c:\Users\FelipeCortes\agentic_ai_football_competition\.worktrees\static-dynamic-prompt`.
Run everything with `uv run pytest` (never bare `python`). Baseline today: **134 tests
green**. Every item below must leave the tree buildable and the suite green.

TDD note: each code item lists the test(s) that gate it. Write or update the test first (or
alongside), then the implementation, then run the stated command. Tests live under `tests/`
and reuse `tests/test_helpers.py` fixtures (`GAME_STATE`, `mock_agentcore_gateway`, DI via
`agent_factory`). Keep every new test pure — no AWS, no network.

Key facts verified in the worktree (ground truth for the plan):
- `plugin_loader.py` has `_SRC_ROOT` and `_PLUGINS_ROOT`; `load_guardrails()` reads
  `GOVERNANCE = _SRC_ROOT/"governance"/"guardrails.md"`. `build_system_prompt` already does
  `guardrails + "\n\n---\n\n" + skill`.
- `unified_agent.register()` is the once-per-process site (captures `skill_descriptions`,
  `known_strategies`, `cached_tools`); `invoke()` currently calls
  `plugin_loader.build_system_prompt(strategy, pos, effective_pid)` **inside** the per-tick
  body, wrapped in `except Exception` → fallback.
- `constants.DEFAULT_STRATEGY = "balanced"`, `constants.position_for`, `PLAYER_POSITIONS`
  (0=GK,1=DEF,2=MID,3=FWD1,4=FWD2), `TICK_TIMEOUT_SECONDS=3.5`, `MAX_TOOL_ITERATIONS=2`,
  `PER_TOOL_TIMEOUT_SECONDS=1.0` all present.
- `registry.strategies()` / `plugin_loader.strategy_names()` read module-level
  `registry.PLUGINS_DIR` / `plugin_loader._PLUGINS_ROOT` (no dir override in the runtime
  path) — T-DROP must monkeypatch BOTH.
- `guardrails.md` has `## 8. Decision Priority (Every Tick)`, item 4 = "consult the tactical
  tools, then PASS or SHOOT". Catalog must stay consistent, contradict nothing.
- `deploy_all.py` stages `("commons","plugins","governance","requirements.txt",*SHARED_MODULES)`;
  `SHARED_MODULES = ["constants.py","planner.py","plugin_loader.py","unified_agent.py","runtime_guards.py"]`.
  A new `governance/*.md` ships automatically. **No new `players/` module is introduced by
  this plan**, so `SHARED_MODULES` stays unchanged (item 9 guards that invariant).
- All five `ai-<pos>/src/main.py` pin the correct id (gk=0, def=1, mid=2, fwd1=3, fwd2=4) and
  call `unified_agent.register(app, MY_PLAYER_ID)` — no change needed.
- Strands pinned `strands-agents>=1.13.0` (`src/agents/players/requirements.txt`). The
  controlled flow uses only `Agent(model, system_prompt, tools)` + per-invocation
  `limits={"turns": 2}` — no newer API. Phase control is ordered Python, not a Strands graph.
- `docs/per-tick-workflow.md` exists and shows the OLD single-step build → UPDATE, not create.

---

- [ ] 1. Add the static tool-catalog markdown asset.
      Create `src/governance/tool_catalog.md` — a self-contained markdown section that names
      EXACTLY the four deployed tactical tools (`evaluate_shot`, `calculate_pass_options`,
      `find_open_space`, `get_defensive_assignment`), gives a one-line trigger for each, and
      states the controlled-flow contract ("before a risky action call the matching tool once,
      read the result, then return exactly one JSON-array command"). Use the catalog body from
      design §3 as the source text. It must restate NO rule that contradicts `guardrails.md`
      (no "return prose", no ">1 command", no "shoot toward your own goal"), and must mention
      no tool-looking token other than those four. This file ships via the already-staged
      `governance/` folder — no `deploy_all.py` change.
      Files: `src/governance/tool_catalog.md`
      Verify: `uv run pytest -q` — still 134 green (no code references it yet; this item just
      adds the asset the next items consume).

- [ ] 2. Add `load_tool_catalog()` and `build_static_base()` to the loader (TDD, T-CAT + T-STATIC part 1).
      First write `tests/test_plugin_loader_static.py`: (T-CAT) `plugin_loader.load_tool_catalog()`
      returns text containing exactly the four tool names and no other `\w+_\w+`-looking tool
      token, and does NOT contain contradictory guardrail wording; (T-STATIC-a)
      `plugin_loader.build_static_base()` returns a string containing both the full guardrails
      text (assert on `"JSON array"`) and all four tool names, and two calls return identical
      text. Then implement in `plugin_loader.py`: `load_tool_catalog() -> str` reads
      `_SRC_ROOT/"governance"/"tool_catalog.md"` (mirrors `load_guardrails`), and
      `build_static_base() -> str` returns `load_guardrails() + "\n\n---\n\n" + load_tool_catalog()`.
      Pure, deterministic, no strategy/position args.
      Files: `src/agents/players/plugin_loader.py`, `tests/test_plugin_loader_static.py`
      Verify: `uv run pytest -q tests/test_plugin_loader_static.py` — new tests pass.

- [ ] 3. Add `compose_tick_prompt()` and rewire `build_system_prompt()` as a thin wrapper (TDD, T-DYNAMIC loader part).
      Extend `tests/test_plugin_loader_static.py`: assert
      `compose_tick_prompt(base, "aggressive", "FWD1", 3)` equals
      `base + "\n\n---\n\n" + load_skill_prompt("aggressive","FWD1",3)`, carries the FWD1-aggressive
      body marker and the resolved formation `"1-0-3"`; and assert `build_system_prompt("aggressive","FWD1",3)`
      STILL contains the full guardrails (`"JSON array"`), a tool name, `"Formation"`, and `"1-0-3"`
      (Finding 5 — keeps the e2e markers alive). Then implement in `plugin_loader.py`:
      `compose_tick_prompt(static_base, strategy, position_label, player_id) -> str` returns
      `static_base + "\n\n---\n\n" + load_skill_prompt(strategy, position_label, player_id)`;
      re-express `build_system_prompt(strategy, position, player_id)` as
      `compose_tick_prompt(build_static_base(), strategy, position, player_id)`. Leave
      `load_skill_prompt`, `strategy_descriptions`, `strategy_names` unchanged (registry discovery
      untouched → north-star AC-N1 preserved).
      Files: `src/agents/players/plugin_loader.py`, `tests/test_plugin_loader_static.py`
      Verify: `uv run pytest -q tests/test_plugin_loader_static.py` and `uv run pytest -q` — all green
      (existing `build_system_prompt` callers, incl. e2e, still pass via the wrapper).

- [ ] 4. Wire the static base + 3-phase controlled flow into `unified_agent.py` (TDD, T-ORDER + T-DYNAMIC + T-STATIC part 2).
      Create `tests/test_unified_agent_phases.py` FIRST using `mock_agentcore_gateway()` and the
      `agent_factory` DI seam (follow `test_unified_agent_invoke.py` / `test_e2e_tick.py` patterns):
      (T-ORDER) spy/counter on `planner.select_strategy`, `plugin_loader.compose_tick_prompt`, and
      the injected `agent_factory`; assert call order select_strategy → compose_tick_prompt →
      agent_factory, and that compose/factory do NOT run until select_strategy returns. Force
      select_strategy to return an UNKNOWN name → assert the PHASE-1 guard coerces it to
      `constants.DEFAULT_STRATEGY` WITHOUT raising (a valid command still comes out via the normal
      compose path, not the `except`→fallback path, and `compose_tick_prompt` received the default).
      Force select_strategy to RAISE → assert neither compose_tick_prompt nor agent_factory fired and
      a deterministic fallback command is returned. (T-STATIC-b) monkeypatch
      `plugin_loader.build_static_base` to raise AFTER `register()` has run, then run a tick and
      assert it still succeeds — proving the base was captured once in the closure and is not rebuilt
      per tick. Then implement in `unified_agent.py`:
        - In `register()`, after computing `known_strategies`, add
          `static_base = plugin_loader.build_static_base()` captured in the closure.
        - In `invoke()`, restructure into three explicit phases:
          PHASE 1 — parse, resolve `effective_pid`/`pos`, call `planner.select_strategy(...)`, then an
          explicit **logged guard** (NOT `assert`): `if strategy not in known_strategies:
          log.warn(...); strategy = constants.DEFAULT_STRATEGY`.
          PHASE 2 — `system_prompt = plugin_loader.compose_tick_prompt(static_base, strategy, pos, effective_pid)`
          and `summarize_state(...)`.
          PHASE 3 — build the agent with `tools=cached_tools`, run under the EXISTING
          `limits={"turns": constants.MAX_TOOL_ITERATIONS}`, `asyncio.wait_for(timeout=TICK_TIMEOUT_SECONDS)`
          over the executor, `parse_commands` → yield, else fallback; on timeout → fallback.
        Keep the whole body in the existing `except Exception` → fallback, and the per-tool timeout
        wrapping, retries-off, and 3-layer fallback exactly as today. Do NOT call `build_static_base`
        inside `invoke()`.
      Files: `src/agents/players/unified_agent.py`, `tests/test_unified_agent_phases.py`
      Verify: `uv run pytest -q tests/test_unified_agent_phases.py tests/test_unified_agent_invoke.py` —
      new phase tests pass and the existing invoke-guard tests (timeout, raising-model, cap-as-limits,
      valid-command) stay green.

- [ ] 5. Prove tool-awareness is driven by the static catalog alone (TDD, T-TOOL, north-star AC-N3).
      Add `test_tool_catalog_drives_tool_use` to `tests/test_unified_agent_phases.py` (or a new
      `tests/test_decide_with_facts.py`). Inject a fake `evaluate_shot` tool (count calls, like
      `_FakeTool` in `test_e2e_tick.py`) and a fake model whose `agent_factory` callback, BEFORE
      returning a SHOOT command, calls the offered tool once — modelling a catalog-following agent.
      Use a possession state (FWD on the ball) and assert `tool.calls >= 1` and the final command is
      a single VALID command. The assertion proves the static catalog makes the agent tool-aware
      independent of any per-body tool wording (the skill bodies are NOT edited in this plan).
      Files: `tests/test_unified_agent_phases.py` (or `tests/test_decide_with_facts.py`)
      Verify: `uv run pytest -q tests/test_unified_agent_phases.py` (or the new file) — passes.

- [ ] 6. Prove per-agentId routing to position + skill file for both teams (TDD, T-ROUTE, AC-B1..B4).
      Add `tests/test_routing_by_agentid.py`. Parametrize over `player_id ∈ {0,1,2,3,4}` ×
      `team_id ∈ {0,1}`, capturing the composed `system_prompt` via the `agent_factory` DI seam.
      Branch (a) payload-supplied: payload carries `myPlayers=[pid]` (and `teamCode:"away"` players for
      team 1); assert the composed prompt contains the position-unique body marker for that pid
      (GK text for 0, DEF for 1, MID for 2, FWD1 for 3, FWD2 for 4) and the correct HOME/AWAY
      perspective. Branch (b) pinned-id: register with `my_player_id=pid`, OMIT `myPlayers`; assert
      the same position body resolves. Confirms single-source `constants.position_for`, no
      cross-wiring, and both resolution paths. (Pick stable per-position markers from the real
      `src/plugins/<pos>/<strategy>.md` bodies during implementation.)
      Files: `tests/test_routing_by_agentid.py`
      Verify: `uv run pytest -q tests/test_routing_by_agentid.py` — all parametrizations pass.

- [ ] 7. Prove drop-a-new-strategy is zero-code (TDD, T-DROP, north-star AC-N1).
      Add `tests/test_drop_strategy_zero_code.py`. In `tmp_path`, build a minimal copy of the plugins
      tree: a `strategies/` folder plus the five position folders (`gk/def/mid/fwd1/fwd2`), each with
      the three existing strategy bodies, then drop a BRAND-NEW strategy: `strategies/<new>.md` with
      valid frontmatter (`name/type: strategy/formation/description`) and `<pos>/<new>.md` for all five
      positions. `monkeypatch.setattr` BOTH `registry.PLUGINS_DIR` AND `plugin_loader._PLUGINS_ROOT`
      to the tmp tree (clear any registry cache if one exists). Then assert, through the runtime entry
      points (NOT `registry.discover(dir)` directly): (a) `plugin_loader.strategy_names()` includes
      `<new>` (planner-selectable), and (b) `plugin_loader.load_skill_prompt("<new>", label, pid)`
      loads the new body for every one of the five position labels. Zero Python edited to add `<new>`.
      Files: `tests/test_drop_strategy_zero_code.py`
      Verify: `uv run pytest -q tests/test_drop_strategy_zero_code.py` — passes.

- [ ] 8. Update the e2e baseline to the new prompt structure, keeping all five guarantees (T-E2E, AC-R4).
      Edit `tests/test_e2e_tick.py` ONLY where the prompt structure changed. In
      `test_planner_is_state_aware_and_formation_resolves`, keep the direct
      `build_system_prompt("aggressive","FWD1",3)` call and its `"1-0-3"`, `"Formation"`, `"JSON array"`
      assertions (the wrapper routes through `build_static_base`, so they hold) and ADD a tool-catalog
      marker assertion (e.g. `"evaluate_shot" in prompt`). In the happy-path tick, keep the
      formation-in-prompt, tool-offered-AND-used, `limits == {"turns": MAX_TOOL_ITERATIONS}`, and
      single-valid-command assertions; the composed prompt now also contains a tool name — assert it.
      Leave the cap-stops-loop and timeout-fallback tests unchanged. Do not weaken any of the five
      guarantees (state-aware selection, formation in prompt, a tool used, exactly one VALID command,
      infinite-loop safety).
      Files: `tests/test_e2e_tick.py`
      Verify: `uv run pytest -q tests/test_e2e_tick.py` — all e2e tests pass with guarantees intact.

- [ ] 9. Guard the packaging / deploy contract (TDD, T-PKG, AC-R5).
      Add `tests/test_deploy_contract.py` (import `deploy_all` as a module — its `main()` is guarded by
      `__main__`, so import is side-effect-free). Assert: `src/governance/tool_catalog.md` exists;
      the staged set in `deploy_all` includes `"governance"` (so the new file ships) — assert on the
      literal tuple used in `cleanup()`/`main()` staging, i.e. `"governance"` is among the staged
      folder names; and `deploy_all.SHARED_MODULES` equals the current five
      (`constants.py, planner.py, plugin_loader.py, unified_agent.py, runtime_guards.py`) so a future
      new `players/` module is caught by this guard. This plan adds NO new `players/` module, so no
      `SHARED_MODULES` edit is expected.
      Files: `tests/test_deploy_contract.py`
      Verify: `uv run pytest -q tests/test_deploy_contract.py` — passes.

- [ ] 10. Update the per-tick workflow document to match the implemented code (AC-C1/AC-C2/AC-X1).
      UPDATE (do not duplicate) `docs/per-tick-workflow.md`: replace the single-step
      `build_system_prompt` box with the static/dynamic split — guardrails + `tool_catalog.md` built
      ONCE at `register()` and cached, then the chosen strategy body appended per tick via
      `compose_tick_prompt`. Describe the controlled sequence: receive state → resolve position from
      agentId → PHASE 1 confirm/parse strategy (with the logged default-coercion guard) → PHASE 2
      consult this position's skill content → PHASE 3 controlled-ReAct tactical-tool consultation →
      single validated command. State the settled calculation decision (the four MCP tactical tools
      ONLY; explicitly NO code interpreter / code execution), the markdown-only tuning promise
      (drop-a-folder adds a strategy with zero code; improving tactics is a `.md` edit), and WHERE the
      `3.5s` wall-clock timeout and `2`-iteration cap apply. Add a line that the document must be kept
      accurate to the implemented code. Update the mermaid flow to show the two-layer prompt (cached
      static base + per-tick strategy body) and the PHASE 1/2/3 gate.
      Files: `docs/per-tick-workflow.md`
      Verify: manual read-through for accuracy against items 1–9; `uv run pytest -q` still green
      (doc change does not affect tests, but confirm no accidental code edit).

- [ ] 11. Optional markdown-only reinforcement of skill bodies (ONLY if cheap; NOT required).
      This is explicitly optional per design §6/AC-N3 — the static catalog is the SUFFICIENT driver of
      decide-with-facts and no test depends on per-body tool wording. If done, soften blind-action
      wording in `src/plugins/<pos>/<strategy>.md` toward tool-first (e.g. `fwd1/aggressive.md`
      "always shoot with maximum power" → "call `evaluate_shot` first, then shoot if it's worth it").
      Make NO behavioral/code change and do NOT make any new strategy require tool wording. Skip this
      item entirely if time-constrained.
      Files: `src/plugins/<gk|def|mid|fwd1|fwd2>/<aggressive|balanced|defensive>.md` (optional subset)
      Verify: `uv run pytest -q` — still green (markdown-only, no test should break).

- [ ] 12. Full-suite regression gate (AC-R1..R5, north-star).
      Run the entire suite from the worktree root and confirm the baseline grew by exactly the new
      tests with ZERO regressions: the 134 existing tests plus the new files (T-STATIC/T-CAT/T-DYNAMIC
      in `test_plugin_loader_static.py`, T-ORDER/T-TOOL/T-STATIC-b in `test_unified_agent_phases.py`,
      T-ROUTE, T-DROP, T-PKG). Confirm the do-not-regress invariants still hold via the tests:
      `TICK_TIMEOUT_SECONDS=3.5` timeout→fallback, `MAX_TOOL_ITERATIONS=2` cap, `PER_TOOL_TIMEOUT_SECONDS=1.0`,
      retries-off, 3-layer fallback, no infinite loop. Remove any scratch/temp files created during
      development (nothing left under `src/` or the repo root).
      Files: (none — verification only)
      Verify: `uv run pytest -q` from the worktree root — all green, count = 134 + the new tests, and
      `git status` shows only the intended files changed (tool_catalog.md, plugin_loader.py,
      unified_agent.py, the new/updated test files, per-tick-workflow.md, and any optional item-11 md).

---

## Notes for the implementer

- Build-state invariant: every item leaves the suite green. Items 2–3 touch only the loader
  (wrapper keeps old callers working); item 4 is the one that changes `invoke()` flow and is gated by
  both the new phase tests and the existing invoke-guard tests.
- Do NOT edit: `src/agents/players/agentcore/cdk/` (entire tree), `node_modules/`, `agentcore.json`,
  the `Makefile`, `.env`, `ai-team-strands-balanced/`, `sample-ai-possibilities/`. Extend only our code.
- No new dependency and no code-interpreter/code-execution surface (AC-X1). Only the existing four MCP
  tactical tools do probability/advantage math.
- No new module under `src/agents/players/` is introduced, so `deploy_all.py SHARED_MODULES` is NOT
  edited; item 9 guards that this stays true. If any future edit DOES add such a module, it must be
  added to `SHARED_MODULES` in the SAME change or the deployed bundle crashes with ModuleNotFoundError.
- Markdown single-tuning-surface promise (north-star): adding a strategy stays drop-a-folder
  (`strategies/<name>.md` + five `<pos>/<name>.md`), proven by item 7; tool-awareness tuning is the
  single `tool_catalog.md` file, proven by items 2 and 5.
