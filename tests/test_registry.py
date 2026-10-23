"""Tests for the plugin registry — discovery by scanning folders."""

from plugins import registry


def test_discovers_all_plugins():
    found = registry.discover()
    assert set(found) >= {"general", "balanced", "aggressive", "defensive"}


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
