#!/usr/bin/env python3
"""A new index generation's board, computed off the request path (the
refresher's ``on_refresh`` and the startup warm-up): its base, search index,
the app's facets and each top view's first page as the web client asks for
it (``sort=idx`` newest first, offset 0, its page size; ``top=jobs``,
``top=singles``, ``top=1`` and All runs; never grouped, so no group
aggregate), under the app's conf / store settings, so the first browser
request after a refresh is a memo hit.

A generation superseded meanwhile (the startup warm-up still on generation N
while the refresher published N+1) is left alone, between steps too: its
answers would never be asked for. A snapshot supersedes another of the same
app when its generation is newer and they share rows by identity (one
index's generations do; another workspace's same-named app never does).
Failures are logged, never raised.
"""
import logging

from vmn_exp.core.activity import activity
from vmn_exp.core.metric_schema import effective_schema
from vmn_exp.core.traced_lock import TracedLock
from vmn_exp.ui.leaderboard_delta import same_index

# webui's firstPage: IDX_SORT, PAGE_SIZE (src/paging.ts).
DEFAULT_SORT = "idx"
DEFAULT_LIMIT = 200
# Outer runs, Single runs, Runs (an app without outer runs), All runs.
TOP_VIEWS = ("jobs", "singles", True, False)

_LOGGER = logging.getLogger(__name__)


class BoardWarmer:
    def __init__(self, cache):
        self._cache = cache
        self._newest = {}  # app name -> the newest snapshot warmed
        self._lock = TracedLock("board warmer")

    def superseded(self, snapshot):
        """Whether a newer generation of *snapshot*'s index was warmed."""
        newest = self._newest.get(snapshot.app_name)
        return (newest is not None and newest is not snapshot
                and newest.generation > snapshot.generation and same_index(newest, snapshot))

    def _note(self, snapshot):
        with self._lock:
            if self.superseded(snapshot):
                return False
            self._newest[snapshot.app_name] = snapshot
            return True

    def warm(self, snapshot):
        """Warm *snapshot*'s board in the cache as a request reads it: rows
        summarized by the app's conf / store settings schema
        (``cache.conf_of``) and sorted by it plus what they declare."""
        if not self._note(snapshot):
            return
        try:
            with activity("board warm", key=snapshot.app_name):
                for step in self._steps(snapshot):
                    if self.superseded(snapshot):
                        return
                    step()
        except Exception:
            _LOGGER.debug("Warming the board failed", exc_info=True)

    def _steps(self, snapshot):
        cache = self._cache
        conf_schema, _ = cache.conf_of(snapshot)
        board = snapshot.summarized(conf_schema)
        yield lambda: cache._base(board)
        yield lambda: cache.warm_search(board)
        yield lambda: cache.facets_payload(board)
        schema = effective_schema(conf_schema, board.declared_schema())
        for top in TOP_VIEWS:
            yield lambda top=top: cache.page(board, schema, sort=DEFAULT_SORT, offset=0,
                                             limit=DEFAULT_LIMIT, top=top)
