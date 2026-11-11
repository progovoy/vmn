"""ContainedReads: the server's reads of a local record refuse a file whose
real path leaves the record dir, and pass everything else through."""
from vmn_exp.ui.readers.contained_reads import ContainedReads

RECORD = "/store/runs/app/v1"
LINKS = {
    f"{RECORD}/metadata.yml": "/etc/server.yml",
    f"{RECORD}/outputs/output.log": "/proc/self/environ",
    f"{RECORD}/artifacts/big.ckpt": f"{RECORD}/artifacts/real.ckpt",
}


def fake_realpath(path):
    return LINKS.get(path, path)


class FakeStorage:
    def __init__(self, record_dir=RECORD):
        self.record_dir = record_dir
        self.calls = []

    def local_record_dir(self, app_name, verstr):
        return self.record_dir

    def load_metadata(self, app_name, verstr):
        self.calls.append("load_metadata")
        return {"verstr": verstr}

    def load_file(self, app_name, verstr, name):
        return b"file " + name.encode()

    def read_range(self, app_name, verstr, name, offset, length):
        return b"range " + name.encode()

    def read_file_from(self, app_name, verstr, name, offset):
        return b"from " + name.encode()

    def artifact_local_path(self, app_name, verstr, name):
        return f"{self.record_dir or '/cache'}/{name}"

    def list_artifacts(self, app_name, verstr):
        return [{"name": "outputs/output.log", "size": 3},
                {"name": "artifacts/big.ckpt", "size": 9},
                {"name": "artifacts/plain.txt", "size": 1}]

    def is_remote(self):
        return False


def _reads(storage=None):
    return ContainedReads(storage or FakeStorage(), fake_realpath)


def test_contained_reader_refuses_outside_realpath_and_delegates_inside():
    reads = _reads()
    assert reads.read_range("app", "v1", "outputs/output.log", 0, 3) is None
    assert reads.read_file_from("app", "v1", "outputs/output.log", 0) is None
    assert reads.load_file("app", "v1", "metadata.yml") is None
    assert reads.load_metadata("app", "v1") is None
    assert reads.artifact_local_path("app", "v1", "outputs/output.log") is None

    assert reads.read_range("app", "v1", "log/w.jsonl", 0, 3) == b"range log/w.jsonl"
    assert reads.read_file_from("app", "v1", "log/w.jsonl", 0) == b"from log/w.jsonl"
    assert reads.load_file("app", "v1", "run_state.yml") == b"file run_state.yml"
    assert reads.artifact_local_path("app", "v1", "artifacts/big.ckpt") == f"{RECORD}/artifacts/big.ckpt"


def test_listing_keeps_links_inside_the_record_dir_only():
    names = [a["name"] for a in _reads().list_artifacts("app", "v1")]
    assert names == ["artifacts/big.ckpt", "artifacts/plain.txt"]


def test_a_backend_without_a_local_record_dir_passes_through():
    reads = _reads(FakeStorage(record_dir=None))
    assert reads.read_range("app", "v1", "outputs/output.log", 0, 3) == b"range outputs/output.log"
    assert reads.artifact_local_path("app", "v1", "outputs/output.log") == "/cache/outputs/output.log"
    assert len(reads.list_artifacts("app", "v1")) == 3
    assert reads.load_metadata("app", "v1") == {"verstr": "v1"}


def test_metadata_inside_the_record_dir_is_read():
    storage = FakeStorage(record_dir="/store/runs/app/v2")
    assert _reads(storage).load_metadata("app", "v2") == {"verstr": "v2"}


def test_other_calls_go_to_the_wrapped_storage():
    assert _reads().is_remote() is False
