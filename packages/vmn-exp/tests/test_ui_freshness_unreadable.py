"""An app status's ``freshness`` carries the records its index set aside
unread (``unreadable``, absent when none): the refresh succeeds around them,
so it is the dashboard's only sign of a throttled store."""
import pytest

pytest.importorskip("fastapi")
from test_ui_status_freshness import HEALTHY, IDLE, KEYS, OCT_22  # noqa: E402

from vmn_exp.ui.freshness import freshness, freshness_key  # noqa: E402

THROTTLED = {"count": 12, "store_errors": 12,
             "last_error": "ClientError('An error occurred (SlowDown) ...')"}


def test_set_aside_records_are_in_the_payload():
    fresh = freshness(HEALTHY, dict(IDLE, unreadable=THROTTLED))
    assert fresh["unreadable"] == THROTTLED
    assert set(fresh) == KEYS | {"unreadable"}
    assert not fresh["refresh_failing"]


def test_none_set_aside_leaves_it_out():
    assert "unreadable" not in freshness(HEALTHY, IDLE)


def test_the_count_moves_a_fresh_indexs_etag_key():
    now = OCT_22 + 10
    assert freshness_key(freshness(HEALTHY, dict(IDLE, unreadable=THROTTLED)), now) != (
        freshness_key(freshness(HEALTHY, IDLE), now))
    assert freshness_key(freshness(HEALTHY, dict(IDLE, unreadable=THROTTLED)), now) != (
        freshness_key(freshness(HEALTHY, dict(IDLE, unreadable=dict(THROTTLED, count=3))), now))
