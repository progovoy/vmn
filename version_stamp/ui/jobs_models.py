"""Validation helpers for model registry mutations.
from __future__ import annotations

Analogous to :mod:`version_stamp.ui.jobs_exp_meta`.  Mutations are executed
in-process (the registry is git-free and needs no repo lock) rather than as
CLI subprocesses.
"""
from vmn_exp.registry.names import valid_alias_name, valid_model_name

MAX_DESCRIPTION_LEN = 512
VALID_STATUSES = ("active", "deprecated", "deleted")


def _valid_verstr(value):
    """A non-empty string that doesn't start with ``-``."""
    return isinstance(value, str) and bool(value) and not value.startswith("-")


def validate_register_body(body: dict) -> tuple[dict | None, str | None]:
    """Validate and normalise a register-version request body.

    Returns ``(normalised_dict, None)`` or ``(None, error_message)``.
    """
    run = body.get("run")
    if not isinstance(run, dict):
        return None, "'run' must be an object with app and verstr"
    if not isinstance(run.get("app"), str) or not run["app"]:
        return None, "'run.app' must be a non-empty string"
    if not _valid_verstr(run.get("verstr")):
        return None, "'run.verstr' must be a non-empty string"

    description = body.get("description")
    if description is not None:
        if not isinstance(description, str) or len(description) > MAX_DESCRIPTION_LEN:
            return None, f"'description' must be a string of at most {MAX_DESCRIPTION_LEN} chars"

    artifact_path = body.get("artifact_path")
    if artifact_path is not None and not isinstance(artifact_path, str):
        return None, "'artifact_path' must be a string"

    alias = body.get("alias")
    if alias is not None and not valid_alias_name(alias):
        return None, f"Invalid alias name {alias!r}"

    return {
        "run": {"app": run["app"], "verstr": run["verstr"]},
        "artifact_path": artifact_path,
        "artifact_uri": body.get("artifact_uri"),
        "description": description,
        "alias": alias,
    }, None


def validate_alias_body(body: dict) -> tuple[dict | None, str | None]:
    """Validate a move-alias request body.

    Returns ``(normalised_dict, None)`` or ``(None, error_message)``.
    """
    alias = body.get("alias")
    if not valid_alias_name(alias or ""):
        return None, f"Invalid alias name {alias!r}"

    version = body.get("version")
    if not isinstance(version, int) or version < 1:
        return None, "'version' must be a positive integer"

    expect = body.get("expect")
    if expect is not None and (not isinstance(expect, int) or expect < 1):
        return None, "'expect' must be a positive integer when present"

    return {"alias": alias, "version": version, "expect": expect}, None


def validate_status_body(body: dict) -> tuple[str | None, str | None]:
    """Validate a set-version-status request body.

    Returns ``(status_string, None)`` or ``(None, error_message)``.
    """
    status = body.get("status")
    if status not in VALID_STATUSES:
        return None, f"'status' must be one of {VALID_STATUSES}"
    return status, None
