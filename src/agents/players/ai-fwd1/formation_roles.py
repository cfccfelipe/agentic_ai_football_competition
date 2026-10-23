"""Single source of truth for per-player ROLE assignment (dynamic roles).

The user's hard requirement: two agents are PINNED forever — player 0 is ALWAYS
the goalkeeper and player 1 is ALWAYS a defender — so there is always at least
one GK and one DEF regardless of formation or flag. The other three agents
(players 2, 3, 4) are FLEXIBLE: a flag decides whether they keep the formation's
remaining DEF-MID-FWD distribution (flag OFF) or may reason about and adapt
their own role for the situation (flag ON).

Single Responsibility: map a formation (+ flex flag) to ``{player_id: role}``
for ids 0..4, roles drawn from the 4-role set {GK, DEF, MID, FWD}. It builds no
prompts and talks to nothing. This is a NEW players/ runtime module, so it is
registered in deploy_all.SHARED_MODULES.

## How the distribution is derived (flag OFF)

A formation is the DEF-MID-FWD shape of the FOUR outfield players (the GK is not
counted). player 1 is the pinned DEF and consumes one DEF slot. The remaining
THREE players (2, 3, 4) fill the formation's LEFTOVER outfield slots in a fixed
order — DEF first, then MID, then FWD — so the assignment is deterministic and
formation-agnostic.

Worked example — ``2-1-1`` (2 DEF, 1 MID, 1 FWD outfield):
  pinned player 1 takes 1 DEF -> remaining = 1 DEF, 1 MID, 1 FWD for 2/3/4
  fill order DEF->MID->FWD: player 2=DEF, player 3=MID, player 4=FWD.

Edge formations:
- ``0-4-0`` has 0 DEF outfield, but player 1 is still pinned DEF (the structural
  back). The remaining 3 players take the leftover shape, which is all MID:
  2=MID, 3=MID, 4=MID. (player 1=DEF over-satisfies the 0-DEF line; the GK+DEF
  pin always wins over the formation's exact counts — that is the whole point of
  the pin.)
- ``1-1-1-1`` (a 4-way staggered 1 DEF, 1 MID, 1 FWD + 1 spread extra) has no
  single canonical DEF-MID-FWD triple for 2/3/4. We pick ONE deterministic fill:
  after the pinned DEF consumes the 1 DEF slot, the leftover is 1 MID + 2 FWD
  spread, giving 2=MID, 3=FWD, 4=FWD. Documented here and asserted in the test.

## Flag ON (flexible 2/3/4)

players 0/1 are untouched (GK/DEF). players 2/3/4 START from the same flag-OFF
distribution (so a concrete body always loads) but the returned mapping marks
them flexible so ``unified_agent`` can let each agent reason about its best role
for the situation. We expose that via ``formation_roles_flex`` returning, for
2/3/4, the string ``"FLEX"`` — while 0/1 stay the concrete GK/DEF. ``flex=True``
on ``formation_roles`` returns the concrete starting roles (never FLEX) so a body
always resolves; callers that want the FLEX marker use ``is_flexible``.
"""

from __future__ import annotations

# Formation name -> outfield (DEF, MID, FWD) counts for the 4 outfield players.
# Mirrors constants.ALLOWED_FORMATIONS / game-domain.md. 1-1-1-1 is the
# staggered spread; we encode it as (1, 1, 2) leftover intent after the pin
# (see module docstring) via an explicit override below.
_OUTFIELD_COUNTS = {
    "0-4-0": (0, 4, 0),
    "1-0-3": (1, 0, 3),
    "1-1-2": (1, 1, 2),
    "1-1-1-1": (1, 1, 2),  # staggered: deterministic 1 DEF / 1 MID / 2 FWD intent
    "1-2-1": (1, 2, 1),
    "2-0-2": (2, 0, 2),
    "2-1-1": (2, 1, 1),
    "3-0-1": (3, 0, 1),
}

_DEFAULT_FORMATION = "1-1-1-1"

# The three flexible player ids (2, 3, 4). 0 and 1 are hard-pinned.
FLEX_PLAYER_IDS = (2, 3, 4)


def _remaining_for_outfield(formation: str) -> list[str]:
    """Return the roles for players 2/3/4 under flag OFF, in id order.

    Takes the formation's outfield DEF-MID-FWD counts, subtracts the one DEF
    slot consumed by the pinned player 1, then fills three slots in DEF->MID->FWD
    order. Any shortfall (e.g. 0-4-0, where there is no leftover DEF) is filled
    from the next role so exactly three roles are always produced.
    """
    defs, mids, fwds = _OUTFIELD_COUNTS.get(formation, _OUTFIELD_COUNTS[_DEFAULT_FORMATION])
    # player 1 (pinned DEF) consumes one of the formation's DEF slots.
    remaining_def = max(0, defs - 1)
    pool: list[str] = (
        ["DEF"] * remaining_def + ["MID"] * mids + ["FWD"] * fwds
    )
    # Exactly three outfield players (2, 3, 4) remain to be assigned. Pad with
    # MID (the neutral link role) if the formation left fewer than three slots,
    # and truncate deterministically if it left more (fill DEF->MID->FWD order
    # already guarantees the extra are the FWD-most).
    while len(pool) < len(FLEX_PLAYER_IDS):
        pool.append("MID")
    return pool[: len(FLEX_PLAYER_IDS)]


def formation_roles(formation: str, flex: bool = False) -> dict[int, str]:
    """Return ``{player_id: role}`` for ids 0..4 for a formation.

    Invariants (ALWAYS, for every formation and both flag states):
      - player 0 -> "GK"
      - player 1 -> "DEF"
    players 2/3/4 take the formation's remaining DEF-MID-FWD distribution (see
    module docstring). ``flex`` does NOT change the returned concrete roles —
    they are the starting point either way so a body always loads; use
    ``is_flexible`` to know whether a player may adapt its role this tick.
    """
    roles: dict[int, str] = {0: "GK", 1: "DEF"}
    remaining = _remaining_for_outfield(formation)
    for pid, role in zip(FLEX_PLAYER_IDS, remaining):
        roles[pid] = role
    return roles


def is_flexible(player_id: int, flex: bool) -> bool:
    """True when this player may reason about/adapt its own role this tick.

    Only players 2/3/4 are ever flexible, and only when the flag is ON. players
    0 (GK) and 1 (DEF) are NEVER flexible — they are pinned forever.
    """
    return bool(flex) and player_id in FLEX_PLAYER_IDS
