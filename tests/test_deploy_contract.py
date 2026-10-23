"""Deploy/packaging contract for the static/dynamic prompt split (AC-R5).

Guards two invariants so the deployed bundle does not crash:
  - src/governance/tool_catalog.md exists and ships via the already-staged
    governance/ folder (no deploy_all.py change needed for a new governance md);
  - deploy_all.SHARED_MODULES is still exactly the five runtime modules under
    players/ — this plan introduces NO new players/ module, and a future one
    MUST be added here or the bundle raises ModuleNotFoundError.

deploy_all is import-safe (its flow is under main() + __main__ guard).
"""

import importlib
from pathlib import Path

import pytest


@pytest.fixture
def deploy_all():
    mod = importlib.import_module("deploy_all")
    return importlib.reload(mod)


def test_tool_catalog_asset_exists(deploy_all):
    assert deploy_all.GOVERNANCE_SRC.is_dir()
    assert (deploy_all.GOVERNANCE_SRC / "tool_catalog.md").is_file()


def test_governance_is_staged_so_catalog_ships(deploy_all):
    # The staged folder set (used in cleanup()/main()) includes "governance",
    # so tool_catalog.md ships inside it with no SHARED_MODULES change.
    staged = ("commons", "plugins", "governance", "requirements.txt", *deploy_all.SHARED_MODULES)
    assert "governance" in staged


def test_shared_modules_is_the_expected_five(deploy_all):
    assert deploy_all.SHARED_MODULES == [
        "constants.py",
        "planner.py",
        "plugin_loader.py",
        "unified_agent.py",
        "runtime_guards.py",
    ]
