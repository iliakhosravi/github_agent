"""Chat sessions and the short rolling memory replayed to the LLM."""
from __future__ import annotations

import json

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from ..extensions import db
from ..models import ChatMessage, ChatSession, User, utcnow
from .errors import NotFound


def get_or_create_session(
    user: User, session_id: str | None = None, repo: str | None = None
) -> ChatSession:
    if session_id:
        session = (
            db.session.query(ChatSession)
            .filter_by(id=session_id, user_id=user.id)
            .one_or_none()
        )
        if session is None:
            raise NotFound(f"Chat session '{session_id}' not found for this user.")
        # A repo passed on a later turn retargets the session.
        if repo and session.repo_full_name != repo:
            session.repo_full_name = repo
        return session

    session = ChatSession(
        user_id=user.id, repo_full_name=repo or user.default_repo
    )
    db.session.add(session)
    db.session.flush()
    return session


def recent_messages(session: ChatSession, limit: int) -> list[ChatMessage]:
    """The last `limit` stored messages, oldest first."""
    if limit <= 0:
        return []
    rows = (
        db.session.query(ChatMessage)
        .filter_by(session_id=session.id)
        .order_by(ChatMessage.id.desc())
        .limit(limit)
        .all()
    )
    return list(reversed(rows))


def to_langchain_messages(rows: list[ChatMessage]) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for row in rows:
        if row.role == "user":
            messages.append(HumanMessage(content=row.content))
        elif row.role == "assistant":
            messages.append(AIMessage(content=row.content or ""))
    return messages


def add_message(
    session: ChatSession,
    role: str,
    content: str,
    tool_calls: list | None = None,
) -> ChatMessage:
    message = ChatMessage(
        session_id=session.id,
        role=role,
        content=content or "",
        tool_calls=json.dumps(tool_calls) if tool_calls else None,
    )
    db.session.add(message)
    session.updated_at = utcnow()
    if role == "user" and not session.title:
        session.title = (content or "")[:120]
    db.session.flush()
    return message


def list_sessions(user: User, limit: int = 50) -> list[ChatSession]:
    return (
        db.session.query(ChatSession)
        .filter_by(user_id=user.id)
        .order_by(ChatSession.updated_at.desc())
        .limit(limit)
        .all()
    )


def get_session(user: User, session_id: str) -> ChatSession:
    session = (
        db.session.query(ChatSession)
        .filter_by(id=session_id, user_id=user.id)
        .one_or_none()
    )
    if session is None:
        raise NotFound(f"Chat session '{session_id}' not found for this user.")
    return session
