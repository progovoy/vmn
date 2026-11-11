from datetime import datetime, timedelta, timezone


class FakeClock:
    """A clock that moves only when told: ``sleep``/``advance`` move ``now``
    and ``monotonic`` together, and nothing really sleeps."""

    def __init__(self, start=datetime(2026, 1, 1, tzinfo=timezone.utc), monotonic=1000.0):
        self._now = start
        self._monotonic = monotonic

    def now(self):
        return self._now

    def monotonic(self):
        return self._monotonic

    def advance(self, sec):
        self._now += timedelta(seconds=sec)
        self._monotonic += sec

    def sleep(self, sec):
        self.advance(sec)
