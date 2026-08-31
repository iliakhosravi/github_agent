"""Storage and retrieval of per-user GitHub tokens.

Every request to the agent resolves a token here; the token is what the GitHub
MCP server is called with, so a user can only ever touch repositories their own
token grants access to.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import requests
from flask import current_app

from ..extensions import db
from ..models import GitHubCredential, User, utcnow
from ..security.crypto import decrypt, encrypt
from .errors import MissingCredential, UpstreamError

# Refresh a little before actual expiry to avoid races.
_EXPIRY_SKEW = timedelta(seconds=60)


# --------------------------------------------------------------------------- users
def get_or_create_user(external_id: str, display_name: str | None = None) -> User:
    external_id = (external_id or "").strip()
    if not external_id:
        raise ValueError("external_id is required")

    user = db.session.query(User).filter_by(external_id=external_id).one_or_none()
    if user is None:
        user = User(external_id=external_id, display_name=display_name)
        db.session.add(user)
        db.session.flush()
    elif display_name and not user.display_name:
        user.display_name = display_name
    return user


def get_user(external_id: str) -> User | None:
    return db.session.query(User).filter_by(external_id=external_id).one_or_none()


# ---------------------------------------------------------------------- credentials
def save_token(
    user: User,
    access_token: str,
    *,
    token_type: str = "pat",
    refresh_token: str | None = None,
    expires_in: int | None = None,
    refresh_token_expires_in: int | None = None,
    scope: str | None = None,
    github_login: str | None = None,
) -> GitHubCredential:
    """Create or replace the stored credential for a user."""
    cred = user.credential
    if cred is None:
        cred = GitHubCredential(user_id=user.id)
        db.session.add(cred)

    now = utcnow()
    cred.token_type = token_type
    cred.access_token_enc = encrypt(access_token)
    cred.refresh_token_enc = encrypt(refresh_token) if refresh_token else None
    cred.expires_at = now + timedelta(seconds=expires_in) if expires_in else None
    cred.refresh_expires_at = (
        now + timedelta(seconds=refresh_token_expires_in)
        if refresh_token_expires_in
        else None
    )
    cred.scope = scope
    cred.github_login = github_login or fetch_github_login(access_token)
    cred.revoked = False
    db.session.flush()
    return cred


def revoke_token(user: User) -> bool:
    cred = user.credential
    if cred is None:
        return False
    db.session.delete(cred)
    db.session.flush()
    return True


def get_access_token(user: User) -> str:
    """Return a usable access token, refreshing it first if it has expired."""
    cred = user.credential
    if cred is None or cred.revoked:
        raise MissingCredential(
            f"No GitHub token stored for user '{user.external_id}'. "
            "Authorize via /auth/github/login or POST /auth/token."
        )

    if _is_expired(cred):
        cred = refresh_credential(cred)

    token = decrypt(cred.access_token_enc)
    if not token:
        raise MissingCredential("Stored GitHub token is empty.")
    return token


def _is_expired(cred: GitHubCredential) -> bool:
    if cred.expires_at is None:
        return False
    expires_at = cred.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    return datetime.now(timezone.utc) + _EXPIRY_SKEW >= expires_at


def refresh_credential(cred: GitHubCredential) -> GitHubCredential:
    """Exchange the refresh token for a new access token.

    Only GitHub Apps (and OAuth apps with expiring tokens enabled) issue refresh
    tokens; classic OAuth-app tokens never expire and never reach this path.
    """
    refresh_token = decrypt(cred.refresh_token_enc) if cred.refresh_token_enc else None
    if not refresh_token:
        raise MissingCredential(
            "GitHub token expired and no refresh token is available. "
            "Re-authorize via /auth/github/login."
        )

    cfg = current_app.config
    resp = requests.post(
        cfg["GITHUB_TOKEN_URL"],
        headers={"Accept": "application/json"},
        data={
            "client_id": cfg["GITHUB_CLIENT_ID"],
            "client_secret": cfg["GITHUB_CLIENT_SECRET"],
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
        timeout=20,
    )
    if resp.status_code != 200:
        raise UpstreamError(f"GitHub token refresh failed: HTTP {resp.status_code}")

    payload = resp.json()
    if "error" in payload:
        raise UpstreamError(
            f"GitHub token refresh failed: {payload.get('error_description', payload['error'])}"
        )

    now = utcnow()
    cred.access_token_enc = encrypt(payload["access_token"])
    if payload.get("refresh_token"):
        cred.refresh_token_enc = encrypt(payload["refresh_token"])
    if payload.get("expires_in"):
        cred.expires_at = now + timedelta(seconds=int(payload["expires_in"]))
    if payload.get("refresh_token_expires_in"):
        cred.refresh_expires_at = now + timedelta(
            seconds=int(payload["refresh_token_expires_in"])
        )
    cred.scope = payload.get("scope") or cred.scope
    db.session.flush()
    return cred


# ------------------------------------------------------------------------- helpers
def fetch_github_login(access_token: str) -> str | None:
    """Best-effort lookup of the token owner, used as a sanity check on save."""
    try:
        resp = requests.get(
            f"{current_app.config['GITHUB_API_URL']}/user",
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
            },
            timeout=15,
        )
        if resp.status_code == 200:
            return resp.json().get("login")
    except requests.RequestException:
        pass
    return None
