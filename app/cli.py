"""Flask CLI helpers: `flask init-db`, `flask add-token`, `flask genkey`."""
from __future__ import annotations

import click
from flask import Flask

from .extensions import db
from .services import token_service


def register_cli(app: Flask) -> None:
    @app.cli.command("init-db")
    def init_db() -> None:
        """Create all tables (quick start; use `flask db upgrade` for real migrations)."""
        db.create_all()
        click.echo("Tables created.")

    @app.cli.command("genkey")
    def genkey() -> None:
        """Print a fresh Fernet key for TOKEN_ENCRYPTION_KEY."""
        from cryptography.fernet import Fernet

        click.echo(Fernet.generate_key().decode())

    @app.cli.command("add-token")
    @click.argument("user_id")
    @click.argument("token")
    @click.option("--repo", default=None, help="Default repo, e.g. owner/name")
    def add_token(user_id: str, token: str, repo: str | None) -> None:
        """Store a GitHub PAT for USER_ID."""
        login = token_service.fetch_github_login(token)
        if login is None:
            raise click.ClickException("GitHub rejected this token.")
        user = token_service.get_or_create_user(user_id)
        if repo:
            user.default_repo = repo
        token_service.save_token(user, token, token_type="pat", github_login=login)
        db.session.commit()
        click.echo(f"Stored token for {user_id} (GitHub: @{login}).")
