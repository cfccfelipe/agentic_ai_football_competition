"""Tests for commons/_bootstrap.setup_commons_path().

Verifies that the shared bootstrap wires the correct commons/ directory onto
sys.path for all three layouts the deployed + local-dev agents can present:

  - sibling   ./commons          (DEPLOYED bundle: commons sits next to the caller)
  - intermediate ../commons       (one level up)
  - local dev ../../../commons    (agents/commons three levels up from main.py)

The sibling layout is the one the deployed runtimes actually use (deploy_all.py
stages commons/ into the agent dir root), so it MUST resolve or every runtime
crashes with `ModuleNotFoundError: No module named '_bootstrap'`.

Tests are hermetic: each builds its own layout under pytest's tmp_path (never
under the repo) from a copy of the real src/commons/_bootstrap.py bytes, loads
it fresh, and restores sys.path/sys.modules afterwards.
"""

import copy
import importlib.util
import os
import shutil
import sys

import pytest

_HERE = os.path.dirname(__file__)
_REAL_BOOTSTRAP = os.path.normpath(
    os.path.join(_HERE, "..", "src", "commons", "_bootstrap.py")
)


def _load_bootstrap_module(path):
    """Import a _bootstrap.py file from an arbitrary path under a unique name."""
    name = "_bootstrap_under_test"
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def clean_path():
    """Snapshot sys.path + sys.modules and restore them after the test."""
    saved_path = copy.copy(sys.path)
    saved_modules = set(sys.modules)
    try:
        yield
    finally:
        sys.path[:] = saved_path
        for name in set(sys.modules) - saved_modules:
            del sys.modules[name]


def _build_layout(root, caller_rel, commons_rel):
    """Create <root>/<caller_rel> and a commons/ dir at <root>/<commons_rel>.

    Copies the REAL _bootstrap.py into the commons dir and drops a sentinel
    module so we can prove the right directory got onto sys.path. Returns the
    absolute path to the caller file and to the commons dir.
    """
    caller_file = os.path.join(root, caller_rel)
    commons_dir = os.path.join(root, commons_rel)
    os.makedirs(os.path.dirname(caller_file), exist_ok=True)
    os.makedirs(commons_dir, exist_ok=True)

    with open(caller_file, "w", encoding="utf-8") as fh:
        fh.write("# test caller\n")

    shutil.copyfile(_REAL_BOOTSTRAP, os.path.join(commons_dir, "_bootstrap.py"))
    with open(os.path.join(commons_dir, "_sentinel.py"), "w", encoding="utf-8") as fh:
        fh.write("MARKER = 'wired'\n")

    return os.path.normpath(caller_file), os.path.normpath(commons_dir)


# ---------------------------------------------------------------------------
# The fix: all three layouts must resolve
# ---------------------------------------------------------------------------

def test_sibling_layout_deployed(tmp_path, clean_path):
    """DEPLOYED bundle: commons is a sibling of the caller (./commons)."""
    caller_file, commons_dir = _build_layout(
        str(tmp_path), os.path.join("agent", "caller.py"), os.path.join("agent", "commons")
    )
    mod = _load_bootstrap_module(os.path.join(commons_dir, "_bootstrap.py"))

    mod.setup_commons_path(caller_file)

    assert commons_dir in sys.path
    # _bootstrap and a sentinel are importable from that dir
    import _sentinel  # noqa: F401
    assert _sentinel.MARKER == "wired"


def test_intermediate_layout(tmp_path, clean_path):
    """Intermediate layout: commons one level up from the caller (../commons)."""
    caller_file, commons_dir = _build_layout(
        str(tmp_path), os.path.join("agent", "src", "caller.py"), os.path.join("agent", "commons")
    )
    mod = _load_bootstrap_module(os.path.join(commons_dir, "_bootstrap.py"))

    mod.setup_commons_path(caller_file)

    assert commons_dir in sys.path


def test_local_dev_layout(tmp_path, clean_path):
    """Local dev: commons three levels up (../../../commons from main.py)."""
    caller_file, commons_dir = _build_layout(
        str(tmp_path),
        os.path.join("agents", "players", "agent", "main.py"),
        "commons",
    )
    mod = _load_bootstrap_module(os.path.join(commons_dir, "_bootstrap.py"))

    mod.setup_commons_path(caller_file)

    assert commons_dir in sys.path


def test_no_duplicate_inserts(tmp_path, clean_path):
    """Calling twice must not add the same commons dir to sys.path twice."""
    caller_file, commons_dir = _build_layout(
        str(tmp_path), os.path.join("agent", "caller.py"), os.path.join("agent", "commons")
    )
    mod = _load_bootstrap_module(os.path.join(commons_dir, "_bootstrap.py"))

    mod.setup_commons_path(caller_file)
    mod.setup_commons_path(caller_file)

    assert sys.path.count(commons_dir) == 1


# ---------------------------------------------------------------------------
# Regression guard: the ORIGINAL two-candidate logic FAILS the sibling case
# ---------------------------------------------------------------------------

def _original_setup_commons_path(caller_file):
    """Reproduction of the pre-fix logic (only ../commons and ../../../commons).

    Kept here to prove the sibling/deployed layout was NOT resolvable before the
    fix. If this ever starts resolving the sibling dir, the regression guard is
    meaningless and the test should be revisited.
    """
    here = os.path.dirname(os.path.abspath(caller_file))
    commons_deployed = os.path.join(here, "..", "commons")
    commons_local = os.path.join(here, "..", "..", "..", "commons")
    commons_dir = commons_deployed if os.path.isdir(commons_deployed) else commons_local
    commons_dir = os.path.normpath(commons_dir)
    if commons_dir not in sys.path:
        sys.path.insert(0, commons_dir)
    return commons_dir


def test_original_logic_fails_sibling_layout(tmp_path, clean_path):
    """The old two-candidate logic never reaches the sibling ./commons dir."""
    caller_file, commons_dir = _build_layout(
        str(tmp_path), os.path.join("agent", "caller.py"), os.path.join("agent", "commons")
    )

    wired = _original_setup_commons_path(caller_file)

    # The old logic wires a NON-existent ../../../commons, never the sibling dir.
    assert wired != commons_dir
    assert commons_dir not in sys.path
    assert not os.path.isdir(wired)
