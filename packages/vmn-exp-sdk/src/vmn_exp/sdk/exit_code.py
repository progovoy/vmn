#!/usr/bin/env python3
"""The exit code ``sys.exit(N)`` gave the process, for runs left open at exit.

``SystemExit`` never reaches ``sys.excepthook``, so the atexit finalizer could
not tell ``sys.exit(3)`` from a clean exit. Wrapping ``sys.exit`` notes the
code. Only the main thread's call counts: elsewhere it ends one thread, not the
process. A hand-written ``raise SystemExit(N)`` and ``os._exit(N)`` stay unseen.
"""
import threading


def exit_status(code):
    """The process exit code ``sys.exit(code)`` gives, as the interpreter
    computes it: ``None`` is 0, a non-int (a message) is 1, an int is itself."""
    if code is None:
        return 0
    return code if isinstance(code, int) else 1


class ExitCodeNote:
    def __init__(self):
        self._code = None
        self._wrapper = None

    def install(self, sys_module):
        """Wrap ``sys_module.exit`` (once), chaining to the exit that was current."""
        if self._wrapper is not None and sys_module.exit is self._wrapper:
            return
        previous = sys_module.exit

        def exit(*args):
            if threading.current_thread() is threading.main_thread():
                self._code = args[0] if args else None
            return previous(*args)

        self._wrapper = exit
        sys_module.exit = exit

    def noted(self):
        """The exit code of the noted ``sys.exit``; 0 when none was noted."""
        return exit_status(self._code)

    def clear(self):
        self._code = None
