# Unified Agent with Plugin Skills, MCP Gateway & Governance

**Date:** 2026-10-22
**Status:** Implemented. 24 unit tests passing; MCP server verified with 4 tools.

---

## Goal

Replace the 15 separate per-strategy agent files (5 positions × 3 strategies) with a single
unified runtime per position (5 total) that:

- loads strategy + position prompts dynamically from a **plugin** system,
- always prepends **fixed game guardrails**,
- lets the **agent itself pick the strategy** each tick by reading plugin descriptions and game state,
- calls deterministic **MCP tactical tools** via AgentCore Gateway,
- keeps the shared `lib/` kernel unchanged.

---

## Findings that shaped the design

- The only real difference between balanced/aggressive/defensive was the `SYSTEM_PROMPT`
  string. Fallback configs were identical across strategies. So strategy is prompt data,
  not code — it belongs in `.md` files, not Python branches.
- `lib/agent_base.py` already honored `myPlayers` to pick the effective player id, so a
  single runtime serving a position was already feasible.
- `ai-team-strands-gateway` proved the full MCP path (`MCPClient` + `streamablehttp_client`,
  gateway declared in `agentcore.json`, Lambda tools). We reuse that pattern.
- AWS lab permissions confirmed: `lambda:CreateFunction` and AgentCore Gateway create/list
  both succeed — the gateway variant is deployable here.
- The installed `mcp` is 2.x (FastMCP → MCPServer). The local server pins `mcp<2` to keep
  the FastMCP API; deployed Lambda tools don't use FastMCP at all.

---

## Architecture (as built)

```
src/
├── governance/
│   └── guardrails.md              # Fixed rules — injected into EVERY system prompt
├── plugins/
│   ├── registry.py                # Discovers plugins by scanning folders + reading skill.md frontmatter
│   ├── general/
│   │   ├── skill.md               # Declares the 4 tools + when to call them
│   │   └── scripts/               # Pure tool functions (no AWS, no Lambda wrapper)
│   │       ├── calculate_pass_options.py
│   │       ├── evaluate_shot.py
│   │       ├── find_open_space.py
│   │       └── get_defensive_assignment.py
│   ├── balanced/   skill.md + gk/def/mid/fwd1/fwd2.md
│   ├── aggressive/ skill.md + gk/def/mid/fwd1/fwd2.md
│   └── defensive/  skill.md + gk/def/mid/fwd1/fwd2.md
├── mcp_server/
│   └── server.py                  # Local FastMCP (streamable-http) exposing the 4 tools
└── agents/players/
    ├── constants.py               # MODEL_ID (Nova Micro) + player→position map + DEFAULT_STRATEGY
    ├── planner.py                 # select_strategy(): LLM reads descriptions+state, rule-based fallback
    ├── plugin_loader.py           # build_system_prompt() = guardrails + strategy/position prompt
    ├── unified_agent.py           # register(app, player_id): shared factory + invoke handler
    ├── gateway_tools/             # Thin Lambda wrappers delegating to the pure functions
    ├── agentcore/agentcore.json   # 5 runtimes + tactical-tools gateway (4 Lambda targets)
    ├── deploy_all.py              # Stages lib/plugins/governance/modules, deploys, cleans up
    └── ai-{gk,def,mid,fwd1,fwd2}/
        ├── src/main.py            # Thin entry: sets MY_PLAYER_ID, calls unified_agent.register
        └── requirements.txt       # AgentCore deploy contract

tests/                             # TDD — test_registry, test_plugin_loader, test_planner, test_mcp_tools
.kiro/steering/football-workshop.md  # Always-on context (rules, tooling, model policy)
docs/game-rules.md                 # Team-facing wiki
pyproject.toml                     # uv dev group (pytest, mcp<2) + pytest config
```

---

## Per-tick flow

```
AgentCore tick → ai-fwd1/src/main.py → unified_agent.invoke()
  1. parse payload: teamId, myPlayers, gameState, strategy hint (default "auto")
  2. effective player id → position label (constants.position_for)
  3. planner.select_strategy(state, team, descriptions, hint)
        hint != auto → use it; else LLM reads descriptions + score/time
        LLM unavailable/invalid → rule-based (losing late→aggressive, winning late→defensive, else balanced)
  4. plugin_loader.build_system_prompt(strategy, position, pid)
        = governance/guardrails.md  +  plugins/<strategy>/<position>.md  ({player_id} resolved)
  5. Agent(Nova Micro, system_prompt, tools=cached MCP tools)
  6. agent(summarize_state(...))  → tools called as needed
  7. parse_commands → yield JSON  (fallback_fn → last_resort on failure)
```

The Strands `Agent` is rebuilt per tick with the fresh prompt; MCP tools are fetched once at
startup and reused. If no gateway URL is set, the agent runs tool-less (degrades gracefully).

---

## Design principles applied

- **SRP** — registry discovers; plugin_loader composes; planner decides; unified_agent orchestrates.
- **OCP** — a new strategy is a new folder with a `skill.md`; `registry.discover()` picks it up
  with zero code change.
- **DRY** — tool math lives once in `plugins/general/scripts/`; the Lambda `gateway_tools/`
  wrappers are thin adapters staged over the same functions at deploy time. Guardrails exist once.
- **YAGNI** — the registry has no versioning/priority/hot-reload; the planner starts rule-first
  with an optional LLM. Memory (STM) is noted as a future extension, not built.

## Model policy

Nova Micro (`us.amazon.nova-micro-v1:0`) for every agent and the planner until capacity for
larger models is confirmed. Single source of truth: `src/agents/players/constants.py`.

## Verification status

- `uv run pytest` → 24 passed (registry, plugin_loader, planner, mcp_tools).
- MCP server imports and lists all 4 tools.
- Deploy (`deploy_all.py`) wired but not yet run against AWS — pending a live deploy.
