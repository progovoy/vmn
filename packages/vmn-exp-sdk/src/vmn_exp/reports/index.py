"""The per-workspace report index (plan 13 §8.2).

Header folds and latest revision numbers of every report, the panels each
report's latest revision points at (pinned verstrs; a query panel points at
its whole app) and per-run comment counts ``{total, unresolved}``. Built by
one full listing, then kept current from the change journal: a ``reports``
entry re-reads that report, a ``comments`` entry that run's thread. The state
(with the journal cursor) persists in a :class:`CacheStore`'s kv, so a
restart resumes instead of listing again. Rebuildable from storage at any time.
"""
import threading
import time

from vmn_exp.core.journal_reader import JournalReader
from vmn_exp.reports import comments
from vmn_exp.reports import store as rstore
from vmn_exp.reports.panels import panel_refs
from vmn_exp.storage.areas import COMMENTS, REPORTS, app_name_of
from vmn_exp.storage.journal import JOURNAL_MAX_AGE_SEC
from vmn_exp.storage.journal_sinks import journal_list_fn

KV_SCOPE = "reports-index"
KV_FORMAT = "1"
FULL_SWEEP_SEC = 300


def thread_counts(folded):
    """``{total, unresolved}`` of a folded thread: live comments, and live
    top-level ones not resolved (replies live in their thread)."""
    live = [c for c in folded if not c["deleted"]]
    open_ = [c for c in live if not c["resolved"] and not c.get("reply_to")]
    return {"total": len(live), "unresolved": len(open_)}


def _row(report):
    return {k: v for k, v in report.items() if k != "body"}


def _no_journal(prefix, start_after):
    return []


def _list_fn(storage):
    try:
        return journal_list_fn(storage)
    except AttributeError:  # a backend without a journal sink
        return _no_journal


class ReportIndex:
    def __init__(self, storage, cache=None, clock=time.time, full_sweep_sec=FULL_SWEEP_SEC):
        self._storage = storage
        self._cache = cache
        self._clock = clock
        self._full_sweep_sec = full_sweep_sec
        self._list = _list_fn(storage)
        self._lock = threading.Lock()
        self._reader = None
        self._swept_at = None
        self._state = {"reports": {}, "refs": {}, "comments": {}}
        self.generation = 0

    # -- reads ---------------------------------------------------------------

    def reports(self):
        return sorted(self._state["reports"].values(), key=lambda r: r["rid"])

    def using(self, app, verstr=None):
        """Rids whose panels show *app* (a pinned *verstr*, or a query on it)."""
        def shows(refs):
            return any(a == app and (verstr is None or pinned is None or verstr in pinned)
                       for a, pinned in refs)
        return sorted(rid for rid, refs in self._state["refs"].items() if shows(refs))

    def comment_counts(self, app):
        return dict(self._state["comments"].get(app, {}))

    # -- refresh -------------------------------------------------------------

    def refresh(self):
        with self._lock:
            if self._reader is None and not self._load_cached():
                self._rebuild()
            elif self._sweep_due():
                self._rebuild()
            else:
                self._follow()

    def _sweep_due(self):
        return (self._full_sweep_sec is not None
                and self._clock() - self._swept_at >= self._full_sweep_sec)

    def _load_cached(self):
        cached = self._cache and self._cache.kv_get(KV_SCOPE, KV_FORMAT)
        if not cached:
            return False
        last_seen_ms = (cached.get("cursor") or {}).get("last_seen_ms") or 0
        if self._clock() * 1000 - last_seen_ms > JOURNAL_MAX_AGE_SEC * 1000 / 2:
            return False
        self._state = cached["state"]
        self._swept_at = cached["swept_at"]
        self._reader = JournalReader(self._list, self._clock, last_seen_ms=last_seen_ms)
        self._follow()
        return True

    def _rebuild(self):
        now = self._clock()
        reader = JournalReader(self._list, self._clock, last_seen_ms=int(now * 1000))
        reports = {r["rid"]: r for r in rstore.list_reports(self._storage)}
        state = {
            "reports": {rid: _row(r) for rid, r in reports.items()},
            "refs": {rid: panel_refs(r["body"]) for rid, r in reports.items()},
            "comments": self._all_counts(),
        }
        self._reader, self._swept_at = reader, now
        self._replace(_jsonable(state))

    def _follow(self):
        tick = self._reader.tick()
        state = _copy(self._state)
        for area, key in set(tick.entries) | tick.overflow:
            if area == REPORTS:
                self._reload_report(state, key)
            elif area == COMMENTS and (area, key) in tick.overflow:
                state["comments"][app_name_of(key)] = self._app_counts(app_name_of(key))
            elif area == COMMENTS:
                for name in {k.name for k in tick.entries[(area, key)]}:
                    self._reload_thread(state, app_name_of(key), name)
        self._replace(_jsonable(state))

    def _replace(self, state):
        if state != self._state:
            self._state = state
            self.generation += 1
        if self._cache:
            self._cache.kv_put(KV_SCOPE, KV_FORMAT, {
                "state": self._state, "swept_at": self._swept_at,
                "cursor": self._reader.cursor})

    def _reload_report(self, state, rid):
        report = rstore.get(self._storage, rid)
        if report is None:
            state["reports"].pop(rid, None)
            state["refs"].pop(rid, None)
            return
        state["reports"][rid] = _row(report)
        state["refs"][rid] = panel_refs(report["body"])

    def _reload_thread(self, state, app, verstr):
        counts = thread_counts(comments.thread(self._storage, ("run", app, verstr)))
        per_app = state["comments"].setdefault(app, {})
        if counts["total"]:
            per_app[verstr] = counts
        else:
            per_app.pop(verstr, None)
        if not per_app:
            state["comments"].pop(app, None)

    def _all_counts(self):
        apps = self._storage.in_area(COMMENTS).list_apps()
        found = {app: self._app_counts(app) for app in apps}
        return {app: counts for app, counts in found.items() if counts}

    def _app_counts(self, app):
        area = self._storage.in_area(COMMENTS)
        found = {v: thread_counts(comments.thread(self._storage, ("run", app, v)))
                 for v in area.list_verstrs(app)}
        return {v: counts for v, counts in found.items() if counts["total"]}


def _copy(state):
    return {"reports": dict(state["reports"]), "refs": dict(state["refs"]),
            "comments": {app: dict(c) for app, c in state["comments"].items()}}


def _jsonable(state):
    """Tuples as lists, so a state equals its kv round trip."""
    refs = {rid: [[app, pinned] for app, pinned in r] for rid, r in state["refs"].items()}
    return dict(state, refs=refs)
