# Implementation Plan — Markdown-Only Tactics Tuning (Lighting Cloud)

MARKDOWN-ONLY task. Edit ONLY the files listed below (all under the worktree root
`c:\Users\FelipeCortes\agentic_ai_football_competition\.worktrees\tactics-tuning`). Zero
Python edits. Do NOT touch any `.py`, `cdk/`, `Makefile`, `.env`, `deploy_all.py`,
`src\governance\guardrails.md` (fixed rules), or `src\plugins\general\skill.md` (the MCP
tool scripts index — not in scope).

## Why these changes (decided direction, not re-decided here)
Real match: Lighting Cloud LOST 1-0, conceded at minute 4. Command mix too reactive (Press
36%, Pass 7%, Shoot 4%), 6 shots / 0 on target, possession 46%, sat too deep, planner went
defensive on a 1-0 at gameTime 120. Coach: cut PRESS_BALL, raise PASS/possession. Plus a
CRITICAL situational-awareness layer: Nova Micro is small and loses track of (a) attack vs
defend phase, (b) which way it attacks / where its goal is, (c) teammates vs opponents, and
(d) its own zone. Every change below serves: fix shooting, less press + more pass, more
ambition / smarter stamina, planner that doesn't over-trigger defensive, and an explicit
orient-first foundation under all of it.

## Hard constraints every edited file must preserve (verified against tests)
- Keep the literal tokens `{player_id}` and `{formation}` wherever they already appear
  (doubled braces `{{ }}` inside the `## Response` JSON example are literal — keep them).
- Keep the `## Response` section and its line containing the words "JSON array" with the
  single-command contract ("exactly ONE command"). `test_discover_strategy.py` rejects a
  body whose "JSON array" line is altered; keep the phrase verbatim.
- Only ever reference VALID_COMMANDS tokens in bodies: MOVE_TO, PASS, SHOOT, SLIDE_TACKLE,
  PRESS_BALL, INTERCEPT, MARK, FOLLOW_PLAYER, GK_DISTRIBUTE, SET_STANCE, CLEAR_OVERRIDE,
  RESET. Never invent a command token.
- Strategy files (`src\plugins\strategies\*.md`) keep YAML frontmatter with `name`,
  `type: strategy`, `formation`, `description` — all four keys, valid YAML, the `>` folded
  block for `description`. Keep formations exactly: aggressive `1-0-3`, balanced `1-2-1`,
  defensive `3-0-1` (do NOT change them — `test_e2e_tick.py` / `test_plugin_loader.py`
  assert these exact strings render in the composed prompt).
- Position index files (`src\plugins\<pos>\skill.md`) keep frontmatter `name`,
  `type: position`, `description`. They are navigation-only (not loaded at runtime) — edit
  only their prose so it stays in sync with the rewritten strategy descriptions.
- No URLs, no prompt-injection phrases (e.g. "ignore previous instructions"), no secrets —
  the drop-strategy content validator rejects these and we keep bodies clean regardless.
- Keep each body pointed at its OWN role (gk=GK player 0, def=DEF player 1, mid=MID player
  2, fwd1=Forward 1 player 3, fwd2=Forward 2 player 4). Never cross-wire roles or ids.

## CRITICAL gotcha for tool_catalog.md (test-enforced)
`tests\test_plugin_loader_static.py::test_tool_catalog_names_exactly_the_four_tools` scans
`tool_catalog.md` with regex `\b[a-z]+_[a-z_]+\b` and asserts the ONLY lower_snake_case
tokens present are the four tool names (`evaluate_shot`, `calculate_pass_options`,
`find_open_space`, `get_defensive_assignment`) plus `aim_location`. Therefore in
tool_catalog.md you must NOT introduce any other lower_snake_case token — write orient-first
guidance with plain words / hyphens / capitals instead (e.g. "team id", "ATTACK phase",
"my goal", NOT `team_id`, `attack_phase`, `my_goal`, `player_id`, `possession_line`). Also
`test_tool_catalog_contradicts_no_guardrail_rule` requires the lowercased catalog to NOT
contain the substrings "own goal", "two commands", "multiple commands", and not both "prose"
and "no prose". The snake_case restriction applies ONLY to tool_catalog.md — the position/
strategy body files are NOT scanned this way, so `team_id`-style wording is fine in bodies
(but prefer the plain-language phrasing there too for Nova Micro clarity).

---

## Shared orient-first layer (do this FIRST — it is the foundation)

- [ ] 1. Add a shared "Orient first (every tick)" block to `src\governance\tool_catalog.md`
      so every agent inherits it via the static base (DRY). Insert a short section ABOVE or
      just below the existing intro, before the four tool bullets. Content: a tight 3-step
      checklist the agent runs before choosing a command — (a) read your own team id from
      the state to know which way you attack and where your goal is (HOME attacks toward +x,
      opponent goal at x=+55, own goal x=-55; AWAY attacks toward -x, opponent goal x=-55,
      own goal x=+55) — never aim at a fixed corner regardless of side; (b) read the ball
      possession line — if a teammate (MY) holds the ball it is the ATTACK phase, if an
      opponent (OPP) holds it it is the DEFEND phase, if loose then whoever is closer (recover
      if it is in our half); (c) identify MY (teammates: ids 0 GK, 1 DEF, 2 MID, 3 FWD1, 4
      FWD2) vs OPP before acting — PASS and FOLLOW_PLAYER target teammates; MARK, PRESS_BALL,
      INTERCEPT, SLIDE_TACKLE target opponents; never press/mark a teammate or pass to an
      opponent. Keep it to a handful of lines (Nova Micro budget). Reinforce "call the
      matching tool once before a risky PASS/SHOOT, then emit one command" (already present).
      MUST obey the snake_case / forbidden-substring rules in the CRITICAL gotcha above:
      write "team id", "ATTACK phase", "my goal", avoid "own goal"/"two commands"/"multiple
      commands", do not add any new lower_snake_case token. Keep the four tool names exact.
      Files: src\governance\tool_catalog.md
      Verify: `uv run pytest -q tests/test_plugin_loader_static.py tests/test_plugin_loader.py tests/test_deploy_contract.py` — all pass (confirms the four-tools-only regex, no-contradiction, and static-base assertions still hold).

---

## Forwards — fix shooting + orientation + ambition (highest priority)

- [ ] 2. Rewrite `src\plugins\fwd1\balanced.md` and `src\plugins\fwd2\balanced.md` (same
      change pattern, two files; keep fwd1 = Forward 1 / left-center, fwd2 = Forward 2 /
      right, do not swap their teammate lists or example aim corners). In "Your Role":
      (a) SHOOTING — tell the forward to call `evaluate_shot` before shooting and SHOOT only
      when it reports a worthwhile chance (reasonable placement/position), aiming at the
      OPPONENT goal mouth for YOUR team (derived from your team id, per the orient-first
      checklist) using the returned aim corner/zone (TL/TR/BL/BR/CENTER) and the recommended
      power — do NOT blast fixed-corner long shots. (b) AMBITION — push higher up the pitch
      and look for the opponent goal, make runs into the box, do not camp in our half.
      (c) PRESS→PASS — keep high pressing purposeful (press the ball carrier at the right
      moment, not constant chasing); when on the ball consult `calculate_pass_options` and
      build possession rather than hitting it long. (d) STAMINA — sprint for key attacking
      runs and recoveries; stop over-conserving. (e) Add a one-line phase cue ("MY player
      holds ball -> ATTACK; OPP holds -> drop and defend; loose -> nearest recovers").
      Keep `{player_id}`, `{formation}`, the `## Response` JSON-array contract, and keep each
      file's own teammate-context list and example corner (fwd1 TR-ish, fwd2 BL-ish is fine).
      Files: src\plugins\fwd1\balanced.md, src\plugins\fwd2\balanced.md
      Verify: `uv run pytest -q tests/test_plugin_loader.py tests/test_discover_strategy.py` — pass (bodies still load; "JSON array" line + tokens intact).

- [ ] 3. Rewrite `src\plugins\fwd1\aggressive.md` and `src\plugins\fwd2\aggressive.md` (same
      pattern, two files). Remove the broken "Power shots at 1.0 — always shoot with maximum
      power" and "take speculative shots from any distance" guidance: replace with
      "call `evaluate_shot` first; shoot when it says the chance is good, using its
      recommended aim and power at the OPPONENT goal for YOUR team" — still aggressive and
      shot-hungry, but on-target not speculative. Soften "PRESS_BALL at maximum intensity"
      to purposeful high pressing of the ball carrier; add "when on the ball, a quick
      `calculate_pass_options` one-two is better than a blind blast". Keep the aggressive
      identity (high line, runs behind, sprint for attacks). Add the same one-line phase cue
      and the aim-at-opponent-goal-by-team-id reminder. Update the `## Response` example so
      power is a sensible value (e.g. 0.9), NOT 1.0, and the aim corner stays a corner token.
      Keep `{player_id}`, `{formation}`, `## Response` "JSON array" contract, per-file
      teammate lists.
      Files: src\plugins\fwd1\aggressive.md, src\plugins\fwd2\aggressive.md
      Verify: `uv run pytest -q tests/test_plugin_loader.py tests/test_plugin_loader_static.py` — pass.

- [ ] 4. Lightly revise `src\plugins\fwd1\defensive.md` and `src\plugins\fwd2\defensive.md`
      (same pattern, two files). These stay defense-first (deep tracker role for protecting a
      late lead), but: (a) when the ball does fall to them in the opponent box, still use
      `evaluate_shot` and aim at the OPPONENT goal (fix the silent-miss risk) rather than a
      fixed corner; (b) replace "PASS backwards immediately / pass back" reflex with "keep the
      ball — use `calculate_pass_options` and pass to a teammate (MY) to retain possession,
      backward only if genuinely pressed" so even the defensive mode stops gifting possession;
      (c) add the one-line phase + team-id orientation cue and the who-is-who reminder
      (MARK/INTERCEPT target OPP, PASS targets MY). Keep stamina conservative here (this mode
      IS for protecting a lead), keep `SET_STANCE` Defend. Keep tokens + Response contract.
      Files: src\plugins\fwd1\defensive.md, src\plugins\fwd2\defensive.md
      Verify: `uv run pytest -q tests/test_plugin_loader.py` — pass.

---

## Midfield — shooting judgment + press→pass + orientation

- [ ] 5. Rewrite `src\plugins\mid\balanced.md`. Shift the default away from pressing toward
      possession: make PASS the first instinct when on the ball (consult
      `calculate_pass_options`, pass to the best MY target, forward when on, recycle when
      not), keep PRESS_BALL purposeful (press the carrier at the right moment, not constant).
      For the "SHOOT from distance" line, require `evaluate_shot` first and aim at the
      OPPONENT goal for YOUR team. Push the shape a touch higher / be more progressive (less
      passive), stamina used for key transitions. Add the phase cue + team-id orientation +
      who-is-who reminder. Keep `{player_id}`, `{formation}`, Response contract, teammate list.
      Files: src\plugins\mid\balanced.md
      Verify: `uv run pytest -q tests/test_plugin_loader.py` — pass.

- [ ] 6. Rewrite `src\plugins\mid\aggressive.md`. Replace "SHOOT at every opportunity / take
      long shots freely" with "call `evaluate_shot` first and shoot when it says the chance is
      good, aiming at the OPPONENT goal for YOUR team" — stays an attacking second-striker mid
      but on-target. Keep forward thrust and high press purposeful (press the carrier), and
      replace "PASS only forward, never backwards" with "prefer forward/through balls via
      `calculate_pass_options`, but recycle sideways/back to keep possession rather than
      forcing a bad ball" (supports the possession directive without killing ambition). Add
      phase + team-id + who-is-who cues. Keep tokens + Response contract; make the example
      SHOOT power sensible (not forced 1.0).
      Files: src\plugins\mid\aggressive.md
      Verify: `uv run pytest -q tests/test_plugin_loader.py` — pass.

- [ ] 7. Lightly revise `src\plugins\mid\defensive.md`. Keep it defense-first (extra defender
      for protecting a lead) but soften the possession-gifting reflex: replace "When you win
      the ball, PASS to the defender or GK. Never pass forward." with "when you win it, keep
      it — use `calculate_pass_options` and pick the best MY teammate; go forward if a safe
      lane is open, recycle only if not". Keep "NEVER shoot" and the compact block posture.
      Add phase + team-id + who-is-who cues (MARK/INTERCEPT -> OPP; PASS -> MY). Keep tokens +
      Response contract.
      Files: src\plugins\mid\defensive.md
      Verify: `uv run pytest -q tests/test_plugin_loader.py` — pass.

---

## Defenders — press→pass + orientation + zone discipline

- [ ] 8. Rewrite `src\plugins\def\balanced.md`. Reduce PRESS_BALL as a default: press only
      when an opponent carries the ball into your zone (purposeful), else hold defensive shape
      (anti-ball-magnet, consistent with guardrails §5). Raise possession: when you win it,
      consult `calculate_pass_options` and build out with a PASS to the best MY teammate
      instead of clearing/hoofing. Add phase cue (MY holds -> support the attack by offering a
      lane; OPP holds -> mark/press purposefully), team-id orientation (know your own goal and
      your defensive third in x), and who-is-who (MARK/INTERCEPT/SLIDE_TACKLE -> OPP; PASS ->
      MY). Keep stamina for crucial defensive sprints. Keep tokens + Response contract +
      teammate list.
      Files: src\plugins\def\balanced.md
      Verify: `uv run pytest -q tests/test_plugin_loader.py` — pass.

- [ ] 9. Lightly revise `src\plugins\def\aggressive.md` and `src\plugins\def\defensive.md`
      (two files, each keeps its distinct identity — aggressive = attacking defender joining
      attacks; defensive = ultra-defensive sweeper). For BOTH: (a) temper "PRESS_BALL at
      maximum intensity / press hard" to purposeful pressing of the carrier; (b) when winning
      the ball, prefer keeping possession via `calculate_pass_options` to the best MY teammate
      over a blind clearance (aggressive: forward through balls; defensive: safe retention,
      not a panic hoof); (c) add phase + team-id orientation + who-is-who cues consistent with
      guardrails §5 zone discipline. In def\aggressive keep the high line and the "SHOOT from
      distance" line but gate it behind `evaluate_shot` aimed at the OPPONENT goal. Keep def\
      defensive's "NEVER cross halfway", "NEVER shoot", SET_STANCE Defend, and its existing
      good pattern "never move forward past x=-45 (if HOME) or x=45 (if AWAY)". Keep tokens +
      Response contracts.
      Files: src\plugins\def\aggressive.md, src\plugins\def\defensive.md
      Verify: `uv run pytest -q tests/test_plugin_loader.py` — pass.

---

## Goalkeeper — orientation + distribution for possession

- [ ] 10. Lightly revise the three GK bodies `src\plugins\gk\balanced.md`,
      `src\plugins\gk\aggressive.md`, `src\plugins\gk\defensive.md` (same pattern, three
      files; each keeps its distinct identity — balanced line-keeper, aggressive sweeper, deep
      defensive). For all three: add the team-id orientation cue (your goal is at x=-55 if
      HOME / x=+55 if AWAY; defend it) and the who-is-who cue (GK_DISTRIBUTE / PASS target MY
      teammates by id). Nudge GK_DISTRIBUTE toward keeping possession — distribute to the best
      open MY teammate (consult `calculate_pass_options` when it helps) rather than a rushed
      long hoof — to support the possession directive, while keeping each mode's posture
      (defensive GK stays deep, "never leave line"; aggressive stays the sweeper-keeper).
      Generalize any hard-coded direction the way gk\defensive already does (HOME vs AWAY).
      Keep the `## Priority` sections, tokens, and Response contracts.
      Files: src\plugins\gk\balanced.md, src\plugins\gk\aggressive.md, src\plugins\gk\defensive.md
      Verify: `uv run pytest -q tests/test_plugin_loader.py tests/test_plugin_loader_bundle_layout.py` — pass.

---

## Planner-facing strategy descriptions (controls strategy choice by the LLM path)

- [ ] 11. Rewrite the `description` field of `src\plugins\strategies\balanced.md`,
      `src\plugins\strategies\aggressive.md`, `src\plugins\strategies\defensive.md` (three
      files). Keep ALL frontmatter keys and the exact `formation` values (1-2-1 / 1-0-3 /
      3-0-1); change ONLY the `description` wording. New intent, so the planner stops jumping
      to defensive on a slim/early lead:
      - balanced: the confident DEFAULT for level or slim-margin games with time left —
        possession-based, push the shape up, attack with structure. Explicitly the choice when
        no clear late-lead-protection condition holds.
      - aggressive: choose when chasing (losing) OR when level and we want to win — not only
        when losing. Describe it as high, possession-into-attack pressure, not reckless.
      - defensive: ONLY for protecting a CLEAR lead LATE in the match. State plainly that
        gameTime is in SECONDS and matches can be long, so an early/low gameTime (e.g. ~120s)
        is NOT late — do not drop into defensive on a slim or early lead.
      Keep each `description` as a valid YAML folded block (`>`), single paragraph, no colons
      that would break YAML (or quote them). Do NOT add new frontmatter keys.
      Files: src\plugins\strategies\balanced.md, src\plugins\strategies\aggressive.md, src\plugins\strategies\defensive.md
      Verify: `uv run pytest -q tests/test_registry.py tests/test_e2e_tick.py tests/test_planner.py tests/test_drop_strategy_zero_code.py` — pass. NOTE: the planner's hard rule thresholds live in `planner.py` (NOT edited); `test_planner.py` / `test_e2e_tick.py` assert the rule path (losing-late->aggressive at gameTime 80, winning-late->defensive at 82) and only that each strategy name appears in the descriptions block — they do NOT assert specific description sentences, so rewording is safe as long as the three names remain present and frontmatter stays valid.

---

## Position index files (keep narration in sync with the rewritten strategies)

- [ ] 12. Update the prose of the five position index files to match the new strategy
      descriptions from item 11 (same change pattern, five files). Keep frontmatter
      (`name`, `type: position`, `description`) intact. In each file's "Strategy files for
      this position" list, keep the formation labels (1-0-3 / 1-2-1 / 3-0-1) but rewrite the
      "Read when ..." narration so it no longer says things that push to defensive on a slim/
      early lead: balanced = confident default for level/slim-margin with time left;
      aggressive = chasing OR level-and-going-for-it; defensive = protecting a CLEAR lead LATE
      (note gameTime is in seconds; ~120s is early, not late). Keep each file's per-position
      one-liner about what that role does in each mode (GK sweeper vs deep, etc.). Do not
      contradict the planner-facing descriptions or guardrails.
      Files: src\plugins\gk\skill.md, src\plugins\def\skill.md, src\plugins\mid\skill.md, src\plugins\fwd1\skill.md, src\plugins\fwd2\skill.md
      Verify: `uv run pytest -q tests/test_registry.py` — pass (index files are navigation-only; this confirms discovery still works).

---

## Final gate

- [ ] 13. Run the full suite from the worktree root and confirm all 173 tests pass. If any
      test fails because it asserts specific body/description wording you changed, first
      recheck whether the change was actually necessary; if it was, update the ASSERTION
      sensibly WITHOUT weakening a guarantee (e.g. keep asserting the four tool names, the
      "JSON array" contract, the formation strings, and role/player-id markers — never delete
      those checks). Based on this exploration, NO existing test asserts the specific tactical
      prose being changed: the enforced invariants are the four-tool-only regex and no-
      contradiction rules in `test_plugin_loader_static.py` (tool_catalog.md only), the
      "JSON array" response line and valid command tokens in `test_discover_strategy.py`, the
      formation strings and guardrail markers in `test_plugin_loader*.py` / `test_e2e_tick.py`,
      and the presence of the three strategy names in the descriptions block
      (`test_registry.py`, `test_e2e_tick.py`). So no assertion edit is expected — if one is
      needed it signals an over-reaching wording change to reconsider.
      Files: (none — verification only)
      Verify: `uv run pytest -q` run from `c:\Users\FelipeCortes\agentic_ai_football_competition\.worktrees\tactics-tuning` — expect `173 passed`.
