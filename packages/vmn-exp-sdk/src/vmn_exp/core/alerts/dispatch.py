"""Building an alert and delivering it to every sink, best-effort.

Delivery never raises: a sink that fails is logged (a warning the first time
per sink, debug after) and the others still get the alert.
"""
import threading
import time

from vmn_exp._base import VMN_LOGGER, now_iso
from vmn_exp.core.background import join_all
from vmn_exp.core.best_effort import BestEffort

LEVELS = ("info", "warn", "error")

_RUN_STATE_FIELDS = ("host", "pid", "exit_code", "signal", "heartbeat", "finished_at")


def make_alert(trigger, app_name, run_id, title, text="", level="info",
               run_name=None, status=None, run_state=None):
    """The alert payload every sink receives (and the webhook POSTs as is)."""
    if level not in LEVELS:
        raise ValueError(f"alert level must be one of {', '.join(LEVELS)}, not {level!r}")
    alert = {
        "trigger": trigger,
        "title": str(title),
        "text": str(text or ""),
        "level": level,
        "app_name": app_name,
        "run_id": run_id,
        "run_name": run_name,
        "status": status,
        "timestamp": now_iso(),
    }
    for key in _RUN_STATE_FIELDS:
        alert[key] = (run_state or {}).get(key)
    return alert


class Alerter:
    """Sends alerts to one config's sinks; rate-limits by title on request."""

    def __init__(self, config, clock=time.monotonic):
        self.config = config
        self._clock = clock
        self._last_sent = {}  # title -> clock()
        self._lock = threading.Lock()
        self._threads = []
        self._guard = BestEffort(
            VMN_LOGGER, lambda what, exc: f"vmn: could not deliver an alert via {what}: {exc}"
        )

    def wants(self, trigger):
        return bool(self.config.sinks) and trigger in self.config.on

    def admit(self, title, wait_sec=None):
        """True unless *title* was admitted less than *wait_sec* ago."""
        wait = self.config.wait_sec if wait_sec is None else wait_sec
        now = self._clock()
        with self._lock:
            last = self._last_sent.get(title)
            if last is not None and now - last < wait:
                return False
            self._last_sent[title] = now
        return True

    def send(self, alert):
        """Deliver to every sink now; True if at least one took it."""
        delivered = False
        for sink in self.config.sinks:
            what = type(sink).__name__
            ok = self._guard(what, _send_one, sink, alert, self.config.timeout_sec)
            delivered = delivered or bool(ok)
        return delivered

    def send_async(self, alert):
        """Deliver on a daemon thread, so a slow endpoint never stalls the caller."""
        thread = threading.Thread(target=self.send, args=(alert,), daemon=True,
                                  name="vmn-alert")
        with self._lock:
            self._threads = [t for t in self._threads if t.is_alive()] + [thread]
        thread.start()

    def drain(self, timeout):
        """Wait up to *timeout* seconds for the alerts still being delivered."""
        with self._lock:
            threads = list(self._threads)
        join_all(threads, timeout)


def _send_one(sink, alert, timeout):
    sink.send(alert, timeout=timeout)
    return True
