"""``log_image``/``log_table`` never wait on the store: the training loop hands
the encoded file to the run's background uploader, and ``finish()`` waits for
what is still queued."""
import threading
import time

import pytest

from vmn_exp.sdk.run import Run
from vmn_exp.snapshot import LocalSnapshotStorage
from vmn_exp.storage.cached import CachedSnapshotStorage

APP = "app"
VERSTR = "0.0.1-dev.aaaaaaa.bbbbbbb"
_SLOW_SEC = 1.0


class _SlowArtifactStorage(CachedSnapshotStorage):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.uploading_threads = set()

    def save_artifact_file(self, app_name, verstr, src_path, name=None):
        self.uploading_threads.add(threading.current_thread().name)
        time.sleep(_SLOW_SEC)
        return super().save_artifact_file(app_name, verstr, src_path, name=name)


@pytest.fixture
def storage(tmp_path):
    st = _SlowArtifactStorage(LocalSnapshotStorage(str(tmp_path / "s"), "experiments"))
    st.save(APP, VERSTR, {"verstr": VERSTR, "timestamp": "2026-01-01T00:00:00Z"}, {})
    return st


def _png_path(tmp_path):
    from vmn_exp.core.png import encode_png

    path = tmp_path / "x.png"
    path.write_bytes(encode_png(bytes(3), 1, 1, 3))
    return str(path)


def test_log_image_and_log_table_return_without_waiting_on_the_store(
    storage, tmp_path
):
    run = Run(storage, APP, VERSTR, 60)
    run._open()
    started = time.monotonic()
    run.log_image("s", _png_path(tmp_path), step=0)
    run.log_table("t", [{"a": 1}], step=0)
    assert time.monotonic() - started < _SLOW_SEC

    run.finish()
    assert threading.main_thread().name not in storage.uploading_threads
    for name in ("media/s/0.png", "tables/t/0.json"):
        assert storage.artifact_local_path(APP, VERSTR, name) is not None
