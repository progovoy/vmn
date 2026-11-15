"""A run's log sync: periodic failures stay at debug, a failed final sync is
retried and reported by close().
"""
import logging

from final_upload_fakes import WAIT_SEC, FailingJob, FakeAbandon

from vmn_exp.sdk.background_gate import BackgroundGate
from vmn_exp.sdk.log_sync import LogSync


def _sync(job, abandon):
    return LogSync(job, BackgroundGate(), abandon)


def test_a_failed_final_log_sync_is_retried():
    job, abandon = FailingJob(failures=1), FakeAbandon()
    sync = _sync(job, abandon)

    sync.submit(final=True)

    assert sync.close(WAIT_SEC) is True
    assert job.calls == 2
    assert abandon.delays == [0.5]


def test_close_reports_a_final_sync_that_never_landed():
    job, abandon = FailingJob(failures=100), FakeAbandon(blocking=True)
    sync = _sync(job, abandon)

    sync.submit(final=True)
    assert abandon.waiting.wait(WAIT_SEC)

    assert sync.close(0) is False
    assert isinstance(sync.last_error, OSError)


def test_periodic_sync_failures_stay_at_debug(caplog):
    job, abandon = FailingJob(failures=100), FakeAbandon()
    sync = _sync(job, abandon)

    with caplog.at_level(logging.DEBUG):
        sync.submit()
        assert sync.close(WAIT_SEC) is True

    assert job.calls == 1
    assert abandon.delays == []
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING]
