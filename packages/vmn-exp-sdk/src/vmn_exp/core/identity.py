"""Who is acting: the identity stamped on registry writes, comments, reports and
run features. Re-exported by ``vmn_exp.registry.log`` (its original home); it
must not import the registry, so core can use it.
"""
from __future__ import annotations

import os
import subprocess

from vmn_exp.core.writer import get_writer_id


def actor_identity(cwd: str | None = None) -> dict:
    """Return a plain dict identifying the writer.

    Fields:
      writer         — experiment-log writer id (VMN_WRITER_ID / HOSTNAME)
      git_user_email — git config user.email in *cwd* (default: the process
                       cwd), best-effort (empty on failure)
      os_user        — $USER / $LOGNAME / os.getlogin(), best-effort
    """
    return {
        "writer": get_writer_id(),
        "git_user_email": _git_user_email(cwd),
        "os_user": _os_user(),
    }


def _git_user_email(cwd: str | None = None) -> str:
    try:
        result = subprocess.run(
            ["git", "config", "user.email"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=5,
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
