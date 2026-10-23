#!/usr/bin/env python3
"""
Deploy the 5 unified AI football agents + tactical-tools gateway to AgentCore.

Usage:
    uv run python src/agents/players/deploy_all.py

The gateway and its 4 Lambda tactical tools are declared in
agentcore/agentcore.json and created by `agentcore deploy`. The gateway
endpoint is injected into every runtime as
AGENTCORE_GATEWAY_TACTICAL_TOOLS_URL.

Because the agents use the shared commons/, the plugins/, and the governance
guardrails, this script stages those into each agent directory before deploy
and removes them afterwards — the originals stay the single source of truth.

Prerequisites:
    npm install -g @aws/agentcore aws-cdk
    uv (https://docs.astral.sh/uv/)
    AWS credentials configured; CDK bootstrap (done automatically below).
"""

import json
import os
import stat
import sys
import shutil
import signal
import subprocess
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()          # src/agents/players
SRC_ROOT = SCRIPT_DIR.parents[1]                       # src/
REPO_ROOT = SCRIPT_DIR.parents[2]                      # repo root (holds .env)


def load_dotenv() -> None:
    """Load KEY=VALUE pairs from the repo-root .env into os.environ.

    Lets credentials live in one gitignored file instead of being re-exported
    per terminal. Existing environment values win, so an already-exported
    credential is never clobbered. Silently does nothing if .env is absent.
    """
    env_file = REPO_ROOT / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip('"').strip("'")
        # Skip unfilled placeholders like <access-key-id>.
        if value.startswith("<") and value.endswith(">"):
            continue
        os.environ.setdefault(key, value)


load_dotenv()
COMMONS_SRC = SRC_ROOT / "commons"
PLUGINS_SRC = SRC_ROOT / "plugins"
GOVERNANCE_SRC = SRC_ROOT / "governance"
SCRIPTS_SRC = PLUGINS_SRC / "general" / "scripts"      # pure tool functions
GATEWAY_TOOLS = SCRIPT_DIR / "gateway_tools"           # Lambda wrappers
REQUIREMENTS_SRC = SCRIPT_DIR / "requirements.txt"     # canonical runtime deps
SHARED_MODULES = [
    "constants.py", "planner.py", "plugin_loader.py", "unified_agent.py",
    "runtime_guards.py", "formation_roles.py",
]
ALL_AGENTS = ["ai-gk", "ai-def", "ai-mid", "ai-fwd1", "ai-fwd2"]

_injected: list[Path] = []
_impl_staged = False


def rmtree(path):
    def _onerror(func, p, exc_info):
        os.chmod(p, stat.S_IWRITE)
        func(p)
    shutil.rmtree(path, onerror=_onerror)


def cleanup():
    global _impl_staged
    for agent_dir in _injected:
        for name in ("commons", "plugins", "governance", "requirements.txt", *SHARED_MODULES):
            target = agent_dir / name
            if target.is_dir():
                rmtree(target)
            elif target.exists():
                target.unlink()
    impl = GATEWAY_TOOLS / "_impl"
    if _impl_staged and impl.is_dir():
        rmtree(impl)
        _impl_staged = False
    if _injected:
        print("\nCleaned up staged files from agent directories.")


def _signal_handler(sig, frame):
    print("\nInterrupted — cleaning up...")
    cleanup()
    sys.exit(1)


def resolve_exe(name):
    path = shutil.which(name)
    if path is None:
        print(f"ERROR: '{name}' not found on PATH.")
        sys.exit(1)
    return path


def run(cmd, **kwargs):
    cmd = [resolve_exe(cmd[0]), *cmd[1:]]
    print(f"  > {' '.join(str(c) for c in cmd)}")
    kwargs.setdefault("env", os.environ.copy())
    kwargs["env"].setdefault("PYTHONIOENCODING", "utf-8")
    subprocess.run(cmd, check=True, **kwargs)


def check_tool(name):
    try:
        subprocess.run([resolve_exe(name), "--version"], check=True, capture_output=True)
        print(f"  {name}: OK")
    except (FileNotFoundError, subprocess.CalledProcessError):
        print(f"ERROR: '{name}' not found or not working.")
        sys.exit(1)


def aws_cli(*args):
    result = subprocess.run(
        [resolve_exe("aws"), *args], capture_output=True, text=True, encoding="utf-8"
    )
    return result.stdout.strip() if result.returncode == 0 else None


def _ignore_pycache(*_):
    return shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo")


STACK_NAME = "AgentCore-TeamUnified-default"
LOG_GROUP_PREFIX = "/aws/lambda/TeamUnified-"

# Stack statuses that mean the stack is unusable for an in-place UPDATE and must
# be deleted (along with its orphaned log groups) before a fresh deploy. A stack
# in any *_COMPLETE success state, or any transient state, is left untouched.
_CLEANUP_STATUSES = (
    "ROLLBACK_COMPLETE", "ROLLBACK_FAILED", "CREATE_FAILED", "DELETE_FAILED",
)


def _should_cleanup(status: str | None) -> bool:
    """True only when the stack is in a failed state or absent.

    A healthy stack (CREATE_COMPLETE/UPDATE_COMPLETE) must be left for an
    in-place CloudFormation UPDATE — deleting it or its managed log groups would
    tear down the live runtime ARNs. ``None`` (no stack) is treated as needing
    cleanup so orphaned log groups from a prior deleted stack are swept.
    """
    return status is None or status in _CLEANUP_STATUSES


def pre_deploy_cleanup(region: str) -> None:
    """Make redeploys idempotent WITHOUT touching a healthy stack.

    A previous failed deploy can leave two things behind that block a fresh
    `agentcore deploy`:
      1. A CloudFormation stack stuck in e.g. ROLLBACK_COMPLETE (cannot be
         updated, only deleted).
      2. Orphaned Lambda log groups (/aws/lambda/TeamUnified-*) that
         CloudFormation refuses to recreate ("already exists").

    Both are removed ONLY when the stack is in a failed/absent state
    (``_should_cleanup``). A healthy stack is left entirely alone — including
    its managed log groups — so the deploy becomes an in-place UPDATE that keeps
    the same runtime ARNs and simply publishes a new version.
    """
    print("Pre-deploy cleanup (idempotent)...")

    status = aws_cli(
        "cloudformation", "describe-stacks", "--stack-name", STACK_NAME,
        "--region", region, "--query", "Stacks[0].StackStatus", "--output", "text",
    )

    if not _should_cleanup(status):
        print(f"  Stack status: {status} (healthy — left as-is for in-place update)")
        print()
        return

    if status:
        print(f"  Stack is {status}; deleting it before redeploy...")
        aws_cli("cloudformation", "delete-stack", "--stack-name", STACK_NAME, "--region", region)
        subprocess.run(
            [resolve_exe("aws"), "cloudformation", "wait", "stack-delete-complete",
             "--stack-name", STACK_NAME, "--region", region],
            capture_output=True, text=True, encoding="utf-8",
        )
        print("  Stack deleted.")

    # Orphan log-group sweep only runs in the failed/absent branch — never for a
    # healthy stack whose log groups CloudFormation still manages.
    groups_raw = aws_cli(
        "logs", "describe-log-groups", "--log-group-name-prefix", LOG_GROUP_PREFIX,
        "--region", region, "--query", "logGroups[].logGroupName", "--output", "text",
    )
    for g in (groups_raw or "").split():
        if g.startswith(LOG_GROUP_PREFIX):
            aws_cli("logs", "delete-log-group", "--log-group-name", g, "--region", region)
            print(f"  Removed orphaned log group: {g}")
    print()


def main() -> None:
    """Run the full deploy flow.

    Guarded behind ``if __name__ == '__main__'`` so importing this module (e.g.
    in tests) has no side effects — only running it as a script deploys.
    """
    global _impl_staged

    signal.signal(signal.SIGINT, _signal_handler)
    signal.signal(signal.SIGTERM, _signal_handler)
    if hasattr(signal, "SIGBREAK"):
        signal.signal(signal.SIGBREAK, _signal_handler)

    print("==========================================")
    print("  Unified AI Team — Deploy Agents + Gateway")
    print("==========================================\n")
    print("This script will, in order:")
    print("  1. Check prerequisites (agentcore, aws, node, cdk, uv)")
    print("  2. Resolve your AWS account + region")
    print("  2b. Pre-deploy cleanup: remove any failed stack + orphaned log groups")
    print("  3. Bootstrap CDK (safe to repeat)")
    print("  4. Stage shared code (commons, plugins, governance, requirements) into each agent")
    print("  5. Deploy 5 runtimes + the tactical-tools gateway via `agentcore deploy`")
    print("  6. Clean up the staged copies (originals remain the source of truth)\n")
    print("Checking prerequisites...")

    for tool in ["agentcore", "aws", "node", "cdk", "uv"]:
        check_tool(tool)

    account_id = aws_cli("sts", "get-caller-identity", "--query", "Account", "--output", "text")
    if not account_id:
        print("ERROR: Could not resolve AWS account. Check your credentials.")
        sys.exit(1)
    region = (
        os.environ.get("AWS_REGION")
        or os.environ.get("AWS_DEFAULT_REGION")
        or aws_cli("configure", "get", "region")
        or "us-east-1"
    )
    print(f"  AWS Account: {account_id}")
    print(f"  AWS Region:  {region}\n")

    # Optional content-safety guardrail (OWN code — NOT the off-limits cdk/).
    # Only runs when CREATE_BEDROCK_GUARDRAIL is set; otherwise a no-op so a
    # deploy without guardrail-create permissions is unaffected. The returned
    # id/version are exported so they flow to the runtimes' environment via the
    # deploy env mechanism (the runtime reads them from os.environ).
    import setup_guardrail

    guardrail = setup_guardrail.ensure_guardrail(region=region)
    if guardrail is not None:
        guardrail_id, guardrail_version = guardrail
        os.environ["BEDROCK_GUARDRAIL_ID"] = guardrail_id
        os.environ["BEDROCK_GUARDRAIL_VERSION"] = guardrail_version
        print(f"  Bedrock guardrail ready: {guardrail_id} (version {guardrail_version})\n")

    pre_deploy_cleanup(region)

    targets_file = SCRIPT_DIR / "agentcore" / "aws-targets.json"
    targets = [{"name": "default", "account": account_id, "region": region}]
    existing = json.loads(targets_file.read_text(encoding="utf-8")) if targets_file.exists() else []
    if existing != targets:
        targets_file.parent.mkdir(parents=True, exist_ok=True)
        targets_file.write_text(json.dumps(targets, indent=2) + "\n", encoding="utf-8")
        print(f"  Wrote deploy target to {targets_file.relative_to(SCRIPT_DIR)}\n")

    try:
        cdk_dir = SCRIPT_DIR / "agentcore" / "cdk"
        if cdk_dir.is_dir() and not (cdk_dir / "node_modules").is_dir():
            print("Installing CDK dependencies (npm install)...")
            run(["npm", "install"], cwd=cdk_dir)
            print()

        print("CDK Bootstrap...")
        run(["cdk", "bootstrap", f"aws://{account_id}/{region}"])
        print()

        # Stage the pure tool functions into gateway_tools/_impl so the Lambda
        # wrappers can import them without duplicating any logic.
        impl_dir = GATEWAY_TOOLS / "_impl"
        if impl_dir.exists():
            rmtree(impl_dir)
        shutil.copytree(SCRIPTS_SRC, impl_dir, ignore=_ignore_pycache())
        _impl_staged = True

        # Stage shared code into each agent directory.
        for agent in ALL_AGENTS:
            agent_dir = SCRIPT_DIR / agent
            if not agent_dir.is_dir():
                print(f"ERROR: Agent directory not found: {agent_dir}")
                sys.exit(1)
            print(f"Preparing: {agent}")

            for folder, src in (("commons", COMMONS_SRC), ("plugins", PLUGINS_SRC), ("governance", GOVERNANCE_SRC)):
                dest = agent_dir / folder
                if dest.exists():
                    rmtree(dest)
                shutil.copytree(src, dest, ignore=_ignore_pycache())
            for mod in SHARED_MODULES:
                shutil.copy2(SCRIPT_DIR / mod, agent_dir / mod)
            shutil.copy2(REQUIREMENTS_SRC, agent_dir / "requirements.txt")

            _injected.append(agent_dir)
        print()

        print("Deploying via CDK (agentcore deploy)...")
        run(["agentcore", "deploy", "--yes"], cwd=SCRIPT_DIR,
            env={**os.environ, "AWS_DEFAULT_REGION": region})

    except subprocess.CalledProcessError:
        print("\nDeployment failed. Check the output above.")
        cleanup()
        sys.exit(1)
    except Exception as e:
        print(f"\nUnexpected error: {e}")
        cleanup()
        sys.exit(1)
    else:
        cleanup()

    print("\n==========================================")
    print("  Deploy complete: 5 runtimes + tactical-tools gateway")
    print("==========================================")


if __name__ == "__main__":
    main()
