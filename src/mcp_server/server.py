"""Local MCP server exposing the tactical analysis tools.

Registers the four deterministic scripts from plugins/general/scripts/ as MCP
tools over streamable-http transport, so a Strands agent can connect the same
way it connects to an AgentCore Gateway in production.

Run locally:
    uv run src/mcp_server/server.py
Inspect:
    uv run mcp dev src/mcp_server/server.py
"""

import os
import sys

# Make the general plugin's scripts importable.
_SCRIPTS = os.path.join(os.path.dirname(__file__), "..", "plugins", "general", "scripts")
sys.path.insert(0, os.path.normpath(_SCRIPTS))

from mcp.server.fastmcp import FastMCP

from calculate_pass_options import calculate_pass_options
from evaluate_shot import evaluate_shot
from find_open_space import find_open_space
from get_defensive_assignment import get_defensive_assignment

mcp = FastMCP("football-tactics")

mcp.tool()(calculate_pass_options)
mcp.tool()(evaluate_shot)
mcp.tool()(find_open_space)
mcp.tool()(get_defensive_assignment)


if __name__ == "__main__":
    # streamable-http so an agent connects over HTTP, mirroring the Gateway flow.
    mcp.run(transport="streamable-http")
