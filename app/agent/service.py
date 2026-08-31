"""Orchestration: one chat turn = resolve token -> open MCP -> run graph -> persist.

Everything that needs the Flask application context (config, DB, decryption)
happens in the request thread; only the pure-async part is handed to the
background event loop.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AnyMessage, HumanMessage

from ..services.errors import UpstreamError
from .graph import build_graph, collect_tool_calls, final_text
from .llm import build_llm_from_config
from .mcp_client import github_tools
from .prompts import build_system_prompt
from .runner import runner

log = logging.getLogger(__name__)


@dataclass
class AgentRequest:
    """A fully resolved turn -- no Flask objects, safe to use off-thread."""

    access_token: str
    messages: list[AnyMessage]
    system_prompt: str
    mcp_url: str
    toolsets: str | None = None
    read_only: bool = False
    recursion_limit: int = 40
    llm_overrides: dict = field(default_factory=dict)


@dataclass
class AgentResult:
    reply: str
    tool_calls: list[dict]
    steps: int


async def _run(request: AgentRequest, llm) -> AgentResult:
    async with github_tools(
        url=request.mcp_url,
        access_token=request.access_token,
        toolsets=request.toolsets,
        read_only=request.read_only,
    ) as tools:
        graph = build_graph(llm, tools, request.system_prompt)
        state = await graph.ainvoke(
            {"messages": request.messages},
            config={"recursion_limit": request.recursion_limit},
        )

    messages = state["messages"]
    return AgentResult(
        reply=final_text(messages),
        tool_calls=collect_tool_calls(messages),
        steps=len(messages),
    )


def run_agent(request: AgentRequest, config, timeout: float | None = None) -> AgentResult:
    """Blocking entry point called from a Flask view."""
    llm = build_llm_from_config(config, request.llm_overrides)
    try:
        return runner.run(_run(request, llm), timeout=timeout)
    except UpstreamError:
        raise
    except Exception as exc:  # noqa: BLE001 - surfaced to the caller as 502
        log.exception("Agent run failed")
        raise UpstreamError(f"Agent run failed: {exc}") from exc


def build_request(
    *,
    access_token: str,
    user_message: str,
    history: list[AnyMessage],
    config,
    repo: str | None = None,
    github_login: str | None = None,
    llm_overrides: dict | None = None,
) -> AgentRequest:
    read_only = bool(config["GITHUB_MCP_READONLY"])
    return AgentRequest(
        access_token=access_token,
        messages=[*history, HumanMessage(content=user_message)],
        system_prompt=build_system_prompt(
            write_mode=config["AGENT_WRITE_MODE"],
            repo=repo,
            github_login=github_login,
            read_only=read_only,
        ),
        mcp_url=config["GITHUB_MCP_URL"],
        toolsets=config["GITHUB_MCP_TOOLSETS"],
        read_only=read_only,
        recursion_limit=int(config["AGENT_RECURSION_LIMIT"]),
        llm_overrides=llm_overrides or {},
    )


def describe_tools(access_token: str, config) -> list[dict[str, Any]]:
    """List the MCP tools currently visible with this token (useful for debugging)."""

    async def _list() -> list[dict[str, Any]]:
        async with github_tools(
            url=config["GITHUB_MCP_URL"],
            access_token=access_token,
            toolsets=config["GITHUB_MCP_TOOLSETS"],
            read_only=bool(config["GITHUB_MCP_READONLY"]),
        ) as tools:
            return [{"name": t.name, "description": (t.description or "")[:200]} for t in tools]

    try:
        return runner.run(_list(), timeout=60)
    except UpstreamError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise UpstreamError(f"Could not list MCP tools: {exc}") from exc
