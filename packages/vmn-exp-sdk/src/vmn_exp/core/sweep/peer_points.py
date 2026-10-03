"""The median rule's input: each trial's target-metric points, read as little
as the rule allows.

A finished trial's series never changes, so it is read once and kept. A running
one is read again only once its logs or metric streams grew (one listing of
the record's files tells); a backend that cannot tell is read every time. Only the target metric
is kept out of each log.
"""
from vmn_exp.core.log import load_log
from vmn_exp.core.metric_files import is_metric_file
from vmn_exp.core.rewind import drop_rewound
from vmn_exp.core.series_reader import SeriesReader
from vmn_exp.core.sweep.early_stop import step_points
from vmn_exp.storage.files import log_sizes_of

_FINAL = object()


def metric_points(log, name):
    """:func:`step_points` of metric *name* in *log*."""
    return step_points(SeriesReader.from_entries(drop_rewound(log)).series(name))


class PeerPoints:
    """``of(verstr)``: the run's points, from a per-run cache."""

    def __init__(self, storage, app_name, metric):
        self._storage, self._app_name, self._metric = storage, app_name, metric
        self._cache = {}  # verstr -> (log signature or _FINAL, points)

    def of(self, verstr, finished=False):
        cached = self._cache.get(verstr)
        if cached is not None and cached[0] is _FINAL:
            return cached[1]
        signature = _FINAL if finished else self._log_signature(verstr)
        if cached is not None and signature and cached[0] == signature:
            return cached[1]
        log = load_log(self._storage, self._app_name, verstr)
        points = metric_points(log, self._metric)
        self._cache[verstr] = (signature, points)
        return points

    def _log_signature(self, verstr):
        """``{writer or metric object: bytes}`` of the run's logs and metric
        streams; empty when unknown."""
        record_files = getattr(self._storage, "record_files", None)
        files = record_files(self._app_name, verstr) if record_files else None
        if files is not None:
            sizes = log_sizes_of((name, sig[0]) for name, sig in files.items())
            sizes.update((n, sig[0]) for n, sig in files.items() if is_metric_file(n))
            return sizes
        sizes = self._storage.log_sizes(self._app_name, verstr)
        listing = getattr(self._storage, "metric_objects", None)
        for objects in (listing(self._app_name, verstr) if listing else {}).values():
            sizes.update(objects)
        return sizes
