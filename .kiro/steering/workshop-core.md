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
## Our runtimes are ALWAYS `TeamUnified_ai_*` (shared account)
The workshop AWS account (937592087229) is SHARED with other participants. OUR 5 agent
runtimes are always named with the `TeamUnified_ai_` prefix (`TeamUnified_ai_gk_agent-*`,
`TeamUnified_ai_def_agent-*`, etc.). Bare `ai_*` runtimes (e.g. `ai_gk_agent-MPug56HQgi`)
belong to OTHER teams — never inspect, invoke, redeploy, or reason about them as ours. When
listing runtimes, log groups, versions, or endpoints, ALWAYS filter to the
`TeamUnified_ai_*` prefix. `make observability` already filters to it.

## Reuse what they give us; extend on top — never modify the given package
The guiding principle for everything built on the workshop stack: **REUSE the vendored
package as-is, EXTEND it with our own code.** The given package is a stable dependency we
consume, never something we fork or edit.
- **Reuse (consume as-is):** the vended `@aws/agentcore-cdk` L3 constructs
  (`AgentCoreApplication`, `AgentCoreMcp`, …, anything under `node_modules/`), the
  `agentcore.json` contract/schema, Bedrock AgentCore primitives, and the Strands/MCP
  libraries. Read and call them; do not alter them.
- **Extend (our code, on top):** our agents, `src/commons/`, `src/plugins/` (including
  registry-discovered drop-a-folder strategies), `src/governance/`, `deploy_all.py` /
  `destroy_all.py` and our own helper scripts. New capability is an additive extension in
  OUR code, not a patch to the given package.
- **Forbidden — the entire `cdk/` folder is OFF-LIMITS.** Do NOT edit ANYTHING under
  `src/agents/players/agentcore/cdk/` (that includes `lib/cdk-stack.ts`, `bin/cdk.ts`,
  `cdk.json`, `package.json`, tests) — the whole CDK tree is part of the GIVEN workshop
  package. Also forbidden: anything under `node_modules/`, forking/patching the vended CDK,
  and the `agentcore.json` schema/contract. Reading these is fine; editing them is not.
- **Consequence for new AWS resources (e.g. a Bedrock Guardrail):** since we cannot add
  resources through `cdk/`, create them from OUR OWN code instead — boto3/AWS CLI in
  `deploy_all.py` or a dedicated helper script, gated behind a flag, with ids passed to the
  runtimes via the `.env` env-var mechanism. If a feature truly cannot be built without
  editing `cdk/` or the given package, STOP and raise it rather than touching them.

## Autonomy — act, don't ask (this workspace)
- The user has authorized acting without step-by-step approval in this workspace. Proceed
  directly: commits, pushes, deploys, verification commands, resuming/merging workflows,
  applying fixes — just do them and report what happened.
- Do NOT stop to ask "should I proceed?" for routine work. Only pause for genuinely
  destructive/irreversible actions with broad blast radius (deleting live infra, force-push,
  dropping data, tearing down the stack) — and even then, state the plan and do it unless the
  user objects, rather than blocking on a question.
- Keep the user informed by reporting what was done, not by asking permission first.

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
