"""Central configuration, loaded from environment / .env."""
from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def _bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None or raw == "":
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _int(name: str, default: int) -> int:
    raw = os.getenv(name)
    try:
        return int(raw) if raw not in (None, "") else default
    except ValueError:
        return default


def _optional_int(name: str) -> int | None:
    raw = os.getenv(name)
    try:
        return int(raw) if raw not in (None, "") else None
    except ValueError:
        return None


def normalize_db_url(url: str) -> str:
    """Force the psycopg (v3) driver, which is what requirements.txt installs."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://") :]
    return url


class Config:
    # --- Flask -------------------------------------------------------------
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")
    JSON_SORT_KEYS = False

    # --- Database ----------------------------------------------------------
    SQLALCHEMY_DATABASE_URI = normalize_db_url(
        os.getenv(
            "DATABASE_URL",
            "postgresql://postgres:postgres@localhost:5432/github_agent",
        )
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    # --- Crypto ------------------------------------------------------------
    TOKEN_ENCRYPTION_KEY = os.getenv("TOKEN_ENCRYPTION_KEY", "")

    # --- GitHub OAuth ------------------------------------------------------
    GITHUB_CLIENT_ID = os.getenv("GITHUB_CLIENT_ID", "")
    GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
    GITHUB_OAUTH_REDIRECT_URI = os.getenv(
        "GITHUB_OAUTH_REDIRECT_URI", "http://127.0.0.1:5000/auth/github/callback"
    )
    GITHUB_OAUTH_SCOPES = os.getenv("GITHUB_OAUTH_SCOPES", "repo read:user")
    GITHUB_AUTHORIZE_URL = "https://github.com/login/oauth/authorize"
    GITHUB_TOKEN_URL = "https://github.com/login/oauth/access_token"
    GITHUB_API_URL = os.getenv("GITHUB_API_URL", "https://api.github.com")
    OAUTH_SUCCESS_REDIRECT = os.getenv("OAUTH_SUCCESS_REDIRECT", "")
    OAUTH_STATE_MAX_AGE = _int("OAUTH_STATE_MAX_AGE", 600)

    # --- GitHub MCP --------------------------------------------------------
    GITHUB_MCP_URL = os.getenv("GITHUB_MCP_URL", "https://api.githubcopilot.com/mcp/")
    GITHUB_MCP_TOOLSETS = os.getenv(
        "GITHUB_MCP_TOOLSETS", "context,repos,issues,pull_requests"
    )
    GITHUB_MCP_READONLY = _bool("GITHUB_MCP_READONLY", False)

    # --- LLM ---------------------------------------------------------------
    LLM_PROVIDER = os.getenv("LLM_PROVIDER", "openai")
    LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o")
    LLM_TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0") or 0)
    LLM_MAX_TOKENS = _optional_int("LLM_MAX_TOKENS")

    # --- Agent -------------------------------------------------------------
    CHAT_HISTORY_LIMIT = _int("CHAT_HISTORY_LIMIT", 3)
    AGENT_RECURSION_LIMIT = _int("AGENT_RECURSION_LIMIT", 40)
    AGENT_TIMEOUT_SECONDS = _int("AGENT_TIMEOUT_SECONDS", 300)
    AGENT_WRITE_MODE = os.getenv("AGENT_WRITE_MODE", "branch_pr")


class TestConfig(Config):
    TESTING = True
    SQLALCHEMY_DATABASE_URI = os.getenv("TEST_DATABASE_URL", "sqlite+pysqlite:///:memory:")
    SQLALCHEMY_ENGINE_OPTIONS: dict = {}
