# Design Note — Where strategy-level metadata relocates (plugins-by-position refactor)

Decision only. No files moved, no code written here.

## The problem in one line

Today `registry.strategies()` discovers strategies by scanning `src/plugins/*/skill.md`
and keeping entries whose frontmatter `type == "skill"`, reading `name` / `formation` /
`description` from each. In the position-grouped layout the only `skill.md` files left are
per-POSITION index files (`gk/`, `def/`, `mid/`, `fwd1/`, `fwd2/`). If those stayed
`type: skill` the registry would discover five *positions* as if they were strategies —
breaking `select_strategy`, the planner's scoreline/clock logic, and
`test_strategies_excludes_scripts`. So strategy metadata (name + formation + description,
and the aggressive=1-0-3 / balanced=1-2-1 / defensive=3-0-1 bindings) needs a NEW home that
the registry/planner can read, independent of any position folder.

## 1. Chosen relocation mechanism — a `strategies/` folder of per-strategy frontmatter files

Create `src/plugins/strategies/` containing one small markdown file per strategy, each
carrying only frontmatter (no position prose):

```
src/plugins/strategies/aggressive.md   # name: aggressive, type: strategy, formation: 1-0-3, description: >...
src/plugins/strategies/balanced.md     # name: balanced,   type: strategy, formation: 1-2-1, description: >...
src/plugins/strategies/defensive.md    # name: defensive,  type: strategy, formation: 3-0-1, description: >...
```

Each file reuses the SAME frontmatter keys the old `src/plugins/<strategy>/skill.md`
carried (`name`, `formation`, `description`) with the `description` text preserved VERBATIM
(the scoreline/clock guidance the planner shows the LLM). The one change is the type
discriminator: `type: strategy` instead of `type: skill`, so discovery can distinguish a
strategy-metadata file from a position index.

The registry's `strategies()` filter changes from `type == "skill"` to recognizing the
strategy-metadata files (either by `type == "strategy"` or by directory membership in
`strategies/`); `discover()` keeps scanning but the strategy set is sourced from
`strategies/`. `strategy_descriptions()` and `strategy_names()` are unchanged in signature —
they just iterate the new source. `SkillMeta.path` for a strategy now points at
`src/plugins/strategies/` (the metadata dir), NOT at a position folder, because position
prose no longer lives with the strategy (see §4 for how the loader resolves prose).

### Why this option over the two alternatives

- **vs. a single `strategies.md` with multiple frontmatter sections:** the registry's
  `_parse_frontmatter` parses exactly ONE leading `--- ... ---` block per file; multi-section
  parsing would require rewriting the parser (more code, more risk) and would weaken the
  "drop a file = new strategy" additivity. Rejected.
- **vs. a constants-level table in `constants.py`:** moving name/formation/description into
  Python makes "add a strategy" a CODE change, violating the Open/Closed, drop-a-folder
  principle the registry docstring and `code-conventions.md` call out, and `constants.py`
  must stay free of a dependency on scanning. Rejected.
- **one-file-per-strategy wins on every criterion:**
  - (a) **Registry discovers strategies + metadata** — each file is one frontmatter block the
    existing `_parse_frontmatter` already handles; `formation` validation against
    `ALLOWED_FORMATIONS` is reused unchanged.
  - (b) **planner.select_strategy keeps the same scoreline/clock behavior** — the planner is
    untouched. It still consumes `strategy_descriptions()` text and `STRATEGIES`/discovered
    `known`; `rule_based_strategy` still keys off score diff + `gameTime`. Only the SOURCE of
    the descriptions text moved.
  - (c) **longest-match-first preserved** — `_parse_choice` and the discovered-set threading in
    `select_strategy` are untouched; `strategy_names()` still returns the full discovered set
    so `high_press_counter` / `defensive_press` substring handling keeps working.
  - (d) **add a strategy = additive** — drop `strategies/<new>.md` (metadata) + add
    `<new>.md` in each of the five position folders. No code change to add a strategy that
    reuses existing positions. `discover_strategy.py` keeps staging-then-move with the same
    validation surface (it already validates frontmatter + the five position bodies; its
    `REQUIRED_FILES`/output shape is adjusted to the new layout in a later step, out of scope
    for this note).
  - (e) **does NOT touch `src/plugins/general/`** — `general/skill.md` stays `type: scripts`,
    `auto_load: true`, discovered exactly as today. The new `type: strategy` discriminator
    leaves the scripts plugin's discovery untouched (`test_general_is_scripts_and_autoload`
    still holds).

## 2. Exact file-move mapping (content preserved VERBATIM)

Each strategy's five position files move into the matching position folder, renamed to the
strategy name. Content is copied byte-for-byte — including the `{player_id}` / `{formation}`
tokens and the recently-added `## Formation posture` sections.

| From (grouped by strategy)      | To (grouped by position)   |
|---------------------------------|----------------------------|
| `aggressive/gk.md`              | `gk/aggressive.md`         |
| `balanced/gk.md`                | `gk/balanced.md`           |
| `defensive/gk.md`               | `gk/defensive.md`          |
| `aggressive/def.md`             | `def/aggressive.md`        |
| `balanced/def.md`               | `def/balanced.md`          |
| `defensive/def.md`              | `def/defensive.md`         |
| `aggressive/mid.md`             | `mid/aggressive.md`        |
| `balanced/mid.md`               | `mid/balanced.md`          |
| `defensive/mid.md`              | `mid/defensive.md`         |
| `aggressive/fwd1.md`            | `fwd1/aggressive.md`       |
| `balanced/fwd1.md`              | `fwd1/balanced.md`         |
| `defensive/fwd1.md`             | `fwd1/defensive.md`        |
| `aggressive/fwd2.md`            | `fwd2/aggressive.md`       |
| `balanced/fwd2.md`              | `fwd2/balanced.md`         |
| `defensive/fwd2.md`             | `fwd2/defensive.md`        |

The old `aggressive/`, `balanced/`, `defensive/` folders (including their `skill.md`) are
removed once their position files have moved and the strategy metadata has been extracted to
`strategies/<name>.md` (§1). `general/` is untouched.

## 3. What each NEW per-position `skill.md` index contains

Five new index files: `gk/skill.md`, `def/skill.md`, `mid/skill.md`, `fwd1/skill.md`,
`fwd2/skill.md`. Each is an AGENT-FACING index that tells the agent which strategy file to
read for this position and under what conditions. Frontmatter uses a NON-strategy type so the
registry never mistakes a position index for a strategy — use `type: position` (anything
other than `skill`/`strategy`/`scripts`); `discover()` still parses it but neither
`strategies()` nor the scripts path picks it up.

Each position index must:

- **List the three strategy files for this position:** `aggressive.md`, `balanced.md`,
  `defensive.md`.
- **Give the when-to-use-which guidance,** mirroring the condition language from the OLD
  strategy `skill.md` `description` blocks, re-expressed for this position. (E.g. the
  aggressive condition "losing by 1+ with <~20 min left, losing by 2+ anytime, or level and
  time running out" from the old `aggressive/skill.md` description, phrased as "read
  `aggressive.md` when the team is chasing goals".) This is guidance only; the AUTHORITATIVE
  team-strategy pick is still made ONCE per tick by the planner — the index must not invite
  the agent to pick its own mode independently (that would reintroduce the anti-ball-magnet
  failure guardrails.md §5 forbids).
- **Keep each strategy's formation associated with the right strategy file:** state
  aggressive → 1-0-3, balanced → 1-2-1, defensive → 3-0-1 next to each listed file, so the
  index is self-consistent with the metadata in `strategies/`. (The formation that actually
  renders into the prompt still comes from `strategies/<strategy>.md`, not from the index —
  the index just documents the pairing for the human/agent reader.)

The position index is documentation/navigation; it is NOT loaded into the runtime prompt and
carries no `{player_id}`/`{formation}` tokens.

## 4. New load-path contract for `plugin_loader.build_system_prompt`

Signature is unchanged: `build_system_prompt(strategy, position_label, player_id)`.

New resolution inside `load_skill_prompt`:

1. Look up strategy metadata from the registry's strategy set (now sourced from
   `strategies/<strategy>.md`). Unknown strategy → fall back to `DEFAULT_STRATEGY`
   (`balanced`) and `DEFAULT_FORMATION`, exactly as today (keeps
   `test_unknown_strategy_falls_back_to_default` and `test_unknown_strategy_formation_defaults`
   green).
2. Resolve the position prose from the POSITION folder, not the strategy folder:
   `src/plugins/<position_label.lower()>/<strategy>.md`. If that file is missing, fall back to
   `src/plugins/mid/<strategy>.md` (preserves the "unknown position → MID" behavior in
   `test_unknown_position_falls_back_to_mid`). The loader must NOT key the position path off
   `SkillMeta.path` anymore, because a strategy's `path` now points at `strategies/`, not at a
   position folder.
3. `formation` still comes from the chosen strategy's metadata (`meta.formation`), so
   `{formation}` substitutes to 1-0-3 / 1-2-1 / 3-0-1 as before.
4. Substitution is unchanged: replace `{player_id}` and `{formation}` in the loaded template.
5. `build_system_prompt` still prefixes `governance/guardrails.md` via `load_guardrails()`:
   `guardrails + "\n\n---\n\n" + skill`. All `test_plugin_loader` / `test_e2e_tick`
   assertions ("Guardrails" before the separator, "JSON array" present, formation value in
   `ALLOWED_FORMATIONS`, `Formation` posture line present, no leftover `{...}` tokens) remain
   satisfied because the position prose and guardrails text are preserved verbatim.

### Deploy constraint (must hold both locally and when staged)

`deploy_all.py` copies `src/plugins/` into each agent bundle as `plugins/` (via
`shutil.copytree(PLUGINS_SRC, dest)`), and `src/governance/` as `governance/`. The loader
already resolves paths relative to `_SRC_ROOT` and the registry relative to
`PLUGINS_DIR = Path(__file__).parent`, so the position-grouped tree copies and resolves
identically in the staged layout — PROVIDED every path is computed from those roots and the
loader never hard-codes the old `plugins/<strategy>/<position>.md` shape. The new
`strategies/` folder and the five position folders are plain subdirectories of
`src/plugins/`, so they ride the existing copytree with no change to `deploy_all.py`. No edit
to `cdk/`, `node_modules/`, `agentcore.json`, or the vended package is required — this is a
pure OUR-code file-layout + loader-path change.

## Assumptions / gaps noted (not resolved here, this is design-only)

- `registry.py`, `plugin_loader.py`, `discover_strategy.py` (its `REQUIRED_FILES` and output
  shape), and their tests (`test_registry.py`, `test_plugin_loader.py`,
  `test_discover_strategy.py`, `test_e2e_tick.py`) will need corresponding edits in the
  implementation steps; this note only fixes WHERE metadata lives and the load-path contract.
- Exact frontmatter `type` token value (`strategy` / `position`) is a free choice above; the
  only hard requirement is that strategy-metadata files and position-index files use types
  DISTINCT from each other, from `scripts`, and that the strategy set no longer keys off
  `type: skill`.
