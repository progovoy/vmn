#!/usr/bin/env python3
"""The rollup gauges ``/metrics`` serves (plan 28 T2a) for every app an
index serves (:mod:`~vmn_exp.ui.rollup_gauges`), from the snapshot it last
published: a scrape never loads, refreshes or waits for an index, so an app
nobody asked for since the server started is absent, and one still loading
(or not published yet) reports its freshness only. Each app's gauges are
computed once per published snapshot and minute (under its conf / store
settings, as the board reads them: ``LeaderboardCache.conf_of``), so
scrapes in between cost a lookup. A background server keeps the snapshots
current unwatched (keep-warm, :mod:`~vmn_exp.ui.refresher`); an inline one
answers from the last request's. An app that fails to read (its store
settings, say) is logged and left out of that scrape."""
import logging

import vmn_exp.core.status as experiment_status
from vmn_exp.core.app_settings import attention_entries
from vmn_exp.core.metric_schema import effective_schema
from vmn_exp.ui.config import DEFAULT_METRICS_ENDED_HOURS
from vmn_exp.ui.job_rollup_cache import minute
from vmn_exp.ui.memo import LRU
from vmn_exp.ui.prometheus import exposition
from vmn_exp.ui.rollup_gauges import app_samples, freshness_sample, new_families

_LOGGER = logging.getLogger(__name__)
APPS_KEPT = 256


class MetricsFeed:
    def __init__(self, source, workspace_of, cache, ended_hours=DEFAULT_METRICS_ENDED_HOURS):
        """*source*: the :class:`~vmn_exp.ui.experiment_source.ExperimentSource`;
        *workspace_of(name)* -> the workspace or None; *cache*: the board's
        :class:`~vmn_exp.ui.leaderboard_cache.LeaderboardCache`; an ended
        outer run is reported for *ended_hours*."""
        self._source, self._workspace_of, self._cache = source, workspace_of, cache
        self.ended_hours = ended_hours
        self._samples = LRU(APPS_KEPT)

    def text(self):
        families, now = new_families(), experiment_status._now()
        for ws_name, app_name in self._source.served_apps():
            ws = self._workspace_of(ws_name)
            if ws is None:
                continue
            labels = {"workspace": ws_name, "app": app_name}
            for gauge, sample_labels, value in self._app(labels, ws, app_name, now):
                families[gauge].add(sample_labels, value)
        return exposition(families.values())

    def _app(self, labels, ws, app_name, now):
        as_of = self._source.as_of(ws.name, app_name)
        samples = [] if as_of is None else [freshness_sample(labels, as_of, now)]
        try:
            snapshot = self._source.published(ws, app_name)
            if snapshot is None or snapshot.loading is not None:
                return samples
            return samples + self._samples.per_snapshot(
                snapshot, lambda: self._computed(labels, ws, app_name, snapshot, now),
                key=(ws.name, minute()))
        except Exception as exc:
            _LOGGER.warning("Skipped %s/%s's gauges on /metrics: %s", ws.name, app_name, exc)
            return samples

    def _computed(self, labels, ws, app_name, snapshot, now):
        conf, ui = self._cache.conf_of(snapshot)
        board = self._source.published(ws, app_name, conf)
        schema = effective_schema(conf, board.declared_schema())
        return app_samples(labels, self._cache, board, schema, attention_entries(ui), now,
                           self.ended_hours * 3600)
