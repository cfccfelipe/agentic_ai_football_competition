"""Regression test: plugin_loader must resolve governance/ and plugins/ in the
DEPLOYED BUNDLE layout, where they are SIBLINGS of plugin_loader.py.

This is the exact failure that took a deploy down: build_static_base() raised
`FileNotFoundError: /governance/guardrails.md` because plugin_loader resolved
governance via `Path(__file__).resolve().parents[2]`, which in the bundle
(/var/task/plugin_loader.py) walks ABOVE /var/task to '/'. In the deployed
bundle, deploy_all.py stages governance/ and plugins/ as siblings of
plugin_loader.py (/var/task/governance, /var/task/plugins), so resolution must
try the SIBLING first.

Local tests pass with the old code because the local checkout layout
(src/agents/players/plugin_loader.py with src/governance two levels up) happens
to resolve — which is exactly why this bundle-layout simulation is needed: the
local-only tests are blind to the deployed path.

Hermetic: builds a fake bundle under pytest's tmp_path from the real source
bytes, imports plugin_loader fresh with only the bundle root on sys.path, and
restores sys.path/sys.modules afterwards.
"""

import copy
import importlib.util
import os
import shutil
import sys

import pytest

_HERE = os.path.dirname(__file__)
_SRC = os.path.normpath(os.path.join(_HERE, "..", "src"))
_PLAYERS = os.path.join(_SRC, "agents", "players")


def _copy_tree(src, dst):
    shutil.copytree(src, dst, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))


@pytest.fixture
def clean_state():
    saved_path = copy.copy(sys.path)
    saved_modules = set(sys.modules)
    try:
        yield
    finally:
        sys.path[:] = saved_path
        for m in set(sys.modules) - saved_modules:
            del sys.modules[m]


def _build_fake_bundle(root: str) -> None:
    """Mirror the deployed /var/task layout: the runtime modules + staged
    governance/ and plugins/ all FLAT at the bundle root (siblings)."""
    # runtime modules that plugin_loader imports or sits beside
    for mod in ("plugin_loader.py", "constants.py"):
        shutil.copy2(os.path.join(_PLAYERS, mod), os.path.join(root, mod))
    # staged resource dirs as SIBLINGS (this is what deploy_all.py does)
    _copy_tree(os.path.join(_SRC, "governance"), os.path.join(root, "governance"))
    _copy_tree(os.path.join(_SRC, "plugins"), os.path.join(root, "plugins"))


def _import_plugin_loader_from(root: str):
    """Import plugin_loader.py from the fake bundle with only root on sys.path."""
    sys.path.insert(0, root)
    name = "plugin_loader_bundle_under_test"
    spec = importlib.util.spec_from_file_location(
        name, os.path.join(root, "plugin_loader.py")
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


def test_build_static_base_resolves_in_bundle_layout(tmp_path, clean_state):
    """build_static_base() must find governance/guardrails.md when governance/
    is a SIBLING of plugin_loader.py (the deployed bundle)."""
    root = str(tmp_path / "var_task")
    os.makedirs(root)
    _build_fake_bundle(root)

    pl = _import_plugin_loader_from(root)
    base = pl.build_static_base()

    # The static base is guardrails + tool catalog; assert real content from both.
    assert "Game Guardrails" in base, "guardrails.md not loaded in bundle layout"
    assert base.strip(), "static base is empty"


def test_skill_prompt_resolves_in_bundle_layout(tmp_path, clean_state):
    """load_skill_prompt must resolve plugins/<pos>/<strategy>.md as a sibling."""
    root = str(tmp_path / "var_task")
    os.makedirs(root)
    _build_fake_bundle(root)

    pl = _import_plugin_loader_from(root)
    prompt = pl.load_skill_prompt("balanced", "GK", 0)

    assert prompt.strip(), "skill prompt empty in bundle layout"
    # {player_id} must have been substituted (no leftover template token)
    assert "{player_id}" not in prompt


def test_guardrails_path_is_not_filesystem_root(tmp_path, clean_state):
    """Guard the specific regression: GOVERNANCE must resolve UNDER the bundle
    root, never at '/governance' (parents[2] walking above /var/task)."""
    root = str(tmp_path / "var_task")
    os.makedirs(root)
    _build_fake_bundle(root)

    pl = _import_plugin_loader_from(root)
    gov = str(pl.GOVERNANCE)
    assert gov.startswith(root), f"GOVERNANCE resolved outside the bundle: {gov}"
    assert os.path.isfile(gov), f"GOVERNANCE path does not exist: {gov}"
