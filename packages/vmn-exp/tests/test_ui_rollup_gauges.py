"""Plan 28 T2a units: the Prometheus text the ``/metrics`` gauges are written
in (label escaping, one HELP/TYPE per family, absent values left out) and
the feed's per-app reads: an app whose index has published nothing yet, or
is still loading it chunk by chunk, reports its freshness only; an app that
fails to read is left out, never the scrape."""
import datetime

import pytest
from prometheus_parse import label_sets, parse, value
from vmn_exp.core import status as status_mod
from vmn_exp.core.index_bulk import loading_snapshot
from vmn_exp.ui.leaderboard_cache import LeaderboardCache
from vmn_exp.ui.metrics_feed import MetricsFeed
from vmn_exp.ui.prometheus import Family, exposition, label_value

NOW = datetime.datetime(2026, 3, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)


@pytest.fixture(autouse=True)
def frozen(monkeypatch):
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or NOW)


def test_label_values_escape_backslash_quote_and_newline():
    assert label_value('a"b\\c\nd') == 'a\\"b\\\\c\\nd'


def test_a_family_renders_its_header_once_and_skips_absent_values():
    family = Family("vmn_x", "gauge", "An x.")
    family.add({"app": 'q"'}, 3)
    family.add({"app": "none"}, None)
    family.add({"app": "half"}, 0.5)
    text = exposition([family])
    assert text.count("# TYPE vmn_x gauge") == 1 and text.count("# HELP vmn_x An x.") == 1
    samples = parse(text)
    assert value(samples, "vmn_x", app='q"') == 3 and value(samples, "vmn_x", app="half") == 0.5
    assert value(samples, "vmn_x", app="none") is None


class _Ws:
    def __init__(self, name):
        self.name = name


class _Source:
    """The :class:`ExperimentSource` reads the feed makes, per app."""

    def __init__(self, apps):
        self.apps = apps  # {(ws, app): (published snapshot or None, as_of or None)}

    def served_apps(self):
        return sorted(self.apps)

    def published(self, ws, app_name, schema=None):
        snapshot = self.apps[(ws.name, app_name)][0]
        if isinstance(snapshot, Exception):
            raise snapshot
        return snapshot

    def as_of(self, ws_name, app_name):
        return self.apps[(ws_name, app_name)][1]


def _feed(apps):
    return MetricsFeed(_Source(apps), _Ws, LeaderboardCache())


def test_an_unpublished_or_loading_index_reports_its_freshness_only():
    as_of = NOW.timestamp() - 30
    samples = parse(_feed({("ws", "cold"): (None, None),
                           ("ws", "loading"): (loading_snapshot("loading", 10), as_of)}).text())
    assert value(samples, "vmn_index_freshness_seconds", workspace="ws", app="loading") == 30
    assert label_sets(samples, "vmn_index_freshness_seconds") == [
        {"workspace": "ws", "app": "loading"}]
    assert label_sets(samples, "vmn_runs") == []


def test_an_app_that_fails_to_read_is_left_out(caplog):
    as_of = NOW.timestamp() - 5
    samples = parse(_feed({("ws", "broken"): (OSError("store down"), as_of),
                           ("ws", "fine"): (None, as_of)}).text())
    apps = {s["app"] for s in label_sets(samples, "vmn_index_freshness_seconds")}
    assert apps == {"broken", "fine"}
    assert "store down" in caplog.text


def test_a_postgres_backed_index_answers_its_current_index_published_snapshot():
    from types import SimpleNamespace

    from vmn_exp.ui.elected_index import ElectedIndex

    index = ElectedIndex.__new__(ElectedIndex)
    index._leader, index._follower = SimpleNamespace(published="lead"), SimpleNamespace(published=None)
    index.leading = True
    assert index.published == "lead"
    index.leading = False
    assert index.published is None
