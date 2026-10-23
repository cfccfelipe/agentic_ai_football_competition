"""OFFLINE strategy discovery + validation.

Given a target name, an injected research callable proposes a full strategy
spec (``strategy.md`` metadata + the four role bodies). The spec is
validated hard — structure, frontmatter, name safety, non-collision, and
content safety — then staged to an OS-temp directory and landed into the
position-grouped layout ONLY on full success: the metadata file goes to
``src/plugins/strategies/<name>.md`` and each position body goes to
``src/plugins/<position>/<name>.md``. On any failure nothing is written and the
process exits non-zero.

This module is a TOOL, run on demand to grow the strategy library. It is NEVER
imported by the runtime agent (``unified_agent`` must not import it): browsing
and model research must never happen inside a per-tick ``invoke()``. The 4th
user ask — "let it search strategies in the browser if the offered ones are
not enough" — is served here, OUT of the tick path.

Single Responsibility: validate a proposed strategy and, if sound, land it as a
registry-discoverable folder. It does not choose strategies at match time.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

# --- path wiring so this runs standalone (src root + commons on sys.path) ---
_SRC_ROOT = Path(__file__).resolve().parents[2]
for _p in (str(_SRC_ROOT), str(_SRC_ROOT / "commons")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import constants  # noqa: E402
from parsing import VALID_COMMANDS  # noqa: E402
from plugins import registry  # noqa: E402

# The four ROLES a strategy supplies a body for (fwd1/fwd2 collapsed into fwd).
POSITIONS = ("gk", "def", "mid", "fwd")

# The metadata file key in a research spec (frontmatter only: name/type/
# formation/description). Lands at plugins/strategies/<name>.md.
METADATA_FILE = "strategy.md"

# The files every strategy spec must contain: one metadata file + five bodies.
REQUIRED_FILES = (METADATA_FILE,) + tuple(f"{p}.md" for p in POSITIONS)

# The deterministic tactical tools a strategy prompt may name (game-domain.md).
TACTICAL_TOOLS = (
    "evaluate_shot",
    "calculate_pass_options",
    "find_open_space",
    "get_defensive_assignment",
)

_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,30}$")
# Any ALL-CAPS command-looking token emitted as a commandType value.
_COMMAND_TOKEN_RE = re.compile(r'"commandType"\s*:\s*"([A-Z_]+)"')
# A bare UPPER_SNAKE word that looks like a command verb (>=4 chars).
_UPPER_WORD_RE = re.compile(r"\b([A-Z][A-Z_]{3,})\b")
_URL_RE = re.compile(r"https?://", re.IGNORECASE)
_FENCE_RE = re.compile(r"```")

# Phrasings that try to override the system prompt / exfiltrate it.
_OVERRIDE_PHRASES = (
    "ignore all previous",
    "ignore previous instructions",
    "disregard the above",
    "system prompt",
    "you are now",
    "reveal your",
    "override the guardrails",
)

# Words that appear legitimately in the prompts and are NOT commands.
_ALLOWED_UPPER_WORDS = {
    "ONLY", "JSON", "TR", "TL", "BR", "BL", "THROUGH", "THROW", "KICK",
    "TIGHT", "LOOSE", "LOB", "GROUND", "CENTER",
    "HOME", "AWAY", "GK", "DEF", "MID", "FWD", "NEVER",
    "ALWAYS", "YOUR", "FORWARD", "BACK", "ATTACK", "DEFEND", "WE", "OPP", "MY",
    "SPREAD", "FORBIDDEN", "THESE",
}


class SpecError(ValueError):
    """Raised when a proposed strategy spec fails validation."""


def _validate_name(name: str) -> list[str]:
    errors: list[str] = []
    # Path safety first: no separators, no parent refs.
    if os.sep in name or (os.altsep and os.altsep in name) or ".." in name or "/" in name or "\\" in name:
        errors.append(f"unsafe name (path separators or '..'): {name!r}")
    if not _NAME_RE.match(name):
        errors.append(f"name does not match ^[a-z][a-z0-9_-]{{1,30}}$: {name!r}")
    return errors


def _validate_collision(name: str, existing: dict) -> list[str]:
    errors: list[str] = []
    for other in existing:
        if name == other:
            errors.append(f"name collides with existing strategy {other!r}")
        elif name in other or other in name:
            errors.append(
                f"name {name!r} overlaps existing strategy {other!r} "
                "(substring ambiguity)"
            )
    return errors


_FLAT_FORMATION_RE = re.compile(r"^formation:[ \t]*(\S.*?)[ \t]*$", re.MULTILINE)


def _validate_frontmatter(skill_bytes: str, name: str) -> list[str]:
    errors: list[str] = []
    fm = registry._parse_frontmatter(skill_bytes)
    if fm.get("name") != name:
        errors.append(
            f"frontmatter name {fm.get('name')!r} != requested {name!r}"
        )
    if fm.get("type") != "strategy":
        errors.append(f"frontmatter type must be 'strategy', got {fm.get('type')!r}")
    if not (fm.get("description") or "").strip():
        errors.append("frontmatter description is empty")
    formation = fm.get("formation")
    if formation not in constants.ALLOWED_FORMATIONS:
        errors.append(
            f"formation {formation!r} not in ALLOWED_FORMATIONS "
            "(must be a flat scalar in the allowed set)"
        )
    else:
        # The parser normalizes a folded `>` scalar, so confirm from the raw
        # bytes that formation was written as a FLAT scalar in the allowed set.
        flat = _FLAT_FORMATION_RE.search(skill_bytes)
        if flat is None or flat.group(1) not in constants.ALLOWED_FORMATIONS:
            errors.append(
                "formation must be written as a flat scalar "
                "(e.g. `formation: 1-0-3`), not a folded `>` block"
            )
    return errors


def _validate_content_safety(label: str, body: str) -> list[str]:
    errors: list[str] = []
    low = body.lower()

    if "json array" not in low:
        errors.append(f"{label}: missing the mandatory JSON-array response line")

    for phrase in _OVERRIDE_PHRASES:
        if phrase in low:
            errors.append(f"{label}: system-override phrasing detected ({phrase!r})")

    if _URL_RE.search(body):
        errors.append(f"{label}: URLs are not allowed in a strategy prompt")

    if _FENCE_RE.search(body):
        errors.append(f"{label}: extra code fences are not allowed")

    # Any commandType value must be a real command.
    for token in _COMMAND_TOKEN_RE.findall(body):
        if token not in VALID_COMMANDS:
            errors.append(f"{label}: invalid command type {token!r}")

    # Bare UPPER_SNAKE verbs must be a valid command, a tactical tool, or an
    # explicitly allowed non-command word.
    for word in _UPPER_WORD_RE.findall(body):
        if (
            word in VALID_COMMANDS
            or word in _ALLOWED_UPPER_WORDS
            or word.lower() in TACTICAL_TOOLS
        ):
            continue
        errors.append(f"{label}: unknown command-like token {word!r}")

    return errors


def validate(name: str, files: dict[str, str], existing: dict) -> list[str]:
    """Return a list of validation errors for a proposed spec (empty = valid).

    ``files`` maps filename -> content (the exact bytes that would be written).
    ``existing`` is registry.strategies() for collision checks.
    """
    errors: list[str] = []
    errors += _validate_name(name)
    errors += _validate_collision(name, existing)

    present = set(files)
    missing = [f for f in REQUIRED_FILES if f not in present]
    extra = [f for f in present if f not in REQUIRED_FILES]
    if missing:
        errors.append(f"missing required files: {sorted(missing)}")
    if extra:
        errors.append(f"unexpected extra files: {sorted(extra)}")

    if METADATA_FILE in files:
        errors += _validate_frontmatter(files[METADATA_FILE], name)

    for label in POSITIONS:
        fname = f"{label}.md"
        if fname in files:
            errors += _validate_content_safety(fname, files[fname])

    return errors


def _target_paths(base: Path, name: str) -> dict[str, Path]:
    """Map each spec file to its final position-grouped destination.

    ``strategy.md`` -> base/strategies/<name>.md
    ``<pos>.md``    -> base/<pos>/<name>.md
    """
    paths = {METADATA_FILE: base / "strategies" / f"{name}.md"}
    for pos in POSITIONS:
        paths[f"{pos}.md"] = base / pos / f"{name}.md"
    return paths


def generate(name: str, research, plugins_dir: Path | None = None) -> Path:
    """Produce, validate, and land a new strategy in the position-grouped layout.

    Args:
        name: the target strategy name (also the per-file stem in each folder).
        research: a callable ``name -> {filename: content}`` producing the spec
            (``strategy.md`` metadata + ``gk/def/mid/fwd.md`` bodies).
            Injected so the whole flow is offline-testable; the default (built
            only in ``main()``) uses a web-search/Strands agent.
        plugins_dir: the plugins root where strategies/ and the position folders
            live. Defaults to the real src/plugins directory.

    Returns:
        The Path of the written strategy metadata file
        (``plugins/strategies/<name>.md``) on success.

    Raises:
        SpecError: if the spec fails any validation, or any destination already
            exists. Nothing is written on failure.
    """
    base = plugins_dir or registry.PLUGINS_DIR
    existing = registry.strategies(plugins_dir=base)

    files = research(name)

    errors = validate(name, files, existing)
    if errors:
        raise SpecError("; ".join(errors))

    targets = _target_paths(base, name)
    for dest in targets.values():
        if dest.exists():
            raise SpecError(f"destination already exists: {dest}")

    # Stage to an OS-temp dir first; only move each file into place on full
    # success so a partial write never lands in the repo.
    staging_root = Path(tempfile.mkdtemp(prefix="discover_strategy_"))
    try:
        # Re-validate the staged metadata on disk via the registry (defence in
        # depth: the file we are about to publish must parse as a strategy).
        staged_meta_dir = staging_root / "strategies"
        staged_meta_dir.mkdir()
        staged_meta = staged_meta_dir / f"{name}.md"
        staged_meta.write_text(files[METADATA_FILE], encoding="utf-8")
        meta = registry._meta_from_frontmatter(staged_meta, name)
        if meta.type != "strategy" or meta.name != name:
            raise SpecError("staged metadata failed to parse as a strategy")

        # Stage every file flat, then move each to its position-grouped home.
        for fname in REQUIRED_FILES:
            (staging_root / fname).write_text(files[fname], encoding="utf-8")

        for fname, dest in targets.items():
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(staging_root / fname), str(dest))
    finally:
        shutil.rmtree(staging_root, ignore_errors=True)

    return targets[METADATA_FILE]


def _default_research(name: str) -> dict[str, str]:  # pragma: no cover
    """Build the lazy web-search/Strands research agent and ask it for a spec.

    Imported lazily and ONLY from main() so neither strands nor a network call
    is ever pulled in by importing this module.
    """
    from strands import Agent
    from strands.models import BedrockModel
    from strands_tools import http_request  # web access tool

    agent = Agent(
        model=BedrockModel(**constants.bedrock_model_kwargs()),
        tools=[http_request],
        system_prompt=(
            "You research football tactics and emit a strategy spec as six files "
            "(strategy.md + gk/def/mid/fwd.md). strategy.md needs flat "
            "frontmatter name/type(=strategy)/formation/description. Position "
            "files must reference only valid commands and end with a JSON-array "
            "response line."
        ),
    )
    raise NotImplementedError(
        "Wire the agent's structured output into a {filename: content} dict. "
        f"Requested: {name}; agent built: {agent is not None}"
    )


def main(argv: list[str] | None = None) -> int:  # pragma: no cover
    """CLI entry: discover_strategy <name>. Exit non-zero on rejection."""
    argv = argv if argv is not None else sys.argv[1:]
    if not argv:
        print("usage: discover_strategy <name>", file=sys.stderr)
        return 2
    name = argv[0]
    try:
        dest = generate(name, _default_research)
    except SpecError as e:
        print(f"rejected: {e}", file=sys.stderr)
        return 1
    print(f"written: {dest}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
