"""Simulate a thread a signal interrupted while it held a lock: the SDK's
SIGTERM finalizer runs on a worker thread while the main thread sits in the
signal handler, wherever the signal caught it."""
import threading
import time


def frozen_in(obj, method):
    """Make *obj.method* block, on the first thread that calls it next, until
    the returned *release* event is set; *entered* is set once it blocks."""
    real, release, entered = getattr(obj, method), threading.Event(), threading.Event()
    frozen = []

    def blocking(*args, **kwargs):
        if not frozen:
            frozen.append(threading.current_thread())
        if threading.current_thread() is frozen[0]:
            entered.set()
            release.wait(60)
        return real(*args, **kwargs)

    setattr(obj, method, blocking)
    return entered, release


def in_thread(call):
    thread = threading.Thread(target=call, daemon=True)
    thread.start()
    return thread


def finishes_within(seconds, call):
    """``(finished, seconds taken)`` of *call* on a daemon thread."""
    done = threading.Event()
    start = time.monotonic()
    in_thread(lambda: (call(), done.set()))
    finished = done.wait(seconds)
    return finished, time.monotonic() - start
