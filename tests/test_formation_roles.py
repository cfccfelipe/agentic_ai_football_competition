"""Tests for formation_roles — the dynamic-role single source of truth.

Hard invariants under BOTH flag states, for EVERY ALLOWED_FORMATIONS value:
  - player 0 -> GK (always), player 1 -> DEF (always) — guarantees >=1 GK +1 DEF.
  - players 2/3/4 take the formation's remaining DEF-MID-FWD distribution.
  - roles are drawn from the 4-role set {GK, DEF, MID, FWD}.
  - the module is listed in deploy_all.SHARED_MODULES.
"""

import importlib

import pytest

import constants
import formation_roles


ROLE_SET = set(constants.ROLES)  # {GK, DEF, MID, FWD}

# The exact flag-OFF mapping for players 2/3/4 per formation (the plan's table).
EXPECTED_234 = {
    "0-4-0": ("MID", "MID", "MID"),
    "1-0-3": ("FWD", "FWD", "FWD"),
    "1-1-2": ("MID", "FWD", "FWD"),
    "1-1-1-1": ("MID", "FWD", "FWD"),
    "1-2-1": ("MID", "MID", "FWD"),
    "2-0-2": ("DEF", "FWD", "FWD"),
    "2-1-1": ("DEF", "MID", "FWD"),
    "3-0-1": ("DEF", "DEF", "FWD"),
}


@pytest.mark.parametrize("formation", constants.ALLOWED_FORMATIONS)
def test_gk_and_def_are_pinned_both_flag_states(formation):
    for flex in (False, True):
        roles = formation_roles.formation_roles(formation, flex=flex)
        assert roles[0] == "GK", (formation, flex)
        assert roles[1] == "DEF", (formation, flex)


@pytest.mark.parametrize("formation", constants.ALLOWED_FORMATIONS)
def test_flag_off_distribution_matches_table(formation):
    roles = formation_roles.formation_roles(formation, flex=False)
    assert (roles[2], roles[3], roles[4]) == EXPECTED_234[formation], formation


@pytest.mark.parametrize("formation", constants.ALLOWED_FORMATIONS)
def test_all_roles_in_four_role_set(formation):
    roles = formation_roles.formation_roles(formation, flex=False)
    assert set(roles) == {0, 1, 2, 3, 4}
    assert all(r in ROLE_SET for r in roles.values()), roles


@pytest.mark.parametrize("formation", constants.ALLOWED_FORMATIONS)
def test_flag_on_keeps_gk_def_and_still_loads_concrete_roles(formation):
    # Flag ON: 0/1 still GK/DEF; 2/3/4 get a CONCRETE starting role (never
    # GK) so a body always loads, but are marked flexible.
    roles = formation_roles.formation_roles(formation, flex=True)
    assert roles[0] == "GK" and roles[1] == "DEF"
    for pid in (2, 3, 4):
        assert roles[pid] in {"DEF", "MID", "FWD"}
        assert roles[pid] != "GK"
        assert formation_roles.is_flexible(pid, flex=True) is True


def test_is_flexible_only_for_234_and_only_when_flag_on():
    for pid in (0, 1):
        assert formation_roles.is_flexible(pid, flex=True) is False
    for pid in (2, 3, 4):
        assert formation_roles.is_flexible(pid, flex=False) is False
        assert formation_roles.is_flexible(pid, flex=True) is True


def test_unknown_formation_falls_back_without_crashing():
    roles = formation_roles.formation_roles("9-9-9", flex=False)
    assert roles[0] == "GK" and roles[1] == "DEF"
    assert set(roles) == {0, 1, 2, 3, 4}


def test_formation_roles_is_a_shared_module():
    deploy_all = importlib.reload(importlib.import_module("deploy_all"))
    assert "formation_roles.py" in deploy_all.SHARED_MODULES
