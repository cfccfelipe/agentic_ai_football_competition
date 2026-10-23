"""Bootstrap helper — sets up sys.path so the shared commons kernel is importable.

Usage (at the very top of each agent's main.py):

    import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "commons")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "commons")); from _bootstrap import setup_commons_path; setup_commons_path(__file__)

Or more readably as two lines:
    import os, sys; sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "commons")); sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "..", "commons"))
    from _bootstrap import setup_commons_path; setup_commons_path(__file__)
"""

import os
import sys


def setup_commons_path(caller_file: str) -> None:
    """Add the correct commons/ directory to sys.path.

    Works for both layouts:
      - Deployed (AgentCore): agent/commons/ sits next to agent/src/
      - Local dev: agents/commons/ is three levels up from agent/src/main.py
    """
    here = os.path.dirname(os.path.abspath(caller_file))
    commons_deployed = os.path.join(here, "..", "commons")              # agent/commons  (AgentCore)
    commons_local = os.path.join(here, "..", "..", "..", "commons")     # agents/commons (local dev)

    commons_dir = commons_deployed if os.path.isdir(commons_deployed) else commons_local

    # Avoid duplicates
    commons_dir = os.path.normpath(commons_dir)
    if commons_dir not in sys.path:
        sys.path.insert(0, commons_dir)
