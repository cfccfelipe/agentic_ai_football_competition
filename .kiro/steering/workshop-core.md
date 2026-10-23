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
## Reuse what they give us; extend on top — never modify the given package
The guiding principle for everything built on the workshop stack: **REUSE the vendored
package as-is, EXTEND it with our own code.** The given package is a stable dependency we
consume, never something we fork or edit.
- **Reuse (consume as-is):** the vended `@aws/agentcore-cdk` L3 constructs
  (`AgentCoreApplication`, `AgentCoreMcp`, …, anything under `node_modules/`), the
  `agentcore.json` contract/schema, Bedrock AgentCore primitives, and the Strands/MCP
  libraries. Read and call them; do not alter them.
- **Extend (our code, on top):** `src/agents/players/agentcore/cdk/lib/cdk-stack.ts` and
  `bin/cdk.ts` (our thin wrapper over the vended L3 — add resources here via the aws-cdk-lib
  CDK escape hatch, e.g. `CfnGuardrail`), our agents/plugins/commons, and anything the
  registry discovers by convention (drop-a-folder strategies). New capability is an
  additive extension, not a patch to the given package.
- **Forbidden:** editing anything under `node_modules/`, forking/patching the vended CDK,
  or adding bespoke fields to the `agentcore.json` schema. If a feature cannot be built by
  reusing + extending without altering the given package, STOP and raise it — do not modify
  what the workshop provided.

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
