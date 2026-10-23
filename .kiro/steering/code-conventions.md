---
inclusion: fileMatch
fileMatchPattern: '**/*.py'
---

# Code Conventions (loaded when editing Python)

## TDD (mandatory)
1. Write or update a test in `tests/` first (or alongside) — never ship logic without a test.
2. Tests live at the repo root under `tests/` and reuse fixtures from `tests/test_helpers.py`
   (`GAME_STATE`, `TEAM_ID`, `mock_agentcore*`).
3. Run with `uv run pytest`. Do not use bare `python` — this project uses `uv`.
4. Keep tests pure where possible (no AWS, no network). Inject dependencies (e.g. the
   planner's `agent_factory`) so logic is testable without live models.

## Tooling
- Use `uv` for everything local: `uv run pytest`, `uv run python ...`, `uv sync --group dev`.
- Local/dev dependencies live in the root `pyproject.toml` `[dependency-groups] dev`.
- Each deployed agent keeps its own `requirements.txt` — AgentCore's CodeZip build needs it.
  This is the deploy contract, not duplication to remove.

## Design Principles
- SOLID, DRY, YAGNI. The registry makes new strategies additive (drop a folder with a
  `skill.md` — no code change). Tool math is defined once; Lambda wrappers are thin adapters.
- Prompts emphasize knowing what the OTHER four players do, not just one's own role.

## Module map
```
src/agents/players/
  constants.py       # MODEL_ID + player→position map (single source of truth)
  planner.py         # chooses strategy from skill descriptions + game state
  plugin_loader.py   # guardrails + strategy/position prompt composition
  unified_agent.py   # shared factory + invoke handler (dynamic prompt per tick)
  gateway_tools/     # thin Lambda wrappers over the pure tool functions
src/commons/           # shared runtime kernel, staged into each agent at deploy
  parsing.py           # LLM response → validated commands
  json_tolerant.py     # recover Python-flavoured JSON before parsing
  state.py             # possession resolution + state summary for prompts
  fallback.py          # rule-based fallback config + last-resort command
  agent_base.py        # agent factory + invoke handler contract
  _bootstrap.py        # setup_commons_path(): wires commons/ onto sys.path
src/plugins/
  registry.py        # discovers plugins by scanning folders (no hard-coded names)
  general/scripts/   # the 4 tactical tools (pure functions)
  balanced|aggressive|defensive/   # skill.md + {gk,def,mid,fwd1,fwd2}.md
tests/                 # pytest suite + test_helpers.py (GAME_STATE, mocks)
```
