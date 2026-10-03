"""ISO timestamps <-> int64 microseconds, losslessly (plan 12 D5)."""
import datetime

import pytest

from vmn_exp._base import now_iso
from vmn_exp.core.metric_time import iso_to_us, us_to_iso


@pytest.mark.parametrize("iso", [
    "2026-10-02T12:00:00.123456Z",
    "2026-10-02T12:00:00Z",
    "1999-01-01T00:00:00.000001Z",
])
def test_round_trip_is_exact(iso):
    assert us_to_iso(iso_to_us(iso)) == iso


def test_now_iso_round_trips():
    iso = now_iso()
    assert us_to_iso(iso_to_us(iso)) == iso


def test_offsets_are_normalised_to_utc():
    assert iso_to_us("2026-10-02T14:00:00+02:00") == iso_to_us("2026-10-02T12:00:00Z")


def test_microseconds_since_epoch():
    epoch = datetime.datetime(1970, 1, 1, 0, 0, 1, tzinfo=datetime.timezone.utc)
    assert iso_to_us(epoch.isoformat()) == 1_000_000


def test_a_missing_or_bad_timestamp_is_none():
    assert iso_to_us(None) is None
    assert iso_to_us("not a time") is None
