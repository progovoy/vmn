#!/usr/bin/env python3
"""``ago("1h")`` of the query language (plan 28 D3): a duration of whole
minutes, hours or days (``30m``, ``1h``, ``2d``) and the UTC ISO time that
long before now, second precision like the stored stamps, so it compares
with ``timestamp``/``started_at``/``finished_at`` as strings do. Pure."""
import datetime
import re

import vmn_exp.core.status as experiment_status

UNITS = {"m": 60, "h": 3600, "d": 86400}
_DURATION = re.compile(r"(\d+)([mhd])")
# The comparisons an ``ago()`` may stand on the right of.
ORDERED = ("<", "<=", ">", ">=")


def duration_sec(text):
    """Seconds in *text* (``"30m"``, ``"1h"``, ``"2d"``), else None."""
    match = _DURATION.fullmatch(text) if isinstance(text, str) else None
    return int(match[1]) * UNITS[match[2]] if match else None


def iso_before(seconds, now=None):
    """The UTC ISO time *seconds* before *now* (default the clock)."""
    now = (now or experiment_status._now()).astimezone(datetime.timezone.utc)
    return (now - datetime.timedelta(seconds=seconds)).strftime("%Y-%m-%dT%H:%M:%SZ")
