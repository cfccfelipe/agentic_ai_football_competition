---
inclusion: always
---

# Workshop — Core Context (always loaded, keep this short)

Unified AI football team: 5 agents (0=GK, 1=DEF, 2=MID, 3=FWD1, 4=FWD2) that pick a
strategy per tick and call deterministic MCP tools. Our code lives under
`src/agents/players/`, `src/commons/` (shared runtime kernel), `src/plugins/`,
`src/mcp_server/`, `src/governance/`, and `tests/`.

## Do Not Touch
- `ai-team-strands-balanced/` (repo root) belongs to a teammate — never edit/move/delete.
- `sample-ai-possibilities/` is upstream sample code — reference only, never modify.

## Temp files / scratch output — never leave them in the repo
- Do NOT write logs, command dumps, probe output, or scratch files anywhere under the
  repo. No `_tmp_*`, no `*.log`, no throwaway JSON/response files committed or left behind.
- Write scratch to the OS temp dir instead (`$env:TEMP` on Windows), or read the output
  inline and delete the file in the SAME step that created it. Leave the tree clean.
- This applies especially to CloudWatch/agentcore log captures: pull them to `$env:TEMP`,
  read, done. Nothing lands in `src/` or the repo root.

## Where the detailed rules live (loaded on demand)
- Writing/editing Python → `code-conventions.md` (TDD, uv, SOLID/DRY/YAGNI).
- Deploy / credentials / Makefile / .env → `deploy-ops.md`.
- Game rules, commands, model policy, tactical tools → `game-domain.md`.
- Delegation rule → `delegation.md`.
