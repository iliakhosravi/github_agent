"""GitHub authentication: OAuth web flow and direct PAT registration.

OAuth flow
----------
1. GET  /auth/github/login?user_id=alice   -> 302 to GitHub's consent screen
2. GitHub redirects back to /auth/github/callback?code=...&state=...
3. The code is exchanged for a token, which is encrypted and stored.

The `state` parameter is an itsdangerous-signed, time-limited token carrying the
user id and a nonce, so no server-side state table is needed and a forged or
replayed callback is rejected.
"""
from __future__ import annotations

import secrets
from urllib.parse import urlencode

import requests
from flask import Blueprint, current_app, jsonify, redirect, request
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

from ..extensions import db
from ..services import token_service
from ..services.errors import AppError, ConfigError, NotFound, UpstreamError

bp = Blueprint("auth", __name__, url_prefix="/auth")

_STATE_SALT = "github-oauth-state"


def _serializer() -> URLSafeTimedSerializer:
    return URLSafeTimedSerializer(current_app.config["SECRET_KEY"], salt=_STATE_SALT)


def _require_oauth_config() -> None:
    cfg = current_app.config
    if not cfg.get("GITHUB_CLIENT_ID") or not cfg.get("GITHUB_CLIENT_SECRET"):
        raise ConfigError(
            "GitHub OAuth is not configured. Set GITHUB_CLIENT_ID and "
            "GITHUB_CLIENT_SECRET in .env, or use POST /auth/token with a PAT."
        )


# --------------------------------------------------------------------- OAuth flow
@bp.get("/github/login")
def github_login():
    _require_oauth_config()
    user_id = (request.args.get("user_id") or "").strip()
    if not user_id:
        raise AppError("Query parameter 'user_id' is required.")

    cfg = current_app.config
    state = _serializer().dumps(
        {
            "user_id": user_id,
            "nonce": secrets.token_urlsafe(16),
            "next": request.args.get("next") or cfg.get("OAUTH_SUCCESS_REDIRECT") or "",
        }
    )
    params = {
        "client_id": cfg["GITHUB_CLIENT_ID"],
        "redirect_uri": cfg["GITHUB_OAUTH_REDIRECT_URI"],
        "scope": cfg["GITHUB_OAUTH_SCOPES"],
        "state": state,
        "allow_signup": "false",
    }
    return redirect(f"{cfg['GITHUB_AUTHORIZE_URL']}?{urlencode(params)}", code=302)


@bp.get("/github/callback")
def github_callback():
    _require_oauth_config()
    cfg = current_app.config

    if error := request.args.get("error"):
        raise AppError(
            f"GitHub authorization failed: {request.args.get('error_description', error)}"
        )

    code = request.args.get("code")
    state = request.args.get("state")
    if not code or not state:
        raise AppError("Missing 'code' or 'state' in the callback.")

    try:
        payload = _serializer().loads(state, max_age=cfg["OAUTH_STATE_MAX_AGE"])
    except SignatureExpired as exc:
        raise AppError("The authorization request expired. Start over.") from exc
    except BadSignature as exc:
        raise AppError("Invalid OAuth state.", status_code=400, code="bad_state") from exc

    resp = requests.post(
        cfg["GITHUB_TOKEN_URL"],
        headers={"Accept": "application/json"},
        data={
            "client_id": cfg["GITHUB_CLIENT_ID"],
            "client_secret": cfg["GITHUB_CLIENT_SECRET"],
            "code": code,
            "redirect_uri": cfg["GITHUB_OAUTH_REDIRECT_URI"],
        },
        timeout=20,
    )
    if resp.status_code != 200:
        raise UpstreamError(f"Token exchange failed: HTTP {resp.status_code}")

    data = resp.json()
    if "error" in data:
        raise UpstreamError(
            f"Token exchange failed: {data.get('error_description', data['error'])}"
        )

    user = token_service.get_or_create_user(payload["user_id"])
    cred = token_service.save_token(
        user,
        data["access_token"],
        token_type="oauth",
        refresh_token=data.get("refresh_token"),
        expires_in=int(data["expires_in"]) if data.get("expires_in") else None,
        refresh_token_expires_in=(
            int(data["refresh_token_expires_in"])
            if data.get("refresh_token_expires_in")
            else None
        ),
        scope=data.get("scope"),
    )
    db.session.commit()

    if next_url := payload.get("next"):
        return redirect(next_url, code=302)
    return jsonify(
        {"status": "connected", "user_id": user.external_id, "credential": cred.to_dict()}
    )


# ------------------------------------------------------------------- PAT / status
@bp.post("/token")
def store_pat():
    body = request.get_json(silent=True) or {}
    user_id = (body.get("user_id") or "").strip()
    token = (body.get("token") or body.get("access_token") or "").strip()
    if not user_id or not token:
        raise AppError("Both 'user_id' and 'token' are required.")

    login = token_service.fetch_github_login(token)
    if login is None:
        raise AppError(
            "GitHub rejected this token. Check that it is valid and has the "
            "'repo' scope.",
            status_code=401,
            code="invalid_token",
        )

    user = token_service.get_or_create_user(user_id, body.get("display_name"))
    if body.get("default_repo"):
        user.default_repo = body["default_repo"]
    cred = token_service.save_token(
        user, token, token_type="pat", scope=body.get("scope"), github_login=login
    )
    db.session.commit()
    return jsonify({"status": "stored", "user_id": user.external_id, "credential": cred.to_dict()})


@bp.get("/status")
def status():
    user_id = (request.args.get("user_id") or "").strip()
    if not user_id:
        raise AppError("Query parameter 'user_id' is required.")

    user = token_service.get_user(user_id)
    if user is None or user.credential is None:
        return jsonify({"user_id": user_id, "connected": False})
    return jsonify(
        {"user_id": user_id, "connected": True, "credential": user.credential.to_dict()}
    )


@bp.delete("/token")
def delete_token():
    user_id = (request.args.get("user_id") or "").strip()
    if not user_id:
        body = request.get_json(silent=True) or {}
        user_id = (body.get("user_id") or "").strip()
    if not user_id:
        raise AppError("'user_id' is required.")

    user = token_service.get_user(user_id)
    if user is None:
        raise NotFound(f"Unknown user '{user_id}'.")

    removed = token_service.revoke_token(user)
    db.session.commit()
    return jsonify({"status": "revoked" if removed else "no_credential", "user_id": user_id})
