"""Public HTTP API."""
from __future__ import annotations

from flask import Blueprint, current_app, jsonify, request

from ..agent import service as agent_service
from ..agent.llm import available_providers
from ..extensions import db
from ..services import chat_service, token_service
from ..services.errors import AppError

bp = Blueprint("api", __name__, url_prefix="/api")


@bp.get("/health")
def health():
    try:
        db.session.execute(db.text("SELECT 1"))
        db_ok = True
    except Exception:  # noqa: BLE001
        db.session.rollback()
        db_ok = False
    return jsonify(
        {
            "status": "ok" if db_ok else "degraded",
            "database": db_ok,
            "llm": {
                "provider": current_app.config["LLM_PROVIDER"],
                "model": current_app.config["LLM_MODEL"],
                "available_providers": available_providers(),
            },
            "mcp_url": current_app.config["GITHUB_MCP_URL"],
            "write_mode": current_app.config["AGENT_WRITE_MODE"],
            "history_limit": current_app.config["CHAT_HISTORY_LIMIT"],
        }
    ), (200 if db_ok else 503)


@bp.post("/chat")
def chat():
    """Send a prompt to the agent.

    Body:
      user_id     (required) your identifier for the caller
      message     (required) the instruction, e.g. "add retry logic to client.py"
      session_id  (optional) continue an existing conversation
      repo        (optional) "owner/repo" target for this conversation
      llm         (optional) {"provider": ..., "model": ..., "temperature": ...}
    """
    body = request.get_json(silent=True) or {}
    user_id = (body.get("user_id") or "").strip()
    message = (body.get("message") or body.get("prompt") or "").strip()
    if not user_id:
        raise AppError("'user_id' is required.")
    if not message:
        raise AppError("'message' is required.")

    cfg = current_app.config

    user = token_service.get_or_create_user(user_id)
    access_token = token_service.get_access_token(user)
    session = chat_service.get_or_create_session(
        user, body.get("session_id"), body.get("repo")
    )

    history_rows = chat_service.recent_messages(session, int(cfg["CHAT_HISTORY_LIMIT"]))
    history = chat_service.to_langchain_messages(history_rows)

    agent_request = agent_service.build_request(
        access_token=access_token,
        user_message=message,
        history=history,
        config=cfg,
        repo=session.repo_full_name,
        github_login=user.credential.github_login if user.credential else None,
        llm_overrides=body.get("llm") or {},
    )

    # Persist the user turn before running, so a failed run is still recorded.
    chat_service.add_message(session, "user", message)
    db.session.commit()

    result = agent_service.run_agent(
        agent_request, cfg, timeout=float(cfg["AGENT_TIMEOUT_SECONDS"])
    )

    chat_service.add_message(session, "assistant", result.reply, result.tool_calls)
    db.session.commit()

    return jsonify(
        {
            "session_id": session.id,
            "repo": session.repo_full_name,
            "reply": result.reply,
            "tool_calls": result.tool_calls,
            "history_used": len(history),
        }
    )


@bp.get("/sessions")
def list_sessions():
    user_id = (request.args.get("user_id") or "").strip()
    if not user_id:
        raise AppError("Query parameter 'user_id' is required.")
    user = token_service.get_or_create_user(user_id)
    db.session.commit()
    return jsonify({"sessions": [s.to_dict() for s in chat_service.list_sessions(user)]})


@bp.get("/sessions/<session_id>/messages")
def session_messages(session_id: str):
    user_id = (request.args.get("user_id") or "").strip()
    if not user_id:
        raise AppError("Query parameter 'user_id' is required.")
    user = token_service.get_or_create_user(user_id)
    db.session.commit()
    session = chat_service.get_session(user, session_id)
    return jsonify(
        {
            "session": session.to_dict(),
            "messages": [m.to_dict() for m in session.messages],
        }
    )


@bp.get("/tools")
def list_tools():
    """Debug helper: which GitHub MCP tools this user's token exposes."""
    user_id = (request.args.get("user_id") or "").strip()
    if not user_id:
        raise AppError("Query parameter 'user_id' is required.")
    user = token_service.get_or_create_user(user_id)
    access_token = token_service.get_access_token(user)
    db.session.commit()
    return jsonify({"tools": agent_service.describe_tools(access_token, current_app.config)})
