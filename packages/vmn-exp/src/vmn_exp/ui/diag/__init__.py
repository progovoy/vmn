#!/usr/bin/env python3
"""Built-in diagnostic dumps of a running ``vmn-exp ui`` (one JSON file to
carry off an air-gapped host): ``GET /api/v1/diag``, SIGUSR1 and
``--diag-every`` write ``build_dump()``; see docs/vmn-exp/ui.md.

Other modules add sections with :func:`register_section`.
"""
from vmn_exp.ui.diag import s3_attribution
from vmn_exp.ui.diag.dump_files import install_signal_handler, start_periodic_dumps, write_dump
from vmn_exp.ui.diag.indexes import indexes_section
from vmn_exp.ui.diag.latency import install_loop_probe, latency_section, start_thread_probe
from vmn_exp.ui.diag.logs import install_log_capture, logs_section
from vmn_exp.ui.diag.pools import pools_section
from vmn_exp.ui.diag.process import env_section, process_section, record_server_options
from vmn_exp.ui.diag.registry import add_secret, build_dump, register_section
from vmn_exp.ui.diag.requests import RequestTracker
from vmn_exp.ui.diag.stacks import install_stack_dump
from vmn_exp.ui.diag.threads import threads_section

__all__ = [
    "add_secret", "build_dump", "env_section", "install_app", "install_default_sections",
    "install_signal_handler", "install_stack_dump", "process_section", "record_server_options",
    "register_section", "start_periodic_dumps", "threads_section", "write_dump",
]


def install_default_sections(refresher=None, tracker=None):
    """Register the built-in sections, reading *refresher*'s indexes and
    *tracker*'s requests (a fresh tracker when none is given)."""
    tracker = tracker or RequestTracker()
    register_section("threads", threads_section)
    register_section("requests", tracker.section)
    register_section("pools", pools_section)
    register_section("indexes", lambda: indexes_section(refresher))
    register_section("process", process_section)
    register_section("env", env_section)
    register_section("s3", s3_attribution.s3_section)
    s3_attribution.install()
    register_section("logs", logs_section)
    register_section("latency", latency_section)


def install_app(app, prefix, refresher):
    """Wire the dump into a ``create_app`` app: its sections, the log
    capture, the latency probes, the requests middleware (outermost: added
    last) and ``GET {prefix}/diag``."""
    from vmn_exp.ui.diag import routes
    from vmn_exp.ui.diag.requests import DiagRequestsMiddleware

    tracker = RequestTracker()
    app.state.diag_requests = tracker
    install_default_sections(refresher, tracker)
    install_log_capture()
    start_thread_probe()
    install_loop_probe(app)
    routes.register(app, prefix)
    app.add_middleware(DiagRequestsMiddleware, tracker=tracker)
