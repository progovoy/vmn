#!/usr/bin/env python3
"""Error bodies that tell a client why: ``{"detail": <message>, "code": <reason>}``."""
import logging

from fastapi import HTTPException
from starlette.exceptions import HTTPException as StarletteHTTPException

from vmn_exp.core.resolve_ref import AMBIGUOUS_REF, INVALID_REF, RUN_NOT_FOUND
from vmn_exp.ui.responses import SafeJSONResponse

APP_NOT_FOUND = "app_not_found"
REF_STATUS = {RUN_NOT_FOUND: 404, AMBIGUOUS_REF: 409, INVALID_REF: 400}
STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "too_large",
    415: "unsupported_media_type",
    422: "invalid_body",
    429: "busy",
    500: "internal_error",
    501: "not_implemented",
    502: "bad_gateway",
    503: "unavailable",
}
_LOGGER = logging.getLogger(__name__)


class CodedError(Exception):
    def __init__(self, status, detail, code):
        super().__init__(detail)
        self.status, self.detail, self.code = status, detail, code


def error_body(detail, code, **extra):
    """The one error envelope: *detail*, *code*, then any *extra* keys."""
    return {"detail": detail, "code": code, **extra}


def status_code_name(status):
    """The ``code`` of an error that names none: from its HTTP *status*."""
    return STATUS_CODES.get(status, f"http_{status}")


def install(app):
    @app.exception_handler(CodedError)
    async def _coded(request, exc: CodedError):
        return SafeJSONResponse(error_body(exc.detail, exc.code), status_code=exc.status)

    @app.exception_handler(StarletteHTTPException)
    async def _http(request, exc: StarletteHTTPException):
        body = error_body(exc.detail, status_code_name(exc.status_code))
        return SafeJSONResponse(body, status_code=exc.status_code, headers=exc.headers)

    @app.exception_handler(ValueError)
    async def _value_error(request, exc: ValueError):
        # Storage refuses names that are not a single path component; any
        # other ValueError is logged so a server bug answered 400 is seen.
        _LOGGER.warning(
            "400 for ValueError on %s %s", request.method, request.url.path,
            exc_info=exc,
        )
        return SafeJSONResponse({"detail": str(exc)}, status_code=400)


def raise_read_error(err):
    """Raise a reader's *err*: coded when it is a run-ref
    :class:`~vmn_exp.core.resolve_ref.RefError`, else a plain 404."""
    code = getattr(err, "code", None)
    if code is None:
        raise HTTPException(404, err)
    raise CodedError(REF_STATUS[code], str(err), code)
