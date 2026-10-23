#!/usr/bin/env python3
"""
Tear down the 5 unified AI football agents + tactical-tools gateway.

Usage:
    uv run python src/agents/players/destroy_all.py

This is the inverse of deploy_all.py. It runs `agentcore destroy` from the
project directory, which removes every runtime and the tactical-tools gateway
(and its 4 Lambda tools) declared in agentcore/agentcore.json.

One deploy puts up everything (agents + staged skills + gateway); one destroy
takes it all down. There is no separate MCP/skills resource to remove — the
skill prompts are packaged inside each agent bundle, and the MCP tools are the
gateway's Lambda targets, so they go when the stack goes.

Prerequisites: agentcore, aws, cdk on PATH; AWS credentials configured.
"""

import os
import shutil
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent.resolve()


def resolve_exe(name):
    path = shutil.which(name)
    if path is None:
        print(f"ERROR: '{name}' not found on PATH.")
        sys.exit(1)
    return path


def aws_cli(*args):
    r = subprocess.run(
        [resolve_exe("aws"), *args], capture_output=True, text=True, encoding="utf-8"
    )
    return r.stdout.strip() if r.returncode == 0 else None


print("==========================================")
print("  Unified AI Team — Destroy Agents + Gateway")
print("==========================================\n")

for tool in ("agentcore", "aws", "cdk"):
    resolve_exe(tool)

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
print("Destroying 5 runtimes + tactical-tools gateway...\n")

cmd = [resolve_exe("agentcore"), "destroy", "--yes"]
print(f"  > {' '.join(cmd)}")
result = subprocess.run(
    cmd,
    cwd=SCRIPT_DIR,
    env={**os.environ, "AWS_DEFAULT_REGION": region, "PYTHONIOENCODING": "utf-8"},
)

if result.returncode != 0:
    print("\nDestroy failed. Check the output above.")
    sys.exit(result.returncode)

print("\n==========================================")
print("  Teardown complete.")
print("==========================================")
