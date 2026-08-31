"""Flask application factory."""
from __future__ import annotations

import logging

from flask import Flask, jsonify
from werkzeug.exceptions import HTTPException

from .config import Config
from .extensions import db, migrate
from .services.errors import AppError


def create_app(config_object: type | str = Config) -> Flask:
    app = Flask(__name__)
    app.config.from_object(config_object)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
    )

    db.init_app(app)
    migrate.init_app(app, db)

    # Import models so Flask-Migrate/create_all can see them.
    from . import models  # noqa: F401

    from .api import bp as api_bp
    from .auth import bp as auth_bp

    app.register_blueprint(api_bp)
    app.register_blueprint(auth_bp)

    from .cli import register_cli

    register_cli(app)

    _register_error_handlers(app)

    @app.get("/")
    def index():
        return jsonify(
            {
                "service": "github-agent",
                "endpoints": [
                    "GET  /api/health",
                    "POST /api/chat",
                    "GET  /api/sessions?user_id=",
                    "GET  /api/sessions/<id>/messages?user_id=",
                    "GET  /api/tools?user_id=",
                    "GET  /auth/github/login?user_id=",
                    "GET  /auth/github/callback",
                    "POST /auth/token",
                    "GET  /auth/status?user_id=",
                    "DELETE /auth/token?user_id=",
                ],
            }
        )

    return app


def _register_error_handlers(app: Flask) -> None:
    @app.errorhandler(AppError)
    def handle_app_error(exc: AppError):
        db.session.rollback()
        return jsonify(exc.to_dict()), exc.status_code

    @app.errorhandler(HTTPException)
    def handle_http_error(exc: HTTPException):
        return (
            jsonify({"error": {"code": exc.name.lower().replace(" ", "_"), "message": exc.description}}),
            exc.code or 500,
        )

    @app.errorhandler(Exception)
    def handle_unexpected(exc: Exception):
        app.logger.exception("Unhandled error")
        db.session.rollback()
        return jsonify({"error": {"code": "internal_error", "message": str(exc)}}), 500
