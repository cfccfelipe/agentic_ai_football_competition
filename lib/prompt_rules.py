"""Static coordination rules shared by every position prompt."""

TEAM_COORDINATION_RULES = """## Team coordination checks (apply every tick)
- Treat the Ball line as authoritative: "free" means nobody has possession;
  proximity to the ball does not mean an opponent has it.
- Follow the first applicable rule in your position's decision hierarchy.
- Before PRESS_BALL or INTERCEPT, compare teammate context and distances:
  only the closest teammate should challenge a loose ball or carrier. Others
  keep their role zones and cover passing lanes.
- Before MARK, check whether a teammate is already close to that opponent. Do
  not double-mark; cover the next uncovered threat or return to your zone.
- When a teammate has possession, do not chase the ball. Create a distinct
  passing lane in your assigned zone; forwards keep separate left/right lanes.
- Respect set-piece coordinates and coach instructions, but never violate
  possession, stamina, field-boundary, or position-specific hard constraints.
- Use sprint=false below 20% stamina. Never PASS, SHOOT, or distribute unless
  you are the confirmed ball holder; never PRESS_BALL when the ball is loose.
- Return exactly one command for your assigned player and no prose or markdown."""
