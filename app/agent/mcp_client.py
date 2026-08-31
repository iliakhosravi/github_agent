"""GitHub MCP connection.

The agent talks to GitHub only through the remote GitHub MCP server
(https://api.githubcopilot.com/mcp/). One MCP session is opened per chat
request and carries that user's own token in the Authorization header, so the
agent's reach is exactly the reach of the token -- nothing is shared between
users and no token is ever held in a long-lived process.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncIterator

from langchain_core.tools import BaseTool
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain_mcp_adapters.tools import load_mcp_tools

log = logging.getLogger(__name__)

SERVER_NAME = "github"


def build_headers(
    access_token: str, toolsets: str | None = None, read_only: bool = False
) -> dict[str, str]:
    headers = {"Authorization": f"Bearer {access_token}"}
    toolsets = (toolsets or "").strip()
    if toolsets and toolsets.lower() != "all":
        # Limiting the toolset keeps the tool list (and the prompt) small.
        headers["X-MCP-Toolsets"] = ",".join(
            part.strip() for part in toolsets.split(",") if part.strip()
        )
    if read_only:
        headers["X-MCP-Readonly"] = "true"
    return headers


def build_connection(
    url: str,
    access_token: str,
    *,
    toolsets: str | None = None,
    read_only: bool = False,
    timeout: float = 60.0,
) -> dict:
    return {
        "transport": "streamable_http",
        "url": url,
        "headers": build_headers(access_token, toolsets, read_only),
        "timeout": timeout,
    }


@asynccontextmanager
async def github_tools(
    *,
    url: str,
    access_token: str,
    toolsets: str | None = None,
    read_only: bool = False,
    timeout: float = 60.0,
) -> AsyncIterator[list[BaseTool]]:
    """Open an MCP session and yield the GitHub tools as LangChain tools.

    The session stays open for the whole agent loop, so multi-step work
    (read file -> create branch -> commit -> open PR) runs over one connection.
    """
    connection = build_connection(
        url, access_token, toolsets=toolsets, read_only=read_only, timeout=timeout
    )
    client = MultiServerMCPClient({SERVER_NAME: connection})
    async with client.session(SERVER_NAME) as session:
        tools = await load_mcp_tools(session)
        log.info("Loaded %d tools from the GitHub MCP server", len(tools))
        yield tools
