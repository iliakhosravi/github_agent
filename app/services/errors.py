"""Application level errors, mapped to HTTP status codes by the error handler."""


class AppError(Exception):
    status_code = 400
    code = "bad_request"

    def __init__(self, message: str, *, status_code: int | None = None, code: str | None = None):
        super().__init__(message)
        self.message = message
        if status_code is not None:
            self.status_code = status_code
        if code is not None:
            self.code = code

    def to_dict(self) -> dict:
        return {"error": {"code": self.code, "message": self.message}}


class NotFound(AppError):
    status_code = 404
    code = "not_found"


class MissingCredential(AppError):
    status_code = 401
    code = "github_token_missing"


class ConfigError(AppError):
    status_code = 500
    code = "configuration_error"


class UpstreamError(AppError):
    status_code = 502
    code = "upstream_error"
