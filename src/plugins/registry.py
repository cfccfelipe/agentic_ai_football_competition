"""Plugin registry — discovers strategy and script plugins by scanning the
plugins/ directory and reading each skill.md's frontmatter.

Single Responsibility: this module only knows *what plugins exist* and their
metadata. It does not build prompts, call agents, or know about positions.
Adding a new strategy is as simple as creating a folder with a skill.md —
no code changes here (Open/Closed).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

PLUGINS_DIR = Path(__file__).parent

# Formation defaults mirror src/agents/players/constants.py (the single source
# of truth). They are re-declared here as plain literals to keep the registry
# free of a dependency on the agent package (no circular import at discovery).
_DEFAULT_FORMATION = "1-1-1-1"
_ALLOWED_FORMATIONS = (
    "0-4-0", "1-0-3", "1-1-2", "1-1-1-1", "1-2-1", "2-0-2", "2-1-1", "3-0-1",
)


@dataclass(frozen=True)
class SkillMeta:
    """Metadata for one plugin, parsed from its skill.md frontmatter."""

    name: str
    type: str          # "strategy" | "position" | "scripts"
    description: str
    auto_load: bool
    path: Path         # the plugin's directory
    formation: str     # DEF-MID-FWD outfield shape; defaults to DEFAULT_FORMATION


def _parse_frontmatter(text: str) -> dict:
    """Parse a minimal YAML frontmatter block (--- ... ---) at the top of a file.

    Supports flat `key: value` pairs and folded scalars introduced with `>`.
    Deliberately tiny — avoids a yaml dependency for the handful of keys used here.
    """
    if not text.startswith("---"):
        return {}

    end = text.find("\n---", 3)
    if end == -1:
        return {}

    block = text[3:end].strip("\n")
    result: dict[str, str] = {}
    key: str | None = None
    folded_lines: list[str] = []
    folding = False

    for line in block.splitlines():
        if folding:
            # Folded scalar continues while lines are indented.
            if line.startswith((" ", "\t")) and line.strip():
                folded_lines.append(line.strip())
                continue
            result[key] = " ".join(folded_lines)  # type: ignore[index]
            folding = False
            folded_lines = []

        if not line.strip() or ":" not in line:
            continue

        raw_key, raw_val = line.split(":", 1)
        key = raw_key.strip()
        val = raw_val.strip()

        if val == ">":
            folding = True
            folded_lines = []
        else:
            result[key] = val.strip('"').strip("'")

    if folding and key is not None:
        result[key] = " ".join(folded_lines)

    return result


# The folder holding one frontmatter file per strategy (name/formation/
# description). Its files are discovered individually, not as a skill.md plugin.
_STRATEGIES_DIRNAME = "strategies"


def _meta_from_frontmatter(md_file: Path, fallback_name: str) -> SkillMeta:
    """Build a SkillMeta from a markdown file's frontmatter block."""
    fm = _parse_frontmatter(md_file.read_text(encoding="utf-8"))
    formation = fm.get("formation", _DEFAULT_FORMATION)
    if formation not in _ALLOWED_FORMATIONS:
        formation = _DEFAULT_FORMATION
    return SkillMeta(
        name=fm.get("name", fallback_name),
        type=fm.get("type", "skill"),
        description=fm.get("description", ""),
        auto_load=str(fm.get("auto_load", "false")).lower() == "true",
        path=md_file.parent,
        formation=formation,
    )


def _load_meta(plugin_dir: Path) -> SkillMeta | None:
    """Read one plugin's skill.md into a SkillMeta, or None if absent."""
    skill_file = plugin_dir / "skill.md"
    if not skill_file.is_file():
        return None
    return _meta_from_frontmatter(skill_file, plugin_dir.name)


def discover(plugins_dir: Path | None = None) -> dict[str, SkillMeta]:
    """Scan the plugins directory and return {name: SkillMeta} for every plugin.

    A plugin is any immediate subdirectory containing a skill.md (the per-
    position index folders and the scripts plugin). In addition, every markdown
    file inside the ``strategies/`` folder is discovered as its own strategy
    metadata entry, so dropping ``strategies/<name>.md`` plus the matching
    position bodies adds a strategy with no code change.
    """
    base = plugins_dir or PLUGINS_DIR
    registry: dict[str, SkillMeta] = {}
    for child in sorted(base.iterdir()):
        if not child.is_dir():
            continue
        if child.name == _STRATEGIES_DIRNAME:
            for md_file in sorted(child.glob("*.md")):
                meta = _meta_from_frontmatter(md_file, md_file.stem)
                registry[meta.name] = meta
            continue
        meta = _load_meta(child)
        if meta is not None:
            registry[meta.name] = meta
    return registry


def strategies(plugins_dir: Path | None = None) -> dict[str, SkillMeta]:
    """Return only the strategy plugins (type == 'strategy').

    Strategy metadata now lives in ``plugins/strategies/<name>.md`` as a single
    frontmatter block carrying name/formation/description; per-position index
    files use ``type: position`` and the tactical scripts plugin uses
    ``type: scripts``, so neither is returned here.
    """
    return {n: m for n, m in discover(plugins_dir).items() if m.type == "strategy"}


def strategy_descriptions(plugins_dir: Path | None = None) -> str:
    """Render a text block of every strategy's name + description.

    This is what the planner shows the LLM so it can choose a strategy by
    reading the descriptions rather than hard-coded rules.
    """
    lines = []
    for name, meta in strategies(plugins_dir).items():
        lines.append(f"- {name}: {meta.description}".rstrip())
    return "\n".join(lines)
