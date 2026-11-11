"""contained_artifact_path: a stored file the UI serves stays in its record dir."""
import os

from vmn_exp.ui.security import contained_artifact_path


class FakeStorage:
    def __init__(self, record_dir, path):
        self.record_dir = record_dir
        self.path = path

    def local_record_dir(self, app_name, verstr):
        return self.record_dir

    def artifact_local_path(self, app_name, verstr, name):
        return self.path


def _record(tmp_path):
    record = tmp_path / "record"
    (record / "artifacts").mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "secret").write_text("secret")
    return record, outside


def test_contained_artifact_path_refuses_a_path_outside_the_record_dir(tmp_path):
    record, outside = _record(tmp_path)
    link = record / "artifacts" / "link"
    os.symlink(outside / "secret", link)
    storage = FakeStorage(str(record), str(link))
    assert contained_artifact_path(storage, "app", "1.0.0", "artifacts/link") is None


def test_contained_artifact_path_refuses_a_path_under_a_symlinked_parent(tmp_path):
    record, outside = _record(tmp_path)
    os.symlink(outside, record / "artifacts" / "dir")
    path = str(record / "artifacts" / "dir" / "secret")
    storage = FakeStorage(str(record), path)
    assert contained_artifact_path(storage, "app", "1.0.0", "artifacts/dir/secret") is None


def test_contained_artifact_path_returns_a_path_inside_it(tmp_path):
    record, _ = _record(tmp_path)
    inside = record / "artifacts" / "model.bin"
    inside.write_bytes(b"m")
    storage = FakeStorage(str(record), str(inside))
    assert contained_artifact_path(storage, "app", "1.0.0", "artifacts/model.bin") == str(inside)


def test_contained_artifact_path_passes_through_when_backend_has_no_record_dir(tmp_path):
    cached = tmp_path / "cache" / "model.bin"
    storage = FakeStorage(None, str(cached))
    assert contained_artifact_path(storage, "app", "1.0.0", "artifacts/model.bin") == str(cached)


def test_contained_artifact_path_passes_through_a_backend_cache_outside_the_record_dir(tmp_path):
    # A local+remote store with the record dir present locally but the file
    # only remote: the backend downloaded it to its own cache.
    record, _ = _record(tmp_path)
    cached = tmp_path / "cache" / "model.bin"
    storage = FakeStorage(str(record), str(cached))
    assert contained_artifact_path(storage, "app", "1.0.0", "artifacts/model.bin") == str(cached)


def test_contained_artifact_path_is_none_when_the_backend_has_no_file(tmp_path):
    record, _ = _record(tmp_path)
    storage = FakeStorage(str(record), None)
    assert contained_artifact_path(storage, "app", "1.0.0", "artifacts/nope") is None
