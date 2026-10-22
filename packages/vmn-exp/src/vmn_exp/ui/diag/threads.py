#!/usr/bin/env python3
"""The ``threads`` section: every thread's Python stack, identical stacks
collapsed into one group with a count (a pool's idle workers are one)."""
import sys
import threading
import traceback


def _thread_info(ident, threads):
    thread = threads.get(ident)
    if thread is None:
        return {"name": "(not a threading.Thread)", "ident": ident, "daemon": None}
    return {"name": thread.name, "ident": ident, "daemon": thread.daemon}


def threads_section():
    """``{"count", "groups": [{"count", "threads", "stack"}]}``, the largest
    group first."""
    frames = sys._current_frames()
    threads = {t.ident: t for t in threading.enumerate()}
    groups = {}
    for ident, frame in frames.items():
        stack = tuple(line.rstrip("\n") for line in traceback.format_stack(frame))
        groups.setdefault(stack, []).append(_thread_info(ident, threads))
    del frames  # frames keep their locals alive
    ordered = sorted(groups.items(), key=lambda item: -len(item[1]))
    return {
        "count": sum(len(members) for _, members in ordered),
        "groups": [{"count": len(members), "threads": members, "stack": list(stack)}
                   for stack, members in ordered],
    }
