"""VMN_EXP_MIN_STALE_SEC lowers (or raises) the stuck floor, so load tests and
demos see a hung run flip to ``stuck`` in seconds instead of a minute."""
import datetime

import pytest

from vmn_exp.core import status as st

NOW = datetime.datetime(2026, 9, 21, 12, 0, 0, tzinfo=datetime.timezone.utc)


def _running(heartbeat_age, interval=1):
    beat = (NOW - datetime.timedelta(seconds=heartbeat_age)).isoformat()
    return {"state": "running", "heartbeat": beat, "heartbeat_interval_sec": interval}


def test_env_lowers_the_floor(monkeypatch):
    monkeypatch.setenv("VMN_EXP_MIN_STALE_SEC", "5")
    assert st.stale_after_sec(_running(0)) == 5
    assert st.derive_status(_running(heartbeat_age=6), now=NOW) == st.STUCK


def test_interval_multiple_still_wins_over_a_low_floor(monkeypatch):
    monkeypatch.setenv("VMN_EXP_MIN_STALE_SEC", "5")
    assert st.stale_after_sec(_running(0, interval=10)) == 30


@pytest.mark.parametrize("raw", ["", "abc", "-3", "nan"])
def test_bad_values_keep_the_default_floor(monkeypatch, raw):
    monkeypatch.setenv("VMN_EXP_MIN_STALE_SEC", raw)
    assert st.stale_after_sec(_running(0)) == st.MIN_STALE_SEC


def test_unset_keeps_the_default_floor(monkeypatch):
    monkeypatch.delenv("VMN_EXP_MIN_STALE_SEC", raising=False)
    assert st.stale_after_sec(_running(0)) == st.MIN_STALE_SEC
