.PHONY: setup setup-python setup-node setup-cli setup-make test test-mcp deploy destroy monitoring doctor

# ─────────────────────────────────────────────────────────────────────────────
# PATH injection — GNU Make on Windows launches cmd.exe with a stripped PATH
# that misses per-user install dirs (uv, node, npm-global CLIs like agentcore/
# cdk). Prepend them here so every target below finds its tools without the
# caller having to export PATH first. Exported to all recipes.
# ─────────────────────────────────────────────────────────────────────────────
export PATH := $(USERPROFILE)\.local\bin;$(ProgramFiles)\nodejs;$(APPDATA)\npm;$(PATH)

# ─────────────────────────────────────────────────────────────────────────────
# Setup — leaves the machine ready to TEST and DEPLOY. Idempotent.
# Run once; after installing Node/CLIs the FIRST time, reopen your terminal so
# node/npm/agentcore/cdk land on PATH, then run `make setup` again to finish.
# ─────────────────────────────────────────────────────────────────────────────
setup: setup-python setup-node setup-cli
	@echo "Setup complete. Run 'make doctor' to verify, then 'make deploy'."

setup-python:
	where uv >nul 2>&1 || powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"
	uv venv --python 3.13 .venv --seed --allow-existing
	uv sync --group dev

setup-node:
	where node >nul 2>&1 || winget install -e --id OpenJS.NodeJS.LTS --accept-source-agreements --accept-package-agreements

setup-cli:
	where agentcore >nul 2>&1 || npm install -g @aws/agentcore
	where cdk >nul 2>&1 || npm install -g aws-cdk

# Optional: install GNU Make on Windows so these targets run natively.
setup-make:
	where make >nul 2>&1 || winget install -e --id GnuWin32.Make --accept-source-agreements --accept-package-agreements

doctor:
	@echo Checking required tools...
	@where uv        >nul 2>&1 && echo "  uv        OK" || echo "  uv        MISSING (make setup-python)"
	@where node      >nul 2>&1 && echo "  node      OK" || echo "  node      MISSING (make setup-node, then REOPEN terminal)"
	@where npm       >nul 2>&1 && echo "  npm       OK" || echo "  npm       MISSING (comes with node)"
	@where agentcore >nul 2>&1 && echo "  agentcore OK" || echo "  agentcore MISSING (make setup-cli)"
	@where cdk       >nul 2>&1 && echo "  cdk       OK" || echo "  cdk       MISSING (make setup-cli)"
	@where aws       >nul 2>&1 && echo "  aws       OK" || echo "  aws       MISSING (install AWS CLI + configure credentials)"

# ─────────────────────────────────────────────────────────────────────────────
# Day-to-day
# ─────────────────────────────────────────────────────────────────────────────

# Full TDD suite (registry, plugin_loader, planner, mcp_tools). No AWS needed.
test:
	uv run pytest -q

# Local MCP server exposing the 4 tactical tools. These tools do NOT read
# skills — skills are prompt files the agent reads at runtime.
test-mcp:
	uv run python src/mcp_server/server.py

# ─────────────────────────────────────────────────────────────────────────────
# Deployment — ONE command puts up EVERYTHING:
#   • 5 agent runtimes (GK/DEF/MID/FWD1/FWD2)
#   • the skill prompts (plugins/) — packaged inside each agent bundle
#   • the tactical-tools gateway + its 4 Lambda MCP tools
# deploy_all.py now auto-cleans any failed stack + orphaned log groups first,
# so re-running `make deploy` is always safe. Tests must pass before deploying.
# ─────────────────────────────────────────────────────────────────────────────
deploy: test
	uv run python src/agents/players/deploy_all.py

# Tears everything back down (runtimes + gateway + Lambda tools).
destroy:
	uv run python src/agents/players/destroy_all.py

# One-time per account/region: enable CloudWatch Transaction Search so agent
# traces/spans become visible and searchable.
monitoring:
	uv run python src/observability/observability.py
