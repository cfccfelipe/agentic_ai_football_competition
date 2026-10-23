"""Render eval metrics as a readable report and a JSON comparison artifact.

All I/O lives here; ``metrics`` stays pure. ``render_text`` produces the
two-section human report; ``build_json``/``write_json`` persist a run-to-run
comparison artifact under the OS temp dir by default so nothing scatters in the
repo.
"""

import datetime
import json
import os
import tempfile

import constants

SCHEMA_VERSION = 1

_ALERT_SUFFIX = "  [ALERT]"


def render_text(breakdown: dict, performance: dict) -> str:
    """Render the two-section report.

    Teams render in the order they appear in ``breakdown`` (insertion order).
    Agent-performance rows flagged with ``alert`` get a trailing ``[ALERT]`` so
    timeouts / sub-100% success are visible at a glance.
    """
    lines: list[str] = []
    lines.append(
        "Command breakdown — what each team's agents decided to do during the match"
    )
    lines.append("")
    for team, data in breakdown.items():
        lines.append(team)
        lines.append(f"{data['total']} cmds · {data['avg_latency_ms']}ms avg")
        for cmd in data["commands"]:
            lines.append(f"  {cmd['display']}  {cmd['count']} · {cmd['pct']}%")
        lines.append("")

    lines.append("Agent performance — per-position response time and success rate")
    lines.append("")
    for team, positions in performance.items():
        lines.append(team)
        lines.append("  Position   Latency   Success")
        for position, stats in positions.items():
            suffix = _ALERT_SUFFIX if stats["alert"] else ""
            lines.append(
                f"  {position:<9}  {stats['avg_latency_ms']}ms"
                f"     {stats['success_pct']}%{suffix}"
            )
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


def build_json(breakdown: dict, performance: dict, *, meta: dict | None = None) -> dict:
    """Assemble the run-to-run comparison artifact.

    ``generated_at`` is injectable via ``meta`` so tests are deterministic.
    ``model_id`` and ``tick_budget_ms`` come from ``constants`` for provenance.
    """
    meta = meta or {}
    generated_at = meta.get(
        "generated_at",
        datetime.datetime.now(datetime.timezone.utc).isoformat(),
    )
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "model_id": constants.MODEL_ID,
        "tick_budget_ms": int(constants.TICK_TIMEOUT_SECONDS * 1000),
        "command_breakdown": breakdown,
        "agent_performance": performance,
    }


def write_json(data: dict, out_dir: str | None = None) -> str:
    """Write ``data`` as ``match-eval-<timestamp>.json`` and return the abs path.

    Defaults to ``%TEMP%\\match-eval`` so artifacts never land in the repo. Pass
    ``out_dir="docs/eval/output"`` to keep one inside the repo for inspection
    (that path is gitignored).
    """
    if out_dir is None:
        out_dir = os.path.join(tempfile.gettempdir(), "match-eval")
    os.makedirs(out_dir, exist_ok=True)

    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    path = os.path.abspath(os.path.join(out_dir, f"match-eval-{stamp}.json"))
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
    return path
