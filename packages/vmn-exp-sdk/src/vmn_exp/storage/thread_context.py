#!/usr/bin/env python3
"""Pool work in the submitter's :mod:`contextvars` context.

A ``ThreadPoolExecutor`` worker runs in its own context, so a value the
caller set (the ``vmn-exp ui`` diagnostic dump's current request, which its
S3 statistics attribute calls to) is not visible there.
"""
import contextvars


def in_caller_context(fn):
    """*fn* wrapped so every call runs in a copy of this thread's context now
    (a copy per call: one context cannot be entered by two threads at once)."""
    context = contextvars.copy_context()

    def run(*args, **kwargs):
        return context.copy().run(fn, *args, **kwargs)

    return run
