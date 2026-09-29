"""What keeping ``output.log`` up to date costs a running job.

A periodic upload re-sends the whole object, so they are throttled to a
bandwidth budget; the final one is never throttled and uploads exactly the
bytes its log entry describes. The log/state sync goes first: a slow output
PUT must not hold back the liveness data.
"""
import hashlib
from types import SimpleNamespace

from vmn_exp.cli.run import _Supervision
from vmn_exp.core import output_log as ol


class _RecordingStorage:
    def __init__(self, calls=None):
        self.calls = [] if calls is None else calls
        self.uploads = []

    def save_artifact_file(self, app_name, verstr, src_path, name=None):
        with open(src_path, "rb") as f:
            self.uploads.append(f.read())
        self.calls.append("output upload")
        return True

    def sync_log_to_remote(self, app_name, verstr, writer_id):
        self.calls.append("log sync")


class _Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _artifact(storage, clock, cap=10 * 1024 * 1024):
    return ol.OutputArtifact(storage, "app", "0.0.1-dev.1", cap, clock=clock)


def test_periodic_uploads_of_a_big_log_are_throttled_to_the_budget():
    storage, clock = _RecordingStorage(), _Clock()
    art = _artifact(storage, clock)
    size = 16 * ol.UPLOAD_BYTES_PER_SEC  # 16 seconds of budget per upload
    art.write(b"x" * size)
    assert art.upload() is True  # the first one always goes

    art.write(b"y")
    clock.now += 5
    assert art.upload() is False  # too soon for an object this big
    clock.now += 12
    assert art.upload() is True
    assert len(storage.uploads) == 2


def test_a_small_log_uploads_on_every_sync_that_has_new_bytes():
    storage, clock = _RecordingStorage(), _Clock()
    art = _artifact(storage, clock)
    art.write(b"a\n")
    assert art.upload() is True
    art.write(b"b\n")
    clock.now += 1
    assert art.upload() is True


def test_the_sealed_log_uploads_at_once_and_matches_its_entry():
    storage, clock = _RecordingStorage(), _Clock()
    art = _artifact(storage, clock)
    art.write(b"x" * (16 * ol.UPLOAD_BYTES_PER_SEC))
    assert art.upload() is True
    art.write(b"last line\n")

    entry = art.seal()
    art.write(b"after the seal\n")  # a straggler: not part of the sealed log
    assert art.upload() is True  # not throttled, however soon
    assert art.upload() is False

    final = storage.uploads[-1]
    assert final.endswith(b"last line\n")
    assert entry["path"] == ol.OUTPUT_LOG_NAME
    assert entry["size"] == len(final)
    assert entry["sha256"] == hashlib.sha256(final).hexdigest()


def test_the_supervisor_syncs_the_log_before_uploading_output():
    calls = []
    storage = _RecordingStorage(calls)
    output = _artifact(storage, _Clock())
    output.write(b"hello\n")
    fake = SimpleNamespace(
        storage=storage,
        output=output,
        app_name="app",
        verstr="0.0.1-dev.1",
        writer_id="w",
        guard=lambda _what, fn, *a: fn(*a),
    )
    _Supervision._sync_once(fake)
    assert calls == ["log sync", "output upload"]
