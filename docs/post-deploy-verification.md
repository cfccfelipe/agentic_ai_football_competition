# Post-Deploy Verification

Quick checks to confirm a redeploy actually fixed the runtimes and that the deploy was
**incremental** (same ARNs, new version). All commands are **read-only**. Credentials come
from the gitignored `.env` (the scripts/CLIs load them; see `deploy-ops.md`).

> Windows note: AWS/agentcore CLI output can be hard to capture in PowerShell. When a
> command's output doesn't show, redirect to the OS temp dir and read it back
> (`... 1> "$env:TEMP\out.txt" 2>&1; Get-Content "$env:TEMP\out.txt"`), then delete it.
> Never leave scratch files in the repo.

Known identifiers (from the current stack — update if a fresh deploy renames them):
- Stack: `AgentCore-TeamUnified-default`
- Region: `us-east-1`, Account: `937592087229`
- Runtimes: `TeamUnified_ai_{gk,def,mid,fwd1,fwd2}_agent-<suffix>`
- Gateway: `teamunified-tactical-tools-quw6ijaieq`
- GK log group: `/aws/bedrock-agentcore/runtimes/TeamUnified_ai_gk_agent-<suffix>-DEFAULT`

---

## 0. Before deploy — confirm the stack is HEALTHY (so the deploy is incremental)

```
aws cloudformation describe-stacks --stack-name AgentCore-TeamUnified-default \
  --region us-east-1 --query "Stacks[0].StackStatus" --output text
```

Expect `CREATE_COMPLETE` or `UPDATE_COMPLETE`. If it reads any `*_FAILED` / `ROLLBACK_*`,
STOP — `deploy_all.py`'s `pre_deploy_cleanup()` would delete it (a recreate, new ARNs).
Investigate before deploying.

---

## 1. Deploy

```
make deploy
```

Runs the test gate first (expect all green), then `deploy_all.py`: pre-deploy cleanup →
CDK bootstrap → stage shared code into each agent → `agentcore deploy`. Watch for the
final "Deploy complete: 5 runtimes + tactical-tools gateway".

---

## 2. Runtimes are READY

```
aws bedrock-agentcore-control list-agent-runtimes --region us-east-1 \
  --query "agentRuntimes[].{name:agentRuntimeName,status:status}" --output table
```

Expect all five `READY`. (The workshop `WSParticipantRole` CAN run this; it CANNOT run
`agentcore invoke`, which needs `GetAgentRuntime` the role lacks — that's why we verify via
logs, not invoke.)

---

## 3. THE key check — the bootstrap crash is gone

The whole reason the 5 agents returned `AGENT_RUNTIME_ERROR` was this at startup:

```
ModuleNotFoundError: No module named '_bootstrap'
```

After deploy, pull a runtime's recent logs and confirm that line is ABSENT from the newest
startup:

```
aws logs tail /aws/bedrock-agentcore/runtimes/TeamUnified_ai_gk_agent-<suffix>-DEFAULT \
  --region us-east-1 --since 10m --format short
```

- PASS: no `ModuleNotFoundError`, no `Traceback` at import; you see normal startup / an
  invoke log line like `GK agent: team 0, player 0, strategy <name>`.
- FAIL: the `_bootstrap` traceback still appears → the fix didn't ship (check the staged
  bundle actually contains `commons/` as a SIBLING of `unified_agent.py`).

Repeat for `def`/`mid`/`fwd1`/`fwd2` log groups if GK looks clean (they share the same code,
so GK passing is a strong signal all five pass).

---

## 4. Incremental deploy — same ARN, new version

Confirm the runtime identity was PRESERVED (not recreated) and a new version was published:

```
# ARN unchanged (compare against the ARN you had before this deploy)
aws bedrock-agentcore-control get-agent-runtime --region us-east-1 \
  --agent-runtime-id TeamUnified_ai_gk_agent-<suffix> --query "agentRuntimeArn" --output text
```

(Exact "list versions" verb depends on the installed CLI version; the intent is: same
`agentRuntimeId`/ARN, a newer version/endpoint than before. If the ARN suffix changed, the
deploy recreated instead of updating — investigate `pre_deploy_cleanup` and the stack status
from step 0.)

---

## 5. Gateway + tools still healthy (should be untouched by an agent-only change)

```
aws bedrock-agentcore-control list-gateway-targets --region us-east-1 \
  --gateway-identifier teamunified-tactical-tools-quw6ijaieq \
  --query "items[].{name:name,status:status}" --output table
```

Expect `evaluate-shot`, `calculate-pass-options`, `find-open-space`,
`get-defensive-assignment` all `READY`.

---

## 6. (If FEAT-004 guardrail shipped) guardrail wiring is safe

- If `BEDROCK_GUARDRAIL_ID` is unset in the runtime env, agents run WITHOUT a guardrail and
  the deploy must still succeed — this is the conditional/safe path.
- If set, a guardrail BLOCK on a tick must degrade to the rule-based fallback (never a crash);
  confirm via logs that a blocked tick logs the fallback, not a traceback.

---

## 7. End-to-end (only the game harness can do this)

`agentcore invoke` is blocked for the workshop role (`GetAgentRuntime` denied). True
end-to-end proof — agents returning one valid JSON command per tick, and the planner picking
different strategies by scoreline/clock — comes from running the actual game harness, or from
CloudWatch Transaction Search traces (~10 min after deploy to index). The deterministic
strategy-selection logic itself is already proven locally via `uv run pytest` (planner tests).
