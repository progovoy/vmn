"""Hand validators for request bodies (plan 42 E12a): a wrong-typed field is
refused with its name before it reaches library code."""
from fastapi import HTTPException


def _optional_str(body, field, status):
    value = body.get(field)
    if value is not None and not isinstance(value, str):
        raise HTTPException(status, f"Field '{field}' must be a string")
    return value


def workspace_fields(body):
    """``(name, remote or None, path or None)`` of an add-workspace body, or a
    422: a name, and a remote to clone or a path to attach."""
    name = _optional_str(body, "name", 422)
    if name is None:
        raise HTTPException(422, "Missing field: 'name'")
    remote, path = _optional_str(body, "remote", 422), _optional_str(body, "path", 422)
    if not remote and path is None:
        raise HTTPException(422, "Missing field: 'path'")
    return name, remote or None, path


def comment_links(body):
    """``(reply_to, anchor)`` of a new comment: a comment id and an object,
    each optional; anything else is a 400."""
    reply_to = _optional_str(body, "reply_to", 400)
    anchor = body.get("anchor")
    if anchor is not None and not isinstance(anchor, dict):
        raise HTTPException(400, "Field 'anchor' must be an object")
    return reply_to, anchor
