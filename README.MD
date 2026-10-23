# Agentic AI Football Competition

Unified dynamic-skill AI football agents: one runtime per position (GK, DEF, MID,
FWD1, FWD2) that picks its strategy (balanced / aggressive / defensive) each tick
and uses deterministic MCP tactical tools.

## Setup

```bash
make setup
```

Leaves the machine ready to test and deploy. Idempotent — safe to re-run. It installs:

- **uv** + a Python 3.13 virtualenv + dev dependencies (pytest, mcp)
- **Node.js LTS** (needed by the deployment CLIs)
- **AgentCore CLI** (`@aws/agentcore`) and **AWS CDK** (`aws-cdk`) globally via npm

> **Windows note:** after Node.js installs for the first time, **reopen your terminal**
> so `node`/`npm` land on the PATH, then run `make setup` once more to finish the CLIs.

Check everything is in place:

```bash
make doctor
```

You also need the **AWS CLI** configured with valid credentials (`aws sts get-caller-identity`
should succeed) before deploying.

## Test

```bash
make test
```

Runs the full TDD suite (registry, plugin loader, planner, tactical tools). No AWS needed.

Run the local MCP server (exposes the 4 tactical tools over HTTP):

```bash
make test-mcp
```

## Deploy

```bash
make deploy
```

Runs the tests first (a red suite blocks the deploy), then deploys the 5 agents and the
tactical-tools gateway to AgentCore.

## Make targets

| Target | What it does |
|---|---|
| `make setup` | Full setup: Python + Node + deployment CLIs |
| `make doctor` | Verify every required tool is on PATH |
| `make test` | Run the test suite |
| `make test-mcp` | Start the local MCP tactical-tools server |
| `make deploy` | Run tests, then deploy agents + gateway |

## Project layout

```
src/
├── governance/guardrails.md     # Fixed game rules, injected into every prompt
├── plugins/
│   ├── registry.py              # Discovers plugins by scanning folders
│   ├── general/                 # The 4 tactical tools (pure functions) + skill.md
│   └── balanced|aggressive|defensive/   # skill.md + one prompt per position
├── mcp_server/server.py         # Local FastMCP server for the tools
└── agents/players/
    ├── constants.py             # MODEL_ID (Nova Micro) + player→position map
    ├── planner.py               # Chooses the strategy each tick
    ├── plugin_loader.py         # Builds the system prompt (guardrails + strategy)
    ├── unified_agent.py         # Shared factory + invoke handler
    ├── deploy_all.py            # Stages shared code and deploys
    └── ai-{gk,def,mid,fwd1,fwd2}/   # Thin entry points, one per position

tests/                           # TDD suite (run with `make test`)
docs/                            # game-rules.md + architecture docs
```

See `docs/game-rules.md` for the full rules and tactics, and
`docs/unified-agent-with-mcp-skills.md` for the architecture.
