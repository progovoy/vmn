#!/usr/bin/env python3
"""Log timestamps (``...Z`` ISO strings) as the int64 microseconds metric
streams store (plan 12 D5), and back — losslessly for every timestamp vmn
writes (:func:`vmn_exp._base.now_iso`)."""
import datetime

_EPOCH = datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
_US = datetime.timedelta(microseconds=1)


def iso_to_us(iso):
    """Microseconds since the epoch of *iso*; None when it is not a timestamp."""
    if not isinstance(iso, str):
        return None
    try:
        parsed = datetime.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=datetime.timezone.utc)
    return (parsed - _EPOCH) // _US


def us_to_iso(ts_us):
    """The ``...Z`` ISO string of *ts_us*, formatted as ``now_iso`` does."""
    moment = _EPOCH + datetime.timedelta(microseconds=int(ts_us))
    return moment.isoformat().replace("+00:00", "Z")
