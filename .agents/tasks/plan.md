# Implementation Plan — plugins-by-position refactor

Reorganize strategy plugins FROM grouped-by-strategy (`src/plugins/{aggressive,balanced,defensive}/`)
TO grouped-by-position (`src/plugins/{gk,def,mid,fwd1,fwd2}/`), with strategy metadata relocated
to `src/plugins/strategies/` per `.agents/tasks/metadata-design.md`. Team-coordinated strategy
selection is UNCHANGED: the planner still picks ONE team strategy per tick for all five agents
(not per-agent-autonomous — that would break anti-ball-magnet coordination in
governance/guardrails.md). This is a file-layout + load-path change only.

Work entirely inside the worktree
`c:\Users\FelipeCortes\agentic_ai_football_competition\.worktrees\plugins-by-position`.
All `uv run pytest` commands run from that worktree root. TDD: update/add the test for a step
before or alongside the code, and keep the suite green (108 tests today) at every step.

Design decisions already fixed by `metadata-design.md` and honored here (do not re-decide):
- Strategy metadata lives in `src/plugins/strategies/<name>.md` as a one-frontmatter-block file
  with keys `name` / `type: strategy` / `formation` / `description` (description VERBATIM from the
  old strategy `skill.md`).
- The registry distinguishes strategy-metadata files by `type == "strategy"`; position index files
  use `type: position`; `general/` stays `type: scripts`.
- `plugin_loader.build_system_prompt(strategy, position_label, player_id)` keeps its signature;
  position prose resolves from `src/plugins/<position_label.lower()>/<strategy>.md`, formation
  comes from the strategy metadata, guardrails still prefix every prompt.

HARD constraints — do NOT touch: `src/agents/players/agentcore/cdk/` (entire folder), `node_modules/`,
`agentcore.json`, `ai-team-strands-balanced/`, `sample-ai-possibilities/`, `src/plugins/general/`,
the `Makefile`, and `.env`. `deploy_all.py` stages all of `src/plugins/` via `shutil.copytree` as
`plugins/` — the new subfolders ride along with NO edit to `deploy_all.py` (verified: it copies the
directory wholesale, not per-folder).

---

- [ ] 1. Create the relocated strategy-metadata folder `src/plugins/strategies/` with one file per
      strategy carrying ONLY frontmatter (no position prose). Copy each `name` / `formation` /
      `description` VERBATIM from the matching old `src/plugins/<name>/skill.md`, changing only the
      discriminator to `type: strategy`. Bindings: aggressive→1-0-3, balanced→1-2-1, defensive→3-0-1.
      Keep the folded `>` description scalar and flat `formation:` scalar exactly as the old files
      wrote them so the existing `_parse_frontmatter` and formation validation still apply.
      Files: `src/plugins/strategies/aggressive.md`, `src/plugins/strategies/balanced.md`,
      `src/plugins/strategies/defensive.md`
      Verify: `uv run python -c "import sys; sys.path.insert(0,'src'); from plugins import registry; print(sorted(registry.discover(registry.PLUGINS_DIR/'strategies')))"`
      prints the three names. (Full suite not yet green — registry still filters `type=='skill'`; fixed in step 3.)

- [ ] 2. Move each position-strategy file into its position folder, CONTENT BYTE-FOR-BYTE UNCHANGED
      (preserve `{player_id}` / `{formation}` tokens and the `## Formation posture` sections). Use
      `git -C <worktree> mv` so history follows the move. Exact mapping (all 15 files):
      `aggressive/gk.md`→`gk/aggressive.md`, `balanced/gk.md`→`gk/balanced.md`, `defensive/gk.md`→`gk/defensive.md`;
      `aggressive/def.md`→`def/aggressive.md`, `balanced/def.md`→`def/balanced.md`, `defensive/def.md`→`def/defensive.md`;
      `aggressive/mid.md`→`mid/aggressive.md`, `balanced/mid.md`→`mid/balanced.md`, `defensive/mid.md`→`mid/defensive.md`;
      `aggressive/fwd1.md`→`fwd1/aggressive.md`, `balanced/fwd1.md`→`fwd1/balanced.md`, `defensive/fwd1.md`→`fwd1/defensive.md`;
      `aggressive/fwd2.md`→`fwd2/aggressive.md`, `balanced/fwd2.md`→`fwd2/balanced.md`, `defensive/fwd2.md`→`fwd2/defensive.md`.
      Then delete the now-empty old strategy folders including their `skill.md`:
      `src/plugins/aggressive/`, `src/plugins/balanced/`, `src/plugins/defensive/`.
      Files: creates `src/plugins/{gk,def,mid,fwd1,fwd2}/{aggressive,balanced,defensive}.md`;
      removes `src/plugins/{aggressive,balanced,defensive}/` entirely.
      Verify: `git -C <worktree> status` shows 15 renames and the three skill.md deletions;
      `src/plugins/general/` is untouched. (Suite still red until steps 3-4.)

- [ ] 3. Create the five NEW per-position `skill.md` index files per design-note §3. Each uses
      `type: position` frontmatter (so the registry never treats it as a strategy or scripts), lists
      the three strategy files (`aggressive.md`, `balanced.md`, `defensive.md`) for that position with
      each strategy's formation stated next to it (aggressive→1-0-3, balanced→1-2-1, defensive→3-0-1),
      and gives when-to-use-which guidance mirrored from the OLD strategy `skill.md` descriptions,
      re-expressed for this position. The index MUST state that the authoritative team-strategy pick is
      made ONCE per tick by the planner and must NOT invite the agent to pick its own mode (per
      guardrails.md §5). No `{player_id}` / `{formation}` tokens — the index is navigation only, never
      loaded into the runtime prompt.
      Files: `src/plugins/gk/skill.md`, `src/plugins/def/skill.md`, `src/plugins/mid/skill.md`,
      `src/plugins/fwd1/skill.md`, `src/plugins/fwd2/skill.md`
      Verify: deferred to step 4's registry test (an index must NOT be discovered as a strategy).

- [ ] 4. Update `src/plugins/registry.py` so `strategies()` sources the strategy set from the
      `strategies/` metadata files instead of filtering `type == "skill"`. Change the `strategies()`
      filter to select `type == "strategy"` (which, with the new layout, are exactly the files under
      `strategies/`); `SkillMeta.type`'s docstring comment should note the `"strategy" | "position" |
      "scripts"` values. `discover()`, `_parse_frontmatter`, `_load_meta`, `strategy_descriptions()`,
      and `SkillMeta` keep their signatures — only the strategy filter changes. Each strategy's
      `SkillMeta.path` now points at `src/plugins/strategies/` (the metadata dir), NOT a position folder.
      Update `tests/test_registry.py`: `test_strategies_excludes_scripts` must still yield exactly
      `{balanced, aggressive, defensive}` and exclude `general` AND the five position indexes;
      `test_discovers_all_plugins` expectations adjust to the new folder set (general + strategies/ files
      + five position indexes are all discoverable, but only the three are strategies);
      `test_general_is_scripts_and_autoload`, `test_each_strategy_has_a_description`, and
      `test_strategy_descriptions_block_mentions_each` must still pass. Add a test asserting a
      `type: position` index is NOT returned by `strategies()`.
      Files: `src/plugins/registry.py`, `tests/test_registry.py`
      Verify: `uv run pytest -q tests/test_registry.py` — all registry tests pass.

- [ ] 5. Update `src/agents/players/plugin_loader.py` `load_skill_prompt` to the design-note §4
      load-path contract: look up strategy metadata from `registry.strategies()` (unknown → fall back
      to `DEFAULT_STRATEGY` + `DEFAULT_FORMATION`); resolve position prose from the POSITION folder
      `_SRC_ROOT/"plugins"/<position_label.lower()>/<strategy>.md` (NOT from `meta.path`, which now
      points at `strategies/`); if that file is missing, fall back to `plugins/mid/<strategy>.md`;
      formation still comes from `meta.formation`; `{player_id}` / `{formation}` substitution and the
      `build_system_prompt` guardrails-prefix are unchanged. Add a module-level plugins-root path
      (e.g. `_PLUGINS_ROOT = _SRC_ROOT / "plugins"`) so both local and staged layouts resolve
      identically. `tests/test_plugin_loader.py` assertions should all still hold as written
      (`test_unknown_strategy_falls_back_to_default`, `test_unknown_position_falls_back_to_mid`,
      `test_build_system_prompt_renders_formation_and_keeps_guardrails`, etc.); add an explicit test
      that `load_skill_prompt("aggressive", "MID", 2)` loads `plugins/mid/aggressive.md` and the
      composed `build_system_prompt` output contains the guardrails block and the `1-0-3` formation line.
      Files: `src/agents/players/plugin_loader.py`, `tests/test_plugin_loader.py`
      Verify: `uv run pytest -q tests/test_plugin_loader.py` — all loader tests pass, including the
      new mid+aggressive sample.

- [ ] 6. Confirm `src/agents/players/planner.py` and `src/agents/players/constants.py` need NO logic
      change (the planner consumes `strategy_descriptions()` + the discovered `known` set and is
      source-agnostic; `STRATEGIES`, `DEFAULT_STRATEGY`, `MODEL_ID`, `ALLOWED_FORMATIONS`,
      `DEFAULT_FORMATION` all stay intact). If any shared literal is genuinely clearer centralized in
      `constants.py`, move it there WITHOUT removing `MODEL_ID` or `ALLOWED_FORMATIONS`; otherwise leave
      both files unchanged. Run `tests/test_planner.py` to prove selection (hint pass-through,
      rule-based scoreline/clock, discovered-strategy pick, longest-match-first, timeout fallback) is
      unaffected.
      Files: `src/agents/players/planner.py`, `src/agents/players/constants.py` (likely no edit)
      Verify: `uv run pytest -q tests/test_planner.py` — all planner tests pass.

- [ ] 7. Update `src/agents/players/discover_strategy.py` so a newly discovered strategy writes the
      NEW layout: one `strategies/<name>.md` metadata file (frontmatter `name`/`type: strategy`/
      `formation`/`description`) PLUS the five position bodies written as `<position>/<name>.md`
      (`gk/<name>.md` … `fwd2/<name>.md`), staged to an OS-temp dir and moved into place ONLY on full
      success. Adjust `REQUIRED_FILES`/the `research` spec shape and the staged re-validation
      (`_load_meta` must now parse the staged `strategies/<name>.md` as `type == "strategy"`), and the
      collision/overlap/name-safety/content-safety validators keep working against the new file map.
      Keep it OFF the tick path (still never imported by `unified_agent`). Update
      `tests/test_discover_strategy.py`: `_good_files` / `_seed_existing` / `REQUIRED_FILES` expectations
      and `test_good_spec_is_written`'s written-file assertion move to the position-grouped output
      (metadata file + five position files); the rejection tests (missing file, empty description, bad
      formation, folded formation, name collision, substring overlap, override content, URL, invalid
      command token, missing response line, unsafe name, name mismatch) must all still reject with
      nothing written.
      Files: `src/agents/players/discover_strategy.py`, `tests/test_discover_strategy.py`
      Verify: `uv run pytest -q tests/test_discover_strategy.py` — all discovery tests pass; a
      generated strategy produces `strategies/<name>.md` + `<pos>/<name>.md` for all five positions.

- [ ] 8. Update `tests/test_e2e_tick.py` to the new layout and confirm the five-point tick guarantee
      holds end-to-end: (1) state-aware selection (losing-late→aggressive, winning-late→defensive) via
      the REAL registry-discovered set, (2) the chosen formation renders into the composed prompt
      (value in `ALLOWED_FORMATIONS`, `Formation` line present), (3) a tactical tool is offered and
      used, (4) exactly one valid command tagged with the right teamId/playerId, (5) infinite-loop
      safety (turns cap + wall-clock timeout fallback). Most assertions are layout-agnostic and should
      pass unchanged once steps 4-5 land; adjust only anything that referenced the old strategy-folder
      path.
      Files: `tests/test_e2e_tick.py`
      Verify: `uv run pytest -q tests/test_e2e_tick.py` — all e2e tick tests pass.

- [ ] 9. Full-suite regression + deploy-staging sanity. Run the whole suite from the worktree root and
      confirm it stays green at 108 tests (any net test-count change must be a deliberate add in steps
      4/5/7, documented in the step, not a silent loss of coverage). Then prove the staged layout
      resolves by simulating the deploy copytree into a temp dir and loading a prompt from it:
      copy `src/plugins` and `src/governance` into an OS-temp dir and run `plugin_loader`-style
      resolution of `mid/aggressive.md` against that copied tree, asserting the composed prompt still
      contains the guardrails block and the `1-0-3` formation line. Do NOT edit `deploy_all.py`,
      `Makefile`, or `.env`. Clean up the temp dir in the same step.
      Files: none (verification only)
      Verify: `uv run pytest -q` from the worktree root reports 108 passed (or the documented new
      total); the temp-dir staged-resolution check prints a prompt containing both `JSON array` /
      guardrails text and `1-0-3`.

---

## Exact move mapping (reference for step 2)

| From (grouped by strategy) | To (grouped by position) |
|---|---|
| `src/plugins/aggressive/gk.md`   | `src/plugins/gk/aggressive.md`   |
| `src/plugins/balanced/gk.md`     | `src/plugins/gk/balanced.md`     |
| `src/plugins/defensive/gk.md`    | `src/plugins/gk/defensive.md`    |
| `src/plugins/aggressive/def.md`  | `src/plugins/def/aggressive.md`  |
| `src/plugins/balanced/def.md`    | `src/plugins/def/balanced.md`    |
| `src/plugins/defensive/def.md`   | `src/plugins/def/defensive.md`   |
| `src/plugins/aggressive/mid.md`  | `src/plugins/mid/aggressive.md`  |
| `src/plugins/balanced/mid.md`    | `src/plugins/mid/balanced.md`    |
| `src/plugins/defensive/mid.md`   | `src/plugins/mid/defensive.md`   |
| `src/plugins/aggressive/fwd1.md` | `src/plugins/fwd1/aggressive.md` |
| `src/plugins/balanced/fwd1.md`   | `src/plugins/fwd1/balanced.md`   |
| `src/plugins/defensive/fwd1.md`  | `src/plugins/fwd1/defensive.md`  |
| `src/plugins/aggressive/fwd2.md` | `src/plugins/fwd2/aggressive.md` |
| `src/plugins/balanced/fwd2.md`   | `src/plugins/fwd2/balanced.md`   |
| `src/plugins/defensive/fwd2.md`  | `src/plugins/fwd2/defensive.md`  |

Strategy metadata extracted to `src/plugins/strategies/{aggressive,balanced,defensive}.md` (step 1);
old `src/plugins/{aggressive,balanced,defensive}/` folders (incl. their `skill.md`) removed (step 2).
`src/plugins/general/` is never touched.

## Final verification (whole task)

From `c:\Users\FelipeCortes\agentic_ai_football_competition\.worktrees\plugins-by-position`:

```
uv run pytest -q
```

Expect 108 passed (green), with every path-dependent test updated to the position-grouped layout and
the e2e tick guarantees intact.
