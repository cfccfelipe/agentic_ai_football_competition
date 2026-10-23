# Tactical Tools — call one before a risky action, then decide with facts

You are given four deterministic tools. They are NOT optional flavor — they replace a
guess with real math. Before a risky action, call the matching tool ONCE, read its
result, then return exactly ONE JSON-array command for your player
(Decision Priority item 4: consult the tactical tools, then PASS or SHOOT).

- evaluate_shot            — before any SHOOT (especially long attempts): is this shot worth taking?
- calculate_pass_options   — before a PASS: which lanes are open and valuable?
- find_open_space          — when off the ball and choosing where to MOVE_TO.
- get_defensive_assignment — when defending: who to MARK / PRESS_BALL / cover.

A team strategy is ALREADY chosen for this tick and appears below. Follow it. You have at
most a couple of tool calls this tick — spend them on the decision that matters, then emit
one JSON-array command for your player only.
