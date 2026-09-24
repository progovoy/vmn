"""`vmn exp run`'s remote log syncs run off the supervise loop, newest wins."""
import threading
import time
from unittest.mock import MagicMock

import pytest

from version_stamp.cli import experiment_supervisor as supervisor
from version_stamp.cli.experiment_supervisor import BackgroundSync


@pytest.fixture
def logger(monkeypatch):
    fake = MagicMock()
    monkeypatch.setattr(supervisor, "VMN_LOGGER", fake)
    return fake


def _warnings(logger):
    return [c.args[0] for c in logger.warning.call_args_list]


class _Sync:
    """A sync whose first call blocks until released."""

    def __init__(self, block_first=False):
        self.calls = 0
        self.release = threading.Event()
        self.started = threading.Event()
        if not block_first:
            self.release.set()

    def __call__(self):
        self.calls += 1
        self.started.set()
        self.release.wait(10)


def _wait_for(predicate, timeout=5):
    deadline = time.monotonic() + timeout
    while not predicate() and time.monotonic() < deadline:
        time.sleep(0.01)
    return predicate()


def test_request_syncs_in_the_background_and_final_syncs_once_more(logger):
    sync = _Sync()
    worker = BackgroundSync(sync)

    worker.request()
    assert _wait_for(lambda: sync.calls == 1)
    worker.final(5)

    assert sync.calls == 2
    assert _warnings(logger) == []


def test_a_request_made_mid_sync_is_queued_not_dropped(logger):
    sync = _Sync(block_first=True)
    worker = BackgroundSync(sync)

    worker.request()
    assert sync.started.wait(5)
    worker.request()
    worker.request()
    sync.release.set()

    assert _wait_for(lambda: sync.calls == 2)
    time.sleep(0.1)
    assert sync.calls == 2  # the two pending requests coalesced into one
    worker.final(5)
    assert sync.calls == 3


def test_final_is_skipped_when_a_sync_hangs(logger):
    sync = _Sync(block_first=True)
    worker = BackgroundSync(sync)

    worker.request()
    assert sync.started.wait(5)
    worker.final(0.2)

    assert _warnings(logger) == ["Experiment run: final sync skipped, a sync hangs"]
    sync.release.set()
    time.sleep(0.2)
    assert sync.calls == 1  # the skipped final sync never runs later


def test_a_slow_final_sync_times_out(logger):
    sync = _Sync(block_first=True)
    worker = BackgroundSync(sync)

    worker.final(0.2)

    assert sync.calls == 1
    assert _warnings(logger) == ["Experiment run: final sync timed out after 0.2s"]
    sync.release.set()
