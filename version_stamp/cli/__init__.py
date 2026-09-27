#!/usr/bin/env python3
"""CLI package: argument parsing, command handlers, and entry point.

``main`` and ``vmn_run`` are loaded lazily (PEP 562) so that
``import vmn_exp.sdk`` does not pull in the heavy CLI stack
(git, rich, prompt_toolkit, stamping backends …).  Any code that
calls ``version_stamp.cli.main()`` still works unchanged; only the
*import* of this package becomes lightweight.
"""

def __getattr__(name: str):
    if name in ("main", "vmn_run"):
        from version_stamp.cli.entry import main, vmn_run

        globals().update({"main": main, "vmn_run": vmn_run})
        return main if name == "main" else vmn_run
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
