#!/usr/bin/env python3
"""Error bodies that tell a client why: ``{"detail": <message>, "code": <reason>}``."""
from fastapi import HTTPException

from vmn_exp.core.resolve_ref import AMBIGUOUS_REF, INVALID_REF, RUN_NOT_FOUND
from vmn_exp.ui.responses import SafeJSONResponse

APP_NOT_FOUND = "app_not_found"
REF_STATUS = {RUN_NOT_FOUND: 404, AMBIGUOUS_REF: 409, INVALID_REF: 400}


class CodedError(Exception):
    def __init__(self, status, detail, code):
        super().__init__(detail)
        self.status, self.detail, self.code = status, detail, code


def install(app):
    @app.exception_handler(CodedError)
    async def _coded(request, exc: CodedError):
        body = {"detail": exc.detail, "code": exc.code}
        return SafeJSONResponse(body, status_code=exc.status)


def raise_read_error(err):
    """Raise a reader's *err*: coded when it is a run-ref
    :class:`~vmn_exp.core.resolve_ref.RefError`, else a plain 404."""
    code = getattr(err, "code", None)
    if code is None:
        raise HTTPException(404, err)
    raise CodedError(REF_STATUS[code], str(err), code)
