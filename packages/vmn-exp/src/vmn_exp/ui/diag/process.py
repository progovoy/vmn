#!/usr/bin/env python3
"""The ``process`` and ``env`` sections: the interpreter, the process's
resources, the server's (redacted) options, and which env vars are set."""
import gc
import os
import platform
import sys
import threading
import time

from vmn_exp.ui.diag.redact import redact_uri
from vmn_exp.ui.diag.registry import add_secret

ENV_PREFIXES = ("VMN_", "AWS_")
# Option values that are URIs or DSNs, shown redacted.
_URI_OPTIONS = ("store", "db")
# Options shown as "set"/None only.
_SECRET_OPTIONS = ("token",)

_OPTIONS = {}


def record_server_options(options):
    """Remember the server's CLI options for the dump, redacted: URIs lose
    their credentials, a token shows as ``set`` (and is scrubbed anywhere)."""
    redacted = {}
    for key, value in options.items():
        if key in _SECRET_OPTIONS:
            add_secret(value)
            value = "set" if value else None
        elif key in _URI_OPTIONS and isinstance(value, str):
            value = redact_uri(value)
        redacted[key] = value
    _OPTIONS.clear()
    _OPTIONS.update(redacted)


def _resources():
    import psutil

    proc = psutil.Process()
    with proc.oneshot():
        cpu = proc.cpu_times()
        info = {
            "uptime_sec": round(time.time() - proc.create_time(), 1),
            "cpu_user_sec": cpu.user,
            "cpu_system_sec": cpu.system,
            "rss_bytes": proc.memory_info().rss,
            "os_threads": proc.num_threads(),
        }
        if hasattr(proc, "num_fds"):
            info["open_fds"] = proc.num_fds()
    return info


def process_section():
    from vmn_exp.ui.shell_meta import server_versions

    vmn, vmn_exp = server_versions()
    gil = getattr(sys, "_is_gil_enabled", None)
    return {
        "python": sys.version,
        "implementation": platform.python_implementation(),
        "free_threaded": None if gil is None else not gil(),
        "platform": platform.platform(),
        "vmn_version": vmn,
        "vmn_exp_version": vmn_exp,
        **_resources(),
        "threads": threading.active_count(),
        "gc_counts": list(gc.get_count()),
        "gc_stats": gc.get_stats(),
        "server_options": dict(_OPTIONS),
    }


def env_section():
    """Names only of the set ``VMN_*``/``AWS_*`` variables — never values."""
    return {"set": sorted(name for name in os.environ if name.startswith(ENV_PREFIXES))}
