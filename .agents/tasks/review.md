# Review — refactor/plugins-by-position (commit 294ba7c)

Base: ef28ac6 → HEAD: 294ba7c. Reviewed the diff, the relocated files, the planner
(unchanged), plugin_loader, registry, discover_strategy, the touched tests, and the
coder's recorded verification. One narrow spot-check was run (see Gate 5).

**Verdict: APPROVED.** All six gates pass with no blocking findings.

## Gate 1 — Suite GREEN, baseline preserved, no test deleted
- Commit evidence: `uv run pytest -q -> 110 passed in 2.44s`. This is the 108 baseline
  + 2 deliberate new tests:
  - `tests/test_registry.py::test_position_indexes_are_not_strategies`
  - `tests/test_plugin_loader.py::test_mid_aggressive_loads_position_file_and_composes_prompt`
- The three touched test files (`test_discover_strategy.py`, `test_registry.py`,
  `test_plugin_loader.py`) show only path/type updates to match the new layout plus the
  two additive tests. No test function was removed to make the suite pass. The e2e file
  was not touched at all.
- Per instructions the suite was not re-run; the recorded summary is accepted.

## Gate 2 — e2e_tick guarantees intact
`tests/test_e2e_tick.py` is unchanged by this diff and is layout-agnostic: it reaches
the runtime through the real planner + plugin_loader + unified_agent and reads strategy
names/descriptions/formation from the registry-discovered set, not from any hard-coded
path. Its five guarantees still hold against the new layout:
1. State-aware selection — `select_strategy(losing_late)=="aggressive"`,
   `select_strategy(winning_late)=="defensive"` via the real planner.
2. Formation in the prompt — `build_system_prompt("aggressive","FWD1",3)` carries
   `1-0-3` and a `Formation` line (verified independently in Gate 5).
3. A tactical tool is used (fake tool `.calls >= 1`).
4. Exactly one valid, correctly-tagged command.
5. Infinite-loop safety — tool-iteration cap (`MAX_TOOL_ITERATIONS`) and the wall-clock
   timeout fallback.
Since the API these tests consume (`strategy_names`, `strategy_descriptions`,
`build_system_prompt`, `planner.select_strategy`) is preserved, the GREEN run covers them.

## Gate 3 — By-position layout correct
`git ls-tree 294ba7c -- src/plugins` confirms:
- Each of `gk/ def/ mid/ fwd1/ fwd2/` has `skill.md` + `aggressive.md` + `balanced.md`
  + `defensive.md`.
- The 15 position bodies are **R100 renames** (`git diff -M --name-status`): byte-for-byte
  identical to the originals, preserving `{player_id}`/`{formation}` tokens and the
  `## Formation posture` sections (spot-verified in def/balanced, fwd2/defensive,
  gk/aggressive, mid/aggressive).
- Old `src/plugins/{aggressive,balanced,defensive}/` strategy folders (incl. their
  `skill.md`) are gone.
- `src/plugins/general/` is UNCHANGED (empty diff for that path).

## Gate 4 — Team-coordinated selection preserved
- `planner.py` has an **empty diff** — one team strategy per tick, no per-agent autonomy.
- Strategy metadata relocated to `src/plugins/strategies/{aggressive,balanced,defensive}.md`
  with `type: strategy`; name/formation/description copied verbatim from the old skill.md
  (confirmed against `git show ef28ac6`). Bindings correct: aggressive 1-0-3, balanced
  1-2-1, defensive 3-0-1.
- `registry.discover()` reads `strategies/*.md` individually; `registry.strategies()`
  filters `type == "strategy"`, so the five `type: position` indexes and the `type:
  scripts` general plugin are excluded.
- `planner.select_strategy` scoreline/clock behavior unchanged; longest-match-first via
  `_parse_choice` (sorted by length desc) preserved; discovered set threaded through
  `known`.

## Gate 5 — plugin_loader load path
- `build_system_prompt` still prefixes `governance/guardrails.md` via `load_guardrails()`
  (`guardrails + "\n\n---\n\n" + skill`) and substitutes `{player_id}`/`{formation}`.
- `load_skill_prompt` resolves bodies from `_PLUGINS_ROOT/<position>/<strategy>.md`
  (NOT `meta.path`, which now points at `strategies/`); unknown position → `mid`,
  unknown strategy → `DEFAULT_STRATEGY` + `DEFAULT_FORMATION`. `_PLUGINS_ROOT` is derived
  from `_SRC_ROOT` so it resolves both locally and in the staged bundle.
- mid+aggressive proof present in the commit evidence (LOCAL OK + STAGED OK).
- **Spot-check run** (`uv run python`, this worktree):
  `build_system_prompt("aggressive","MID",2)` → guardrails `JSON array` present=True,
  `1-0-3` present=True, no leftover `{formation}`/`{player_id}`=True;
  `strategy_names()` → `['aggressive','balanced','defensive']`. Matches the evidence.

## Gate 6 — No forbidden edits
`git diff --name-only ef28ac6 294ba7c` filtered for forbidden paths returns EMPTY. No
edits under `src/agents/players/agentcore/cdk/`, `node_modules/`, `agentcore.json`,
`ai-team-strands-balanced/`, `sample-ai-possibilities/`, `src/plugins/general/`,
`Makefile`, or `.env`. The changed set is confined to `.agents/tasks/`,
`src/agents/players/{discover_strategy,plugin_loader}.py`, `src/plugins/**`, `tests/**`.

## discover_strategy consistency (supporting check)
`generate()` now writes `strategies/<name>.md` + `<pos>/<name>.md` for all five positions,
staged-then-moved on full success; frontmatter must be `type: strategy`; validation surface
(`REQUIRED_FILES` = metadata + 5 bodies, collision, name safety, content safety) preserved;
still off the tick path. Matches metadata-design §1/§4 and plan.

## Findings
None blocking.
