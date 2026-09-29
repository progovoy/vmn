#!/usr/bin/env python3
"""``VMN_MODE=disabled``: a kill switch that makes the SDK record nothing.

For CI, unit tests of training code and debugging sessions: ``start_run()``
returns a :class:`~vmn_exp.sdk.ranks.NoOpRun` without touching git or the store,
and ``autolog()`` patches nothing. Precedence mirrors ``capture_env``: an
explicit ``start_run(mode=...)`` beats ``VMN_MODE``, which beats the default,
``"enabled"``.
"""
import os

MODE_ENV = "VMN_MODE"
MODES = ("enabled", "disabled")


def resolve_mode(mode=None, env=None):
    """The effective mode: *mode* when given (ValueError if unknown), else the env's."""
    if mode is not None:
        if mode not in MODES:
            raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
        return mode
    env = os.environ if env is None else env
    if env.get(MODE_ENV, "").strip().lower() == "disabled":
        return "disabled"
    return "enabled"


def is_disabled(mode=None, env=None):
    return resolve_mode(mode, env) == "disabled"
