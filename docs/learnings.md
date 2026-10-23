# Learnings

Hard-won lessons from building and deploying the unified AI football team. Each entry is a
real failure we hit and the rule that prevents it. Read before deploying or refactoring.

---

## 1. Every runtime module under `players/` MUST be in `deploy_all.py` `SHARED_MODULES`

**What broke:** The deployed runtime crashed at import with
`ModuleNotFoundError: No module named 'runtime_guards'`. The module existed in
`src/agents/players/runtime_guards.py` and all local tests passed, but it was never copied
into the agent bundle.

**Root cause:** `deploy_all.py` only stages the files listed in `SHARED_MODULES` into each
agent bundle. A new runtime module (`runtime_guards.py`, added for the loop/timeout guards)
was imported by `planner.py`/`unified_agent.py` but not added to that list, so the bundle
was missing it.

**Why local tests didn't catch it:** locally, the whole `players/` directory is on
`sys.path`, so every sibling import resolves. The gap only appears in the DEPLOYED bundle,
where only staged files exist.

**The rule:** when you add a runtime module under `src/agents/players/`, add it to
`SHARED_MODULES` in the SAME change. Modules under `src/commons/` are safe — the whole
`commons/` folder is staged as a unit. Current SHARED_MODULES: constants, planner,
plugin_loader, unified_agent, runtime_guards.

---

## 2. A missing bundle file shows up as "Runtime initialization time exceeded" / silent runtime

**What broke:** The console reported `Runtime initialization time exceeded. Please make sure
that initialization completes in 30s` with "No traces" / "tracing not enabled, no log group".
It looked like an observability or timeout problem.

**Root cause:** the real cause was an import crash at startup (see #1 and the earlier
`_bootstrap` crash). A runtime that dies during import never emits spans, so CloudWatch shows
empty `otel-rt-logs`/`spans` streams and the console says tracing isn't enabled. The
"init exceeded" message is a SYMPTOM, not the cause.

**The rule:** when a runtime is silent / "init exceeded" / "no traces", suspect a startup
import or bundling error FIRST. Pull the runtime's CloudWatch logs and look for a Python
traceback at import before touching observability config. Don't guess — get the logs.

---

## 3. `lib/` -> `commons/` rename: the deployed layout is FLAT (siblings), not nested

**What broke:** First deploy after the rename crashed with
`ModuleNotFoundError: No module named '_bootstrap'`.

**Root cause:** `deploy_all.py` stages `src/commons/` into each bundle as a folder named
`commons` at the bundle ROOT, next to `unified_agent.py`. So at runtime (`/var/task/`),
`unified_agent.py` and `commons/` are SIBLINGS. The bootstrap used `../commons`, which
resolves outside the bundle. Fix: resolve `./commons` (sibling) first, then the dev-layout
fallbacks. `setup_commons_path()` now tries `./commons`, `../commons`, `../../../commons`.

**The rule:** any path logic that must work both locally and deployed has to account for the
flat bundle layout. Add a test that simulates the bundle layout (commons as a sibling), not
just the local layout — a local-only test passes while the deploy breaks.

---

## 4. Runtime versions vs the DEFAULT endpoint — a new version doesn't auto-serve

**What we saw:** `make deploy` published a new runtime VERSION (same runtime ARN — the deploy
IS incremental and reuses ARNs, confirmed), but the agent kept serving an OLDER version's
code. A log line showing `/var/task/lib/agent_base.py` (old `lib/` path) on a runtime whose
latest version was already on `commons/` was the tell.

**The rule:** after a deploy, confirm WHICH version the DEFAULT endpoint actually serves, not
just that a new version exists and is READY. Verify from logs that the running code matches
the deploy (e.g. `commons/` not `lib/`, expected log lines). "READY" on a new version does
not mean the endpoint routes to it.

---

## 5. The workshop account is SHARED — not every runtime you see is ours

**What confused us:** `describe-log-groups` listed many runtimes with our naming
(`TeamUnified_ai_gk_agent-<suffix>`, `ai_gk_agent-<suffix>`) where some were SILENT/failing.
Several of those were OTHER participants' runtimes in the same shared account
(937592087229), not ours.

**The rule:** OUR runtimes are ALWAYS named `TeamUnified_ai_*` (e.g.
`TeamUnified_ai_gk_agent-rvBkVbGcoH`). Bare `ai_*` runtimes (e.g. `ai_gk_agent-MPug56HQgi`)
belong to OTHER participants — never inspect/invoke/redeploy them as ours. Always filter
listings to the `TeamUnified_ai_` prefix. `make observability` now does this automatically.
This confusion cost real time: an `ai_gk_agent-MPug56HQgi` (someone else's) was mistaken for
ours and its version/endpoint read as if it were our deploy.

---

## 6. The workshop IAM role can deploy + list, but CANNOT invoke

**What blocks us:** `WSParticipantRole/Participant` lacks `bedrock-agentcore:GetAgentRuntime`,
so `agentcore invoke` fails. The AWS CLI (2.31.x) has no `bedrock-agentcore` data-plane
service either. So we CANNOT invoke an agent end-to-end from this machine.

**The rule:** end-to-end validation comes from the game HARNESS (which runs with different
permissions) or from CloudWatch logs/traces of real sessions, NOT from invoking ourselves.
Local proof is the offline `tests/test_e2e_tick.py` baseline + unit tests. Don't burn time
trying to invoke from the CLI with the participant role.

---

## 7. Never modify the GIVEN workshop package

**The rule:** reuse what the workshop gives, extend on top. The ENTIRE `cdk/` folder
(`src/agents/players/agentcore/cdk/`), `node_modules/`, and the `agentcore.json` schema are
off-limits. New AWS resources (e.g. a Bedrock Guardrail) are created from OUR own code
(boto3 in `deploy_all.py` / a helper script), gated behind a flag — never by editing `cdk/`.
See the steering `workshop-core.md` for the full boundary.

---

## 8. Windows PowerShell mangles CLI output — redirect to a temp file

**What bit us repeatedly:** `agentcore`/`aws` (node + python CLIs) output doesn't reliably
show through PowerShell piping; `Out-String` sometimes returns empty. git/push also writes to
stderr, which PowerShell surfaces as a red "error" even on success.

**The rule:** for these CLIs, redirect to the OS temp dir and read the file back
(`cmd /c "... 1> `"$env:TEMP\out.txt`" 2>&1"` then read `$env:TEMP\out.txt`), and delete it
after. Never leave scratch in the repo. Treat a git stderr "error" as cosmetic if the
success line (`<old>..<new>  branch -> branch`) is present.
