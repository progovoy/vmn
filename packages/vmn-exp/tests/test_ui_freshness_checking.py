"""An app status's ``freshness`` carries an upgrade's background check of
compacted runs (``checking {done, total}``, absent when none), so the
dashboard says so instead of a silent wait."""
import pytest

pytest.importorskip("fastapi")
from test_ui_status_freshness import HEALTHY, IDLE, KEYS, OCT_22  # noqa: E402

from vmn_exp.ui.freshness import freshness, freshness_key  # noqa: E402

CHECKING = {"done": 120_000, "total": 734_000}


def test_the_check_is_in_the_payload():
    fresh = freshness(HEALTHY, dict(IDLE, checking=CHECKING))
    assert fresh["checking"] == CHECKING
    assert set(fresh) == KEYS | {"checking"}


def test_no_check_leaves_it_out():
    assert "checking" not in freshness(HEALTHY, IDLE)


def test_the_etag_key_moves_by_the_thousand_checked():
    now = OCT_22 + 10

    def key(done):
        return freshness_key(freshness(HEALTHY, dict(IDLE, checking=dict(CHECKING, done=done))), now)

    assert key(120_000) == key(120_400)
    assert key(120_000) != key(121_000)
