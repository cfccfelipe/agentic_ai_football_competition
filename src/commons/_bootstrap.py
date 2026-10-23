"""Bootstrap helper — sets up sys.path so the shared commons kernel is importable.

Usage (at the very top of each agent's main.py):

    import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "commons")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "commons")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "commons")); from _bootstrap import setup_commons_path; setup_commons_path(__file__)

Or more readably as two lines:
    import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "commons")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "commons")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "commons"))
    from _bootstrap import setup_commons_path; setup_commons_path(__file__)
"""

import os
import sys


def setup_commons_path(caller_file: str) -> None:
    """Add the correct commons/ directory to sys.path.

    Works for all three layouts the caller can present:
      - Sibling / deployed (AgentCore): commons/ sits next to the caller file
        (deploy_all.py stages commons/ into the agent dir root) → ./commons
      - Intermediate: commons/ one level up from the caller → ../commons
      - Local dev: agents/commons/ is three levels up from agent/src/main.py
        → ../../../commons

    The first existing candidate (in that order) wins; it is normalized and
    inserted on sys.path only if not already present (dedupe).
    """
    here = os.path.dirname(os.path.abspath(caller_file))
    candidates = (
        os.path.join(here, "commons"),                       # sibling ./commons (deployed)
        os.path.join(here, "..", "commons"),                 # ../commons (intermediate)
        os.path.join(here, "..", "..", "..", "commons"),     # ../../../commons (local dev)
    )

    commons_dir = next(
        (c for c in candidates if os.path.isdir(c)),
        candidates[-1],  # fall back to the local-dev path if none exist
    )

    # Avoid duplicates
    commons_dir = os.path.normpath(commons_dir)
    if commons_dir not in sys.path:
        sys.path.insert(0, commons_dir)
