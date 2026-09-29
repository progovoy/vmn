#!/usr/bin/env python3
"""``VMN_MODE=disabled``: a kill switch that makes the SDK record nothing.

For CI, unit tests of training code and debugging sessions: ``start_run()``
returns a :class:`~vmn_exp.sdk.ranks.NoOpRun` without touching git or the store,
and ``autolog()`` patches nothing. Precedence mirrors ``capture_env``: an
explicit ``start_run(mode=...)`` beats ``VMN_MODE``, which beats the default,
``"enabled"``.
"""
import os

MODES = ("enabled", "disabled")


def is_disabled(mode=None):
    """Whether *mode* (ValueError if unknown), else ``VMN_MODE``, is ``disabled``."""
    if mode is None:
        return os.environ.get("VMN_MODE", "").strip().lower() == "disabled"
    if mode not in MODES:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    return mode == "disabled"
