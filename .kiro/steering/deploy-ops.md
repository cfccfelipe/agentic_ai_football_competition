---
inclusion: fileMatch
fileMatchPattern: '**/{deploy_all,destroy_all}.py|Makefile|.env*|**/agentcore.json'
---

# Deploy & Ops (loaded when touching deploy, Makefile, or env)

## Credentials & terminals
- AWS credentials and workshop values live in the gitignored `.env` at the repo root.
  `deploy_all.py` loads them via `load_dotenv()` — do not re-export per terminal and do
  not spawn many short-lived terminals to probe the environment.
- Workshop credentials are temporary and expire fast — renew them in `.env` right before
  a deploy. The deploy takes longer than one credential window if started late.
- Prefer background processes for long-running work (deploys) and read their output.

## Make targets (the interface)
- `make setup` — uv + venv + dev deps + Node + agentcore/cdk CLIs (idempotent).
- `make doctor` — verify required tools are on PATH.
- `make test` — full pytest suite (gate before deploy).
- `make test-mcp` — local MCP tactical-tools server.
- `make deploy` — tests, then `deploy_all.py` (auto-cleans failed stack + log groups first).
- `make destroy` — tear down runtimes + gateway + Lambdas.
- `make monitoring` — one-time: enable CloudWatch Transaction Search.

## Deploy facts
- Runtime version is PYTHON_3_10; each agent bundle needs `pyproject.toml` + `requirements.txt`
  so the CodeZip build installs OTEL (else "OpenTelemetry instrumentation executable not found").
- `deploy_all.py` auto-deletes any ROLLBACK/FAILED stack and orphaned
  `/aws/lambda/TeamUnified-*` log groups before deploying, so re-running is safe.
- One deploy puts up everything (5 runtimes + gateway + 4 Lambda tools). Skills are packaged
  inside each agent bundle; there is no separate skills/MCP deploy.
- `deploy_all.py` stages the shared kernel `src/commons/` into each agent bundle as a folder
  named `commons` (alongside `plugins`, `governance`, the SHARED_MODULES, and a
  `requirements.txt`) — all FLAT at the bundle root (`/var/task/` at runtime). So in the
  deployed bundle `unified_agent.py` and `commons/` are SIBLINGS, not parent/child. Any
  path/bootstrap logic must resolve `commons` as a sibling (`./commons`), not `../commons`.
- **CRITICAL deploy contract — every runtime module in `src/agents/players/` that is
  imported at runtime MUST be listed in `deploy_all.py`'s `SHARED_MODULES`.** Only the files
  in that list are copied into each agent bundle. A NEW module (e.g. `runtime_guards.py` from
  the loop/timeout work) that is imported by `unified_agent.py`/`planner.py` but NOT added to
  `SHARED_MODULES` deploys a broken bundle: it passes all LOCAL tests (local resolves the
  whole `players/` dir) but crashes the deployed runtime at import with
  `ModuleNotFoundError: No module named '<that module>'`, which shows up as "Runtime
  initialization time exceeded" / a silent runtime. When you add a runtime module under
  `players/`, add it to `SHARED_MODULES` in the SAME change. Modules under `src/commons/` are
  fine — the whole `commons/` folder is staged. Current SHARED_MODULES: constants, planner,
  plugin_loader, unified_agent, runtime_guards.

## Deferred / tech debt (do NOT do mid-fix — pick up after the game is stable)
- **Move infra to its own folder.** `deploy_all.py`, `destroy_all.py`, and `agentcore/`
  (CDK) are infrastructure, not game logic, and arguably belong in `src/infra/` (or a
  top-level `infra/`). Deferred on purpose: `deploy_all.py` anchors everything off
  `SCRIPT_DIR = Path(__file__).parent` (the agent dirs `ai-*`, `gateway_tools/`,
  `requirements.txt`, and `agentcore/cdk/` are all its SIBLINGS in `src/agents/players/`),
  so a move must reajust SCRIPT_DIR/SRC_ROOT and every relative path, plus the Makefile
  target (`src/agents/players/deploy_all.py`) and `.github/workflows/ci.yml`. Do it as a
  dedicated, isolated refactor (like the lib→commons one), verified with a dry-run deploy —
  never in parallel with a workflow that is editing `deploy_all.py` or the CDK.
