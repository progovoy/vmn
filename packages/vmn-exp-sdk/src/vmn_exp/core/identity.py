"""Who is acting: the identity stamped on registry writes, comments, reports and
run features. Re-exported by ``vmn_exp.registry.log`` (its original home); it
must not import the registry, so core can use it.

A run's features name its ``author`` (:func:`run_author`): the identity plus
``source``, where its ``git_user_email`` came from — git config (``git``), else
the caller's fallbacks in order (``VMN_EXP_AUTHOR`` is ``env``), else ``host``.
"""
from __future__ import annotations

import os
import subprocess

from vmn_exp.core.writer import get_writer_id

AUTHOR_ENV = "VMN_EXP_AUTHOR"
# A git that cannot answer ``git config user.email`` by then gives no email:
# run features capture it under the repo lock.
GIT_CONFIG_TIMEOUT_SEC = 2


def actor_identity(cwd: str | None = None) -> dict:
    """Return a plain dict identifying the writer.

    Fields:
      writer         — experiment-log writer id (VMN_WRITER_ID / HOSTNAME)
      git_user_email — git config user.email in *cwd* (default: the process
                       cwd), best-effort (empty on failure or after
                       GIT_CONFIG_TIMEOUT_SEC)
      os_user        — $USER / $LOGNAME / os.getlogin(), best-effort
    """
    return {
        "writer": get_writer_id(),
        "git_user_email": _git_user_email(cwd),
        "os_user": _os_user(),
    }


def _git_user_email(cwd: str | None = None, timeout: float = GIT_CONFIG_TIMEOUT_SEC) -> str:
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return result.stdout.strip()
    except Exception:
        return ""


def _os_user() -> str:
    for key in ("USER", "LOGNAME", "USERNAME"):
        val = os.environ.get(key)
        if val:
            return val
    try:
        return os.getlogin()
    except Exception:
        return ""


def known_identity(cwd: str | None = None) -> dict:
    """:func:`actor_identity` with its values stripped and empty ones dropped."""
    identity = {key: (value or "").strip() for key, value in actor_identity(cwd).items()}
    return {key: value for key, value in identity.items() if value}


def run_author(cwd: str | None = None, fallbacks=()) -> dict:
    """A run's ``author``: :func:`known_identity` in *cwd* plus ``source``.

    Without a git config email, the first ``(source, email)`` of *fallbacks*
    with an email supplies it; with none at all the source is ``host``.
    """
    author = known_identity(cwd)
    if author.get("git_user_email"):
        return dict(author, source="git")
    for source, email in fallbacks:
        email = (email or "").strip()
        if email:
            return dict(author, git_user_email=email, source=source)
    return dict(author, source="host") if author else {}


def env_author() -> tuple:
    """``("env", $VMN_EXP_AUTHOR)``, a :func:`run_author` fallback."""
    return "env", os.environ.get(AUTHOR_ENV, "")
