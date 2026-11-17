"""The SDK's store.yml marker stamps and waits on the clock it is handed,
never on real time (CLAUDE.md "IO behind interfaces")."""
from datetime import datetime, timezone

import yaml

from fakes.clock import FakeClock
from vmn_exp.storage import store_marker

WHEN = datetime(2031, 5, 6, 7, 8, 9, tzinfo=timezone.utc)


class _Backend:
    """A local backend as root_of sees it (``root`` and ``area``)."""

    def __init__(self, root):
        self.root, self.area = root, "runs"


def test_new_marker_is_stamped_with_the_clock_it_is_handed():
    assert store_marker.new_marker(FakeClock(start=WHEN))["created_at"] == "2031-05-06T07:08:09Z"


def test_a_writer_creates_the_marker_at_the_clocks_time(tmp_path):
    store_marker.forget_checked()
    try:
        store_marker.check_store(_Backend(str(tmp_path)), True, FakeClock(start=WHEN))
    finally:
        store_marker.forget_checked()
    marker = yaml.safe_load((tmp_path / "store.yml").read_text())
    assert marker["created_at"] == "2031-05-06T07:08:09Z"
