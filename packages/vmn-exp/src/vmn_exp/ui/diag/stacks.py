#!/usr/bin/env python3
"""SIGUSR2 appends every thread's stack to ``<data-dir>/diag/stacks-<pid>.log``.

:mod:`faulthandler` writes it from the C signal handler, so it answers when
the SIGUSR1 JSON dump cannot: a Python handler runs only once the main thread
executes bytecode, which a pegged interpreter or a C call holding the GIL
never lets it do. It is py-spy's ``dump`` without ptrace or sudo.
"""
import faulthandler
import os
import signal

from vmn_exp.ui.diag.dump_files import dump_dir

# The open file faulthandler writes to: it must stay open for the process.
_FILES = []


def stacks_path(data_dir, pid=None):
    return os.path.join(dump_dir(data_dir), f"stacks-{pid or os.getpid()}.log")


def install_stack_dump(data_dir):
    """Dump all threads' stacks to :func:`stacks_path` on SIGUSR2."""
    os.makedirs(dump_dir(data_dir), exist_ok=True)
    out = open(stacks_path(data_dir), "a", buffering=1)
    _FILES.append(out)
    faulthandler.register(signal.SIGUSR2, file=out, all_threads=True, chain=False)
    return out.name
