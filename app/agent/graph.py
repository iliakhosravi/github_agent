"""The LangGraph agent loop.

    START -> agent -> (tool calls?) -> tools -> agent -> ... -> END

Written explicitly rather than via `create_react_agent` so the system prompt,
the stop condition and the tool node stay easy to change.
"""
from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, AnyMessage, SystemMessage
from langchain_core.tools import BaseTool
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.prebuilt import ToolNode


class AgentState(TypedDict):
    messages: Annotated[list[AnyMessage], add_messages]


def build_graph(llm: BaseChatModel, tools: list[BaseTool], system_prompt: str):
    model = llm.bind_tools(tools) if tools else llm

    async def call_model(state: AgentState) -> dict[str, Any]:
        messages = [SystemMessage(content=system_prompt), *state["messages"]]
        response = await model.ainvoke(messages)
        return {"messages": [response]}

    def route(state: AgentState) -> str:
        last = state["messages"][-1]
        if getattr(last, "tool_calls", None):
            return "tools"
        return END

    graph = StateGraph(AgentState)
    graph.add_node("agent", call_model)
    graph.add_node("tools", ToolNode(tools))
    graph.add_edge(START, "agent")
    graph.add_conditional_edges("agent", route, {"tools": "tools", END: END})
    graph.add_edge("tools", "agent")
    return graph.compile()


def collect_tool_calls(messages: list[AnyMessage]) -> list[dict]:
    """Flatten the tool calls the agent made, for the API response and audit log."""
    calls: list[dict] = []
    for message in messages:
        for call in getattr(message, "tool_calls", None) or []:
            calls.append({"name": call.get("name"), "args": call.get("args", {})})
    return calls


def final_text(messages: list[AnyMessage]) -> str:
    for message in reversed(messages):
        if not isinstance(message, AIMessage) or message.tool_calls:
            continue
        content = message.content
        if isinstance(content, str):
            return content
        if isinstance(content, list):  # provider blocks (e.g. Anthropic)
            parts = [
                block.get("text", "")
                for block in content
                if isinstance(block, dict) and block.get("type") == "text"
            ]
            return "".join(parts)
    return ""
