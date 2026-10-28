"""Plan 28 P1 / D3: ``ago("1h")`` (also ``30m``, ``2d``) is the UTC ISO time
that long before now, so ``timestamp < ago("1h")`` compares like the stored
stamps do; it is evaluated when a query is compiled, never frozen in a cache."""
import datetime

import pytest
import vmn_exp.core.status as status_mod
from vmn_exp.core.query import (
    QueryError,
    compile_query,
    filter_rows,
    parse_query,
    pin_ago,
)
from vmn_exp.ui.query_sql import compile_sql

NOW = datetime.datetime(2026, 10, 28, 12, 0, 30, tzinfo=datetime.timezone.utc)


@pytest.fixture
def clock(monkeypatch):
    at = {"now": NOW}
    monkeypatch.setattr(status_mod, "_now", lambda now=None: now or at["now"])
    return at


def _row(verstr, timestamp, **kw):
    return {"verstr": verstr, "timestamp": timestamp, "metrics": {}, "params": {}, **kw}


ROWS = [
    _row("old", "2026-10-26T09:00:00.000001Z", status="created"),
    _row("hour", "2026-10-28T10:59:59Z", status="created"),
    _row("new", "2026-10-28T11:59:00.5Z", status="created"),
    _row("ran", "2026-10-28T09:00:00Z", status="running"),
    _row("none", None, status="created"),
]


def _verstrs(text, rows=ROWS):
    return [r["verstr"] for r in filter_rows(rows, text)]


@pytest.mark.parametrize("text, expected", [
    ('timestamp < ago("1h")', '"2026-10-28T11:00:30Z"'),
    ("timestamp < ago('30m')", '"2026-10-28T11:30:30Z"'),
    ('timestamp < ago("2d")', '"2026-10-26T12:00:30Z"'),
    ('timestamp < ago("0m")', '"2026-10-28T12:00:30Z"'),
    ('timestamp < ago( "90m" )', '"2026-10-28T10:30:30Z"'),
])
def test_ago_pins_to_the_iso_time_that_long_before_now(clock, text, expected):
    assert pin_ago(text) == f"timestamp < {expected}"


def test_pin_ago_takes_an_explicit_now():
    then = datetime.datetime(2026, 1, 1, 0, 0, tzinfo=datetime.timezone.utc)
    assert pin_ago('finished_at >= ago("1d")', now=then) == 'finished_at >= "2025-12-31T00:00:00Z"'


def test_waiting_for_over_an_hour(clock):
    assert _verstrs('status = "created" and timestamp < ago("1h")') == ["old", "hour"]
    assert _verstrs('timestamp >= ago("1h")') == ["new"]
    assert _verstrs('not timestamp < ago("1h")') == ["new", "none"]


def test_every_ago_of_a_query_is_pinned(clock):
    text = 'timestamp > ago("3d") and timestamp < ago("1h") or idx = 1'
    assert pin_ago(text) == ('timestamp > "2026-10-25T12:00:30Z" and '
                             'timestamp < "2026-10-28T11:00:30Z" or idx = 1')


def test_compiled_queries_follow_the_clock(clock):
    text = 'timestamp < ago("1h")'
    assert _verstrs(text) == ["old", "hour", "ran"]
    clock["now"] = NOW + datetime.timedelta(hours=1)
    assert _verstrs(text) == ["old", "hour", "new", "ran"]
    assert compile_query(text)(ROWS[2])


def test_parse_query_answers_the_pinned_tree(clock):
    assert parse_query('timestamp < ago("1h")') == (
        "cmp", ("path", ("timestamp",)), "<", "2026-10-28T11:00:30Z")


def test_a_query_without_ago_is_unchanged(clock):
    for text in ('note ~ "chicago"', 'note ~ \'ago("1h")\'', "idx > 1", "", None):
        assert pin_ago(text) == text
    assert _verstrs('note ~ "ago(1h)"', [_row("x", None, note="ago(1h)")]) == ["x"]


@pytest.mark.parametrize("text", [
    'timestamp < ago("1x")', 'timestamp < ago("h")', 'timestamp < ago("-1h")',
    'timestamp < ago("1.5h")', 'timestamp < ago("1 h")', 'timestamp < ago("1H")',
    'timestamp < ago(1)', 'timestamp < ago()', 'timestamp < ago("1h"',
    'timestamp < ago("1h", "2h")', "timestamp < ago", 'timestamp = ago("1h")',
    'timestamp != ago("1h")', 'timestamp ~ ago("1h")', 'timestamp in (ago("1h"))',
    'ago("1h") > timestamp', 'ago = 1',
])
def test_bad_ago_is_a_query_error(clock, text):
    with pytest.raises(QueryError):
        compile_query(text)
    with pytest.raises(QueryError):
        pin_ago(text)


def test_a_bad_ago_reports_its_own_offset(clock):
    with pytest.raises(QueryError, match="at offset 16"):
        compile_query('timestamp < ago("1x")')


def test_an_error_after_ago_reports_the_offset_in_the_text_given(clock):
    with pytest.raises(QueryError, match="at offset 32"):
        compile_query('timestamp < ago("1h") and idx > statuz')


def test_the_sql_backend_compares_the_pinned_time(clock):
    where, params = compile_sql('timestamp < ago("1h")')
    assert "2026-10-28T11:00:30Z" in params.values()
    assert "COLLATE" in where
