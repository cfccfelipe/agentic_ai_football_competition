"""Tests for the plugin registry — discovery by scanning folders."""

from plugins import registry

DEFAULT_FORMATION = "1-1-1-1"


def _write_skill(tmp_path, body):
    plugin_dir = tmp_path / "custom"
    plugin_dir.mkdir()
    (plugin_dir / "skill.md").write_text(body, encoding="utf-8")
    return registry.discover(plugins_dir=tmp_path)["custom"]


def test_formation_parsed_from_flat_frontmatter(tmp_path):
    meta = _write_skill(
        tmp_path,
        "---\nname: custom\ntype: skill\ndescription: x\nformation: 3-0-1\n---\n",
    )
    assert meta.formation == "3-0-1"


def test_formation_absent_defaults(tmp_path):
    meta = _write_skill(
        tmp_path,
        "---\nname: custom\ntype: skill\ndescription: x\n---\n",
    )
    assert meta.formation == DEFAULT_FORMATION


def test_formation_folded_scalar_defaults(tmp_path):
    # A folded `>` scalar is not a valid flat formation -> default.
    meta = _write_skill(
        tmp_path,
        "---\nname: custom\ntype: skill\ndescription: x\nformation: >\n  not-a-formation\n---\n",
    )
    assert meta.formation == DEFAULT_FORMATION


def test_discovers_all_plugins():
    found = registry.discover()
    # strategy metadata (strategies/*.md) + scripts plugin + five position indexes
    assert set(found) >= {
        "general",
        "balanced",
        "aggressive",
        "defensive",
        "gk",
        "def",
        "mid",
        "fwd1",
        "fwd2",
    }


def test_position_indexes_are_not_strategies():
    # The per-position skill.md indexes use `type: position`; the registry must
    # never surface them as selectable strategies.
    strats = registry.strategies()
    for pos in ("gk", "def", "mid", "fwd1", "fwd2"):
        assert pos not in strats


def test_general_is_scripts_and_autoload():
    meta = registry.discover()["general"]
    assert meta.type == "scripts"
    assert meta.auto_load is True


def test_strategies_excludes_scripts():
    strats = registry.strategies()
    assert set(strats) == {"balanced", "aggressive", "defensive"}
    assert "general" not in strats


def test_each_strategy_has_a_description():
    for name, meta in registry.strategies().items():
        assert meta.description, f"{name} has no description"


def test_strategy_descriptions_block_mentions_each():
    block = registry.strategy_descriptions().lower()
    for name in ("balanced", "aggressive", "defensive"):
        assert name in block


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
    print(f"{len(fns)} tests passed")
