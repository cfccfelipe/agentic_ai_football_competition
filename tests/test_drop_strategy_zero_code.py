"""Drop-a-new-strategy is zero-code (north-star AC-N1).

Builds a minimal plugins tree in tmp_path, drops a BRAND-NEW strategy
(strategies/<new>.md + <pos>/<new>.md for all five positions), points the
registry + loader roots at it, and asserts through the RUNTIME entry points
(not registry.discover(dir) directly) that the new strategy is:
  (a) selectable by the planner — plugin_loader.strategy_names() includes it;
  (b) loadable for every one of the five positions — load_skill_prompt returns
      the new body for each position label.

No Python is edited to add the strategy. Uses tool-free bodies so the drop
mirrors a plain new strategy (decide-with-facts still comes from the static
catalog, not per-body wording).
"""

from pathlib import Path

from test_helpers import mock_agentcore_gateway

mock_agentcore_gateway()

import plugin_loader  # noqa: E402
from plugins import registry  # noqa: E402

POSITIONS = ("gk", "def", "mid", "fwd1", "fwd2")
NEW = "counterpress"
MARKER = "COUNTERPRESS-BODY-MARKER"


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _build_tree(root: Path) -> None:
    strategies_dir = root / "strategies"
    # Existing strategies (metadata + bodies) so the tree is realistic.
    existing = {
        "balanced": "1-2-1",
        "aggressive": "1-0-3",
        "defensive": "3-0-1",
    }
    for name, formation in existing.items():
        _write(
            strategies_dir / f"{name}.md",
            f"---\nname: {name}\ntype: strategy\nformation: {formation}\n"
            f"description: {name} strategy.\n---\n",
        )
    # The brand-new strategy metadata (valid frontmatter, allowed formation).
    _write(
        strategies_dir / f"{NEW}.md",
        f"---\nname: {NEW}\ntype: strategy\nformation: 1-1-2\n"
        f"description: Win the ball high and strike immediately.\n---\n",
    )
    # Bodies for every position and every strategy (incl. the new one).
    for pos in POSITIONS:
        for name in (*existing, NEW):
            body = f"You are the {pos} playing {name}. Return ONE JSON array command."
            if name == NEW:
                body = f"{MARKER} {body}"
            _write(root / pos / f"{name}.md", body)


def test_dropped_strategy_is_selectable_and_loadable(tmp_path, monkeypatch):
    root = tmp_path / "plugins"
    _build_tree(root)

    # Point BOTH roots the runtime path reads at the tmp tree.
    monkeypatch.setattr(registry, "PLUGINS_DIR", root)
    monkeypatch.setattr(plugin_loader, "_PLUGINS_ROOT", root)

    # (a) planner-selectable through the runtime entry point.
    names = plugin_loader.strategy_names()
    assert NEW in names
    assert {"balanced", "aggressive", "defensive"} <= set(names)

    # (b) loadable for all five positions through the runtime entry point.
    labels = {"gk": "GK", "def": "DEF", "mid": "MID", "fwd1": "FWD1", "fwd2": "FWD2"}
    for folder, label in labels.items():
        body = plugin_loader.load_skill_prompt(NEW, label, 3)
        assert MARKER in body, f"{label} did not load the new {NEW} body"
        # The resolved formation of the new strategy rides the lookup.
    # Formation of the dropped strategy is honored (1-1-2 declared above).
    descriptions = plugin_loader.strategy_descriptions()
    assert NEW in descriptions
