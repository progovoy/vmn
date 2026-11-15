"""LogBuffer writes a batch as parts (plan 40 C4): a failing part is re-queued
alone, so a part already stored is never written twice, and a part the store
refuses is dropped and reported instead of growing the queue forever."""
import pytest

from vmn_exp.sdk.log_buffer import LogBuffer


class _Write:
    """A recording ``write(entries)``; *results* answers each call in turn
    (an exception instance is raised)."""

    def __init__(self, *results):
        self.calls = []
        self._results = list(results)

    def __call__(self, entries):
        self.calls.append(list(entries))
        result = self._results.pop(0) if self._results else True
        if isinstance(result, BaseException):
            raise result
        return result


def _by_kind(batch):
    metrics = [e for e in batch if e["type"] == "metrics"]
    return [part for part in (metrics, [e for e in batch if e["type"] != "metrics"]) if part]


def _metric(step):
    return {"type": "metrics", "step": step}


def _note(text):
    return {"type": "note", "text": text}


def _buffer(write, refused=None):
    return LogBuffer(write, split=_by_kind,
                     on_refused=None if refused is None else refused.append)


def test_a_failure_in_the_second_part_requeues_only_that_part():
    write = _Write(True, OSError("disk full"))
    buf = _buffer(write)
    buf.append(_metric(0))
    buf.append(_note("a"))

    with pytest.raises(OSError):
        buf.flush()
    buf.flush()

    assert write.calls == [[_metric(0)], [_note("a")], [_note("a")]]


def test_the_requeued_part_stays_ahead_of_newer_entries():
    write = _Write(OSError("disk full"))
    buf = _buffer(write)
    buf.append(_metric(0))
    buf.append(_note("old"))
    with pytest.raises(OSError):
        buf.flush()
    buf.append(_note("new"))

    buf.flush()

    assert write.calls == [[_metric(0)], [_metric(0)], [_note("old"), _note("new")]]


def test_a_refused_part_is_dropped_and_reported_not_requeued():
    refused = []
    write = _Write(False)
    buf = _buffer(write, refused)
    buf.append(_note("a"))
    buf.append(_note("b"))

    buf.flush()
    buf.flush()

    assert write.calls == [[_note("a"), _note("b")]]
    assert refused == [2]


def test_a_refused_metric_part_still_writes_the_log_part():
    refused = []
    write = _Write(False, True)
    buf = _buffer(write, refused)
    buf.append(_metric(0))
    buf.append(_note("a"))

    buf.flush()

    assert write.calls == [[_metric(0)], [_note("a")]]
    assert refused == [1]


def test_without_a_splitter_the_batch_is_one_part():
    write = _Write()
    buf = LogBuffer(write)
    buf.append(_metric(0))
    buf.append(_note("a"))

    buf.flush()

    assert write.calls == [[_metric(0), _note("a")]]
