"""Create Strands agents backed by the project's AgentCore MCP gateway."""

import os

from strands import Agent
from strands.models import BedrockModel
from strands.tools.mcp.mcp_client import MCPClient
from mcp.client.streamable_http import streamablehttp_client


GATEWAY_URL_ENV = "AGENTCORE_GATEWAY_TACTICAL_TOOLS_URL"


def _gateway_transport():
    gateway_url = os.environ.get(GATEWAY_URL_ENV)
    if not gateway_url:
        raise RuntimeError(
            f"{GATEWAY_URL_ENV} is missing. Deploy the AgentCore project "
            "with its tactical-tools gateway."
        )
    headers = {}
    access_token = os.environ.get("GATEWAY_ACCESS_TOKEN")
    if access_token:
        headers["Authorization"] = f"Bearer {access_token}"
    return streamablehttp_client(gateway_url, headers=headers)


def create_gateway_agent(
    system_prompt: str,
    model_id: str = "us.amazon.nova-lite-v1:0",
) -> tuple[Agent, MCPClient]:
    """Create an agent with the tools exposed by the deployed MCP gateway."""
    mcp_client = MCPClient(_gateway_transport)
    with mcp_client:
        tools = mcp_client.list_tools_sync()
    if not tools:
        raise RuntimeError("The tactical-tools gateway returned no tools.")

    agent = Agent(
        model=BedrockModel(model_id=model_id),
        system_prompt=system_prompt,
        tools=tools,
    )
    return agent, mcp_client
