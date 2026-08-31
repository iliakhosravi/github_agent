"""Smoke tests that need no GitHub token and no LLM key.

Run with:  pytest -q
"""
from __future__ import annotations

import pytest

from app import create_app
from app.agent.mcp_client import build_headers
from app.agent.prompts import build_system_prompt
from app.config import TestConfig, normalize_db_url
from app.extensions import db
from app.security.crypto import decrypt, encrypt
from app.services import chat_service, token_service


@pytest.fixture()
def app():
    application = create_app(TestConfig)
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app):
    return app.test_client()


def test_db_url_normalisation():
    assert normalize_db_url("postgres://u:p@h/db").startswith("postgresql+psycopg://")
    assert normalize_db_url("postgresql://u:p@h/db").startswith("postgresql+psycopg://")


def test_health(client):
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.get_json()["database"] is True


def test_token_roundtrip(app):
    secret = "ghp_example_token_value"
    assert decrypt(encrypt(secret)) == secret


def test_chat_requires_token(client):
    resp = client.post("/api/chat", json={"user_id": "alice", "message": "hi"})
    assert resp.status_code == 401
    assert resp.get_json()["error"]["code"] == "github_token_missing"


def test_history_limit_keeps_last_three(app):
    user = token_service.get_or_create_user("alice")
    session = chat_service.get_or_create_session(user, repo="octocat/hello-world")
    for i in range(6):
        chat_service.add_message(session, "user" if i % 2 == 0 else "assistant", f"m{i}")
    db.session.commit()

    recent = chat_service.recent_messages(session, 3)
    assert [m.content for m in recent] == ["m3", "m4", "m5"]

    converted = chat_service.to_langchain_messages(recent)
    assert [m.type for m in converted] == ["ai", "human", "ai"]


def test_mcp_headers():
    headers = build_headers("tok", "repos, issues", read_only=True)
    assert headers["Authorization"] == "Bearer tok"
    assert headers["X-MCP-Toolsets"] == "repos,issues"
    assert headers["X-MCP-Readonly"] == "true"
    assert "X-MCP-Toolsets" not in build_headers("tok", "all")


def test_system_prompt_modes():
    pr_prompt = build_system_prompt(write_mode="branch_pr", repo="a/b", github_login="x")
    assert "pull request" in pr_prompt
    assert "`a/b`" in pr_prompt

    ro_prompt = build_system_prompt(read_only=True)
    assert "READ-ONLY" in ro_prompt


def test_agent_loop_runs_tools_then_answers():
    """The graph should call a tool, feed the result back, and then answer.

    Uses a fake chat model and a fake tool -- no GitHub and no LLM key needed.
    """
    from langchain_core.language_models.fake_chat_models import GenericFakeChatModel
    from langchain_core.messages import AIMessage, HumanMessage
    from langchain_core.tools import tool

    from app.agent.graph import build_graph, collect_tool_calls, final_text
    from app.agent.runner import AsyncRunner

    @tool
    def get_file_contents(path: str) -> str:
        """Read a file from the repository."""
        return "print('hello')"

    class FakeModel(GenericFakeChatModel):
        def bind_tools(self, tools, **kwargs):  # noqa: ANN001, ANN003
            return self

    scripted = iter(
        [
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "get_file_contents", "args": {"path": "a.py"}, "id": "1"}
                ],
            ),
            AIMessage(content="Opened PR #7 from branch agent/fix."),
        ]
    )

    graph = build_graph(FakeModel(messages=scripted), [get_file_contents], "system")
    local_runner = AsyncRunner()
    try:
        state = local_runner.run(
            graph.ainvoke({"messages": [HumanMessage(content="fix a.py")]}), timeout=30
        )
    finally:
        local_runner.shutdown()

    assert collect_tool_calls(state["messages"]) == [
        {"name": "get_file_contents", "args": {"path": "a.py"}}
    ]
    assert final_text(state["messages"]) == "Opened PR #7 from branch agent/fix."


def test_auth_status_unknown_user(client):
    resp = client.get("/auth/status?user_id=nobody")
    assert resp.status_code == 200
    assert resp.get_json()["connected"] is False
