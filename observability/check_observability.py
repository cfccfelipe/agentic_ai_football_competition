#!/usr/bin/env python3
"""Diagnose AgentCore observability + pull recent runtime logs.

Read-only. Answers the questions we otherwise guess at:
  1. Is CloudWatch Transaction Search actually ACTIVE (account-level)?
  2. Which runtime log groups exist, and do their `spans`/`otel-rt-logs`
     streams have ANY events (i.e. did the runtime ever emit telemetry)?
  3. What are the most recent log lines for a chosen runtime — especially any
     init error like "Runtime initialization time exceeded" or a Python
     traceback — so we diagnose init failures from real data, not guesses.

Credentials come from the environment (the Makefile target loads .env first).
Nothing is created or modified. No files written to the repo.

Usage:
  uv run python observability/check_observability.py            # summary for all runtimes
  uv run python observability/check_observability.py ai_gk      # + recent logs for the GK runtime
"""

from __future__ import annotations

import io
import os
import sys

# Force UTF-8 stdout so log lines containing arrows/unicode don't crash on the
# Windows cp1252 console codec.
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
except Exception:
    pass

import boto3
from botocore.exceptions import BotoCoreError, ClientError, NoCredentialsError

try:  # load .env so AWS creds are available regardless of how we're invoked
    from dotenv import load_dotenv
    _here = os.path.dirname(os.path.abspath(__file__))
    load_dotenv(os.path.join(_here, "..", ".env"))
except Exception:
    pass

RUNTIME_LG_PREFIX = "/aws/bedrock-agentcore/runtimes"


def _region(session: boto3.Session) -> str:
    r = session.region_name or os.getenv("AWS_REGION") or os.getenv("AWS_DEFAULT_REGION")
    if not r:
        raise ValueError("Set AWS_REGION / AWS_DEFAULT_REGION (or configure a region).")
    return r


def check_transaction_search(xray) -> None:
    print("== Transaction Search (account-level) ==")
    dest = xray.get_trace_segment_destination()
    print(f"  Destination: {dest.get('Destination')}  Status: {dest.get('Status')}")
    if dest.get("Destination") == "CloudWatchLogs" and dest.get("Status") == "ACTIVE":
        print("  -> ACTIVE (spans can be ingested)")
    else:
        print("  -> NOT fully active; run `make monitoring` to enable it.")
    print()


def list_runtime_log_groups(logs) -> list[str]:
    groups: list[str] = []
    paginator = logs.get_paginator("describe_log_groups")
    for page in paginator.paginate(logGroupNamePrefix=RUNTIME_LG_PREFIX):
        groups.extend(g["logGroupName"] for g in page.get("logGroups", []))
    return sorted(groups)


def stream_activity(logs, group: str) -> dict:
    """Return {stream_name: lastEventTimestamp or None} for a group's streams."""
    out: dict = {}
    try:
        resp = logs.describe_log_streams(
            logGroupName=group, orderBy="LastEventTime", descending=True, limit=10
        )
        for s in resp.get("logStreams", []):
            out[s["logStreamName"]] = s.get("lastEventTimestamp")
    except (BotoCoreError, ClientError):
        pass
    return out


def summarize_runtimes(logs) -> None:
    print("== Runtime log groups — did any telemetry land? ==")
    groups = list_runtime_log_groups(logs)
    if not groups:
        print("  (none found under the runtime prefix)")
        print()
        return
    for g in groups:
        short = g[len(RUNTIME_LG_PREFIX) + 1 :]
        streams = stream_activity(logs, g)
        if not streams:
            print(f"  {short}: NO streams (never emitted anything)")
            continue
        parts = []
        for name, ts in streams.items():
            parts.append(f"{name}={'has events' if ts else 'EMPTY'}")
        has_any = any(ts for ts in streams.values())
        flag = "OK" if has_any else "SILENT (init likely failed before emitting)"
        print(f"  {short}: {flag}")
        for p in parts:
            print(f"      - {p}")
    print()


def tail_runtime(logs, needle: str) -> None:
    """Print recent events for the runtime log group matching `needle`."""
    groups = [g for g in list_runtime_log_groups(logs) if needle.lower() in g.lower()]
    if not groups:
        print(f"== No runtime log group matched '{needle}' ==")
        return
    for g in groups:
        print(f"== Recent events: {g} ==")
        streams = logs.describe_log_streams(
            logGroupName=g, orderBy="LastEventTime", descending=True, limit=5
        ).get("logStreams", [])
        found = False
        for s in streams:
            try:
                ev = logs.get_log_events(
                    logGroupName=g, logStreamName=s["logStreamName"],
                    limit=40, startFromHead=False,
                ).get("events", [])
            except (BotoCoreError, ClientError):
                ev = []
            for e in ev:
                msg = e.get("message", "").rstrip()
                if "opentelemetry" in msg.lower() and "error" not in msg.lower():
                    continue  # skip OTEL noise, keep errors
                print(f"  [{s['logStreamName']}] {msg}")
                found = True
        if not found:
            print("  (no non-OTEL events — the runtime emitted nothing meaningful)")
        print()


def main() -> None:
    session = boto3.Session()
    region = _region(session)
    logs = session.client("logs", region_name=region)
    xray = session.client("xray", region_name=region)

    acct = session.client("sts").get_caller_identity()["Account"]
    print(f"Account={acct} Region={region}\n")

    check_transaction_search(xray)
    summarize_runtimes(logs)

    if len(sys.argv) > 1:
        tail_runtime(logs, sys.argv[1])


if __name__ == "__main__":
    try:
        main()
    except (BotoCoreError, ClientError, NoCredentialsError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
