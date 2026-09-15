"""OpenAPI schema and Swagger UI routes."""
from __future__ import annotations

from flask import Blueprint, Response, jsonify

bp = Blueprint("docs", __name__)


def openapi_spec() -> dict:
    return {
        "openapi": "3.0.3",
        "info": {
            "title": "GitHub Agent API",
            "version": "1.0.0",
            "description": (
                "A Flask service for connecting GitHub credentials and sending "
                "natural-language prompts to a repository-editing agent."
            ),
        },
        "servers": [{"url": "/"}],
        "tags": [
            {"name": "Health"},
            {"name": "Agent"},
            {"name": "Sessions"},
            {"name": "Authentication"},
            {"name": "Debug"},
        ],
        "paths": {
            "/": {
                "get": {
                    "summary": "Service index",
                    "tags": ["Health"],
                    "responses": {"200": {"description": "Service metadata"}},
                }
            },
            "/api/health": {
                "get": {
                    "summary": "Check service health",
                    "tags": ["Health"],
                    "responses": {
                        "200": {
                            "description": "Service is healthy",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/HealthResponse"
                                    }
                                }
                            },
                        },
                        "503": {"description": "Database check failed"},
                    },
                }
            },
            "/api/chat": {
                "post": {
                    "summary": "Send a prompt to the GitHub agent",
                    "tags": ["Agent"],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/ChatRequest"}
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Agent response",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/ChatResponse"
                                    }
                                }
                            },
                        },
                        "400": {"$ref": "#/components/responses/Error"},
                        "401": {"$ref": "#/components/responses/Error"},
                        "500": {"$ref": "#/components/responses/Error"},
                    },
                }
            },
            "/api/sessions": {
                "get": {
                    "summary": "List chat sessions for a user",
                    "tags": ["Sessions"],
                    "parameters": [{"$ref": "#/components/parameters/UserId"}],
                    "responses": {
                        "200": {
                            "description": "Sessions for the user",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "sessions": {
                                                "type": "array",
                                                "items": {
                                                    "$ref": "#/components/schemas/Session"
                                                },
                                            }
                                        },
                                    }
                                }
                            },
                        },
                        "400": {"$ref": "#/components/responses/Error"},
                    },
                }
            },
            "/api/sessions/{session_id}/messages": {
                "get": {
                    "summary": "Get messages for a chat session",
                    "tags": ["Sessions"],
                    "parameters": [
                        {
                            "name": "session_id",
                            "in": "path",
                            "required": True,
                            "schema": {"type": "string", "format": "uuid"},
                        },
                        {"$ref": "#/components/parameters/UserId"},
                    ],
                    "responses": {
                        "200": {
                            "description": "Session transcript",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "session": {
                                                "$ref": "#/components/schemas/Session"
                                            },
                                            "messages": {
                                                "type": "array",
                                                "items": {
                                                    "$ref": "#/components/schemas/Message"
                                                },
                                            },
                                        },
                                    }
                                }
                            },
                        },
                        "400": {"$ref": "#/components/responses/Error"},
                        "404": {"$ref": "#/components/responses/Error"},
                    },
                }
            },
            "/api/tools": {
                "get": {
                    "summary": "List GitHub MCP tools available to a user",
                    "tags": ["Debug"],
                    "parameters": [{"$ref": "#/components/parameters/UserId"}],
                    "responses": {
                        "200": {
                            "description": "Available tools",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "tools": {
                                                "type": "array",
                                                "items": {"type": "object"},
                                            }
                                        },
                                    }
                                }
                            },
                        },
                        "400": {"$ref": "#/components/responses/Error"},
                        "401": {"$ref": "#/components/responses/Error"},
                    },
                }
            },
            "/auth/github/login": {
                "get": {
                    "summary": "Start the GitHub OAuth flow",
                    "tags": ["Authentication"],
                    "parameters": [
                        {"$ref": "#/components/parameters/UserId"},
                        {
                            "name": "next",
                            "in": "query",
                            "required": False,
                            "schema": {"type": "string", "format": "uri"},
                        },
                    ],
                    "responses": {
                        "302": {"description": "Redirect to GitHub authorization"},
                        "400": {"$ref": "#/components/responses/Error"},
                        "500": {"$ref": "#/components/responses/Error"},
                    },
                }
            },
            "/auth/github/callback": {
                "get": {
                    "summary": "Handle GitHub OAuth callback",
                    "tags": ["Authentication"],
                    "parameters": [
                        {
                            "name": "code",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                        {
                            "name": "state",
                            "in": "query",
                            "required": True,
                            "schema": {"type": "string"},
                        },
                    ],
                    "responses": {
                        "200": {"description": "Credential connected"},
                        "302": {"description": "Redirect to configured next URL"},
                        "400": {"$ref": "#/components/responses/Error"},
                        "502": {"$ref": "#/components/responses/Error"},
                    },
                }
            },
            "/auth/token": {
                "post": {
                    "summary": "Store a GitHub personal access token",
                    "tags": ["Authentication"],
                    "requestBody": {
                        "required": True,
                        "content": {
                            "application/json": {
                                "schema": {"$ref": "#/components/schemas/TokenRequest"}
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Token stored",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/CredentialResponse"
                                    }
                                }
                            },
                        },
                        "400": {"$ref": "#/components/responses/Error"},
                        "401": {"$ref": "#/components/responses/Error"},
                    },
                },
                "delete": {
                    "summary": "Remove a stored GitHub token",
                    "tags": ["Authentication"],
                    "parameters": [{"$ref": "#/components/parameters/UserId"}],
                    "requestBody": {
                        "required": False,
                        "content": {
                            "application/json": {
                                "schema": {
                                    "type": "object",
                                    "properties": {"user_id": {"type": "string"}},
                                }
                            }
                        },
                    },
                    "responses": {
                        "200": {
                            "description": "Token revoked or no credential existed",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "type": "object",
                                        "properties": {
                                            "status": {
                                                "type": "string",
                                                "enum": ["revoked", "no_credential"],
                                            },
                                            "user_id": {"type": "string"},
                                        },
                                    }
                                }
                            },
                        },
                        "400": {"$ref": "#/components/responses/Error"},
                        "404": {"$ref": "#/components/responses/Error"},
                    },
                }
            },
            "/auth/status": {
                "get": {
                    "summary": "Check whether a user has a connected token",
                    "tags": ["Authentication"],
                    "parameters": [{"$ref": "#/components/parameters/UserId"}],
                    "responses": {
                        "200": {
                            "description": "Connection status",
                            "content": {
                                "application/json": {
                                    "schema": {
                                        "$ref": "#/components/schemas/StatusResponse"
                                    }
                                }
                            },
                        },
                        "400": {"$ref": "#/components/responses/Error"},
                    },
                }
            },
            "/openapi.json": {
                "get": {
                    "summary": "Get the OpenAPI document",
                    "tags": ["Health"],
                    "responses": {"200": {"description": "OpenAPI JSON"}},
                }
            },
            "/docs": {
                "get": {
                    "summary": "Open Swagger UI",
                    "tags": ["Health"],
                    "responses": {"200": {"description": "Swagger UI HTML"}},
                }
            },
        },
        "components": {
            "parameters": {
                "UserId": {
                    "name": "user_id",
                    "in": "query",
                    "required": True,
                    "schema": {"type": "string"},
                }
            },
            "responses": {
                "Error": {
                    "description": "Error response",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/ErrorResponse"}
                        }
                    },
                }
            },
            "schemas": {
                "HealthResponse": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string", "enum": ["ok", "degraded"]},
                        "database": {"type": "boolean"},
                        "llm": {"type": "object"},
                        "mcp_url": {"type": "string", "format": "uri"},
                        "write_mode": {"type": "string"},
                        "history_limit": {"type": "integer"},
                    },
                },
                "ChatRequest": {
                    "type": "object",
                    "required": ["user_id", "message"],
                    "properties": {
                        "user_id": {"type": "string"},
                        "message": {"type": "string"},
                        "prompt": {
                            "type": "string",
                            "description": "Alias for message.",
                        },
                        "session_id": {"type": "string", "format": "uuid"},
                        "repo": {
                            "type": "string",
                            "example": "octocat/hello-world",
                        },
                        "llm": {"$ref": "#/components/schemas/LlmOverrides"},
                    },
                },
                "ChatResponse": {
                    "type": "object",
                    "properties": {
                        "session_id": {"type": "string", "format": "uuid"},
                        "repo": {"type": "string", "nullable": True},
                        "reply": {"type": "string"},
                        "tool_calls": {
                            "type": "array",
                            "items": {"type": "object"},
                        },
                        "history_used": {"type": "integer"},
                    },
                },
                "LlmOverrides": {
                    "type": "object",
                    "properties": {
                        "provider": {"type": "string"},
                        "model": {"type": "string"},
                        "temperature": {"type": "number"},
                    },
                },
                "TokenRequest": {
                    "type": "object",
                    "required": ["user_id", "token"],
                    "properties": {
                        "user_id": {"type": "string"},
                        "token": {"type": "string", "format": "password"},
                        "access_token": {
                            "type": "string",
                            "format": "password",
                            "description": "Alias for token.",
                        },
                        "display_name": {"type": "string"},
                        "default_repo": {
                            "type": "string",
                            "example": "octocat/hello-world",
                        },
                        "scope": {"type": "string"},
                    },
                },
                "Credential": {
                    "type": "object",
                    "properties": {
                        "token_type": {"type": "string", "enum": ["oauth", "pat"]},
                        "github_login": {"type": "string", "nullable": True},
                        "scope": {"type": "string", "nullable": True},
                        "expires_at": {
                            "type": "string",
                            "format": "date-time",
                            "nullable": True,
                        },
                        "revoked": {"type": "boolean"},
                        "updated_at": {
                            "type": "string",
                            "format": "date-time",
                            "nullable": True,
                        },
                    },
                },
                "CredentialResponse": {
                    "type": "object",
                    "properties": {
                        "status": {"type": "string"},
                        "user_id": {"type": "string"},
                        "credential": {"$ref": "#/components/schemas/Credential"},
                    },
                },
                "StatusResponse": {
                    "type": "object",
                    "properties": {
                        "user_id": {"type": "string"},
                        "connected": {"type": "boolean"},
                        "credential": {"$ref": "#/components/schemas/Credential"},
                    },
                },
                "Session": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "string", "format": "uuid"},
                        "repo": {"type": "string", "nullable": True},
                        "title": {"type": "string", "nullable": True},
                        "created_at": {"type": "string", "format": "date-time"},
                        "updated_at": {"type": "string", "format": "date-time"},
                    },
                },
                "Message": {
                    "type": "object",
                    "properties": {
                        "id": {"type": "integer"},
                        "role": {
                            "type": "string",
                            "enum": ["user", "assistant", "system"],
                        },
                        "content": {"type": "string"},
                        "tool_calls": {
                            "type": "array",
                            "items": {"type": "object"},
                        },
                        "created_at": {"type": "string", "format": "date-time"},
                    },
                },
                "ErrorResponse": {
                    "type": "object",
                    "properties": {
                        "error": {
                            "type": "object",
                            "properties": {
                                "code": {"type": "string"},
                                "message": {"type": "string"},
                            },
                        }
                    },
                },
            },
        },
    }


@bp.get("/openapi.json")
def openapi_json():
    return jsonify(openapi_spec())


@bp.get("/docs")
def swagger_ui():
    return Response(
        """<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8">
    <title>GitHub Agent API Docs</title>
    <link rel="stylesheet" href="https://unpkg.com/swagger-ui-dist@5/swagger-ui.css">
    <style>
      body { margin: 0; background: #fafafa; }
    </style>
  </head>
  <body>
    <div id="swagger-ui"></div>
    <script src="https://unpkg.com/swagger-ui-dist@5/swagger-ui-bundle.js"></script>
    <script>
      window.onload = () => {
        window.ui = SwaggerUIBundle({
          url: "/openapi.json",
          dom_id: "#swagger-ui",
          deepLinking: true,
          presets: [SwaggerUIBundle.presets.apis],
          layout: "BaseLayout"
        });
      };
    </script>
  </body>
</html>
""",
        mimetype="text/html",
    )
