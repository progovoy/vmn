"""The terminal view of a running uiload session: expected (oracle) vs API
status counts, mismatching jobs, rolling API latency and freshness."""
import collections
import dataclasses
import threading
import time

from uiload.probe_stats import percentile

STATUSES = ("created", "running", "stuck", "succeeded", "failed")
WINDOW_SEC = 10.0
MAX_MISMATCHES = 8


@dataclasses.dataclass
class Snapshot:
    elapsed_sec: float
    processes: int
    spawned_jobs: int
    expected: dict
    ambiguous: int
    api_live: dict
    api_hist: dict
    mismatches: list
    latency: dict  # route -> {count, p50, p95}
    freshness_sec: float = None


def render(snap):
    fresh = "-" if snap.freshness_sec is None else f"{snap.freshness_sec:.1f}s"
    lines = [
        f"uiload  t={snap.elapsed_sec:6.1f}s  processes={snap.processes}  "
        f"jobs spawned={snap.spawned_jobs}  freshness={fresh}",
        "",
        f"{'status':<10}{'expected':>10}{'api live':>10}{'api hist':>10}",
    ]
    for status in STATUSES:
        lines.append(f"{status:<10}{snap.expected.get(status, 0):>10}"
                     f"{snap.api_live.get(status, 0):>10}{snap.api_hist.get(status, 0):>10}")
    lines.append(f"{'(in flux)':<10}{snap.ambiguous:>10}")
    lines += ["", f"{'route':<18}{'n':>7}{'p50 ms':>9}{'p95 ms':>9}"]
    for route, stats in sorted(snap.latency.items()):
        lines.append(f"{route:<18}{stats['count']:>7}{stats['p50']:>9.1f}{stats['p95']:>9.1f}")
    if snap.mismatches:
        lines += ["", f"MISMATCHES ({len(snap.mismatches)}):"]
        lines += [f"  {m}" for m in snap.mismatches[:MAX_MISMATCHES]]
    return "\n".join(lines)


class LatencyWindow:
    """Rolling per-route latencies fed by ``Probe.run(on_sample=...)``."""

    def __init__(self, window_sec=WINDOW_SEC):
        self.window_sec = window_sec
        self._samples = collections.deque()
        self._lock = threading.Lock()

    def add(self, sample):
        with self._lock:
            self._samples.append((time.monotonic(), sample.route, sample.ms))

    def stats(self):
        cutoff = time.monotonic() - self.window_sec
        with self._lock:
            while self._samples and self._samples[0][0] < cutoff:
                self._samples.popleft()
            by_route = collections.defaultdict(list)
            for _, route, ms in self._samples:
                by_route[route].append(ms)
        return {route: {"count": len(v), "p50": percentile(v, 50), "p95": percentile(v, 95)}
                for route, v in by_route.items()}


def print_loop(snapshot_fn, stop, interval_sec=2.0):
    """Redraw ``render(snapshot_fn())`` until *stop* is set."""
    while not stop.wait(interval_sec):
        try:
            text = render(snapshot_fn())
        except Exception as exc:  # a slow/unavailable API must not kill the view
            text = f"(view refresh failed: {exc})"
        print("\033[2J\033[H" + text, flush=True)
