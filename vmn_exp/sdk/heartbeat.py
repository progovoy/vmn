#!/usr/bin/env python3
"""A periodic publisher for an in-process experiment run's liveness.

``vmn exp run`` refreshes the heartbeat from the loop that supervises the child
process. An SDK run supervises nothing — it *is* the workload — so it carries
its own thread.

Two properties matter more than accuracy of the cadence:

* it never dies quietly. A publisher that raises (a flaky S3 PUT, a full disk)
  would otherwise end the run's liveness while training continues, and the run
  would read as ``stuck`` to everyone looking at it.
* ``stop()`` returns promptly. It waits on an event rather than sleeping the
  interval, so finishing a run with a 30s heartbeat does not block for 30s.
"""
import logging
import threading

# Stdlib logging, not VMN_LOGGER: that one is a proxy that raises until the CLI
# calls init_stamp_logger, and an SDK user never goes through the CLI. A library
# emits records and lets the application decide what to do with them.
_LOGGER = logging.getLogger(__name__)


class Heartbeat:
    """Call ``publish`` every ``interval_sec`` on a daemon thread."""

    def __init__(self, publish, interval_sec):
        if not interval_sec or interval_sec <= 0:
            raise ValueError(f"heartbeat interval must be positive, got {interval_sec}")
        self._publish = publish
        self._interval_sec = interval_sec
        self._stop = threading.Event()
        self._thread = None

    @property
    def alive(self):
        return self._thread is not None and self._thread.is_alive()

    def start(self):
        """Begin publishing. A second call is a no-op."""
        if self._thread is not None:
            return
        self._stop.clear()
        # Daemon: a forgotten run must never wedge interpreter exit.
        self._thread = threading.Thread(
            target=self._loop, name="vmn-heartbeat", daemon=True
        )
        self._thread.start()

    def stop(self):
        """Stop publishing and join the thread. Idempotent."""
        self._stop.set()
        thread, self._thread = self._thread, None
        if thread is not None:
            thread.join(timeout=self._interval_sec + 5)

    def _loop(self):
        while not self._stop.wait(self._interval_sec):
            try:
                self._publish()
            except Exception:
                # Liveness is best-effort: losing one beat is survivable,
                # losing the thread is not.
                _LOGGER.debug("Heartbeat publish failed", exc_info=True)

    def __enter__(self):
        self.start()
        return self

    def __exit__(self, exc_type, exc, tb):
        self.stop()
        return False
