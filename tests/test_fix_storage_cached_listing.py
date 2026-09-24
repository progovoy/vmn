"""Local+remote listings: the new listing methods merge both halves, and a remote
failure raises instead of passing for "the remote has nothing"."""
import pytest
from s3_helpers import cached_host, entry, meta, mocked_bucket


@pytest.fixture(autouse=True)
def _bucket(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield


def _two_hosts(tmp_path):
    a, b = cached_host(tmp_path, "a"), cached_host(tmp_path, "b")
    a.save("app", "va", meta("va"), {})
    b.save("app", "vb", meta("vb"), {})
    return a, b


def test_cached_list_record_names_unions_hosts(tmp_path):
    a, _ = _two_hosts(tmp_path)
    names = a.list_record_names("app")
    assert set(names) == {"va", "vb"}
    assert names["vb"] is None  # remote-only: no cheap change marker


def test_cached_record_names_carry_the_local_dir_signature(tmp_path):
    import os

    a, _ = _two_hosts(tmp_path)
    st = os.stat(os.path.join(a._local._snapshot_dir("app", "va")))
    assert a.list_record_names("app")["va"] == (st.st_mtime_ns, st.st_ino)


def test_cached_list_run_verstrs_merges_local_and_remote_for_that_code(tmp_path):
    a, b = cached_host(tmp_path, "a"), cached_host(tmp_path, "b")
    a.save("app", "0.0.1", meta("0.0.1"), {})
    b.save("app", "0.0.1.r2", meta("0.0.1.r2"), {})
    b.save("app", "9.9.9", meta("9.9.9"), {})  # an unrelated code_verstr

    assert a.list_run_verstrs("app", "0.0.1") == {"0.0.1", "0.0.1.r2"}


def test_cached_list_files_for_keys_merges_local_and_remote(tmp_path):
    a, _ = _two_hosts(tmp_path)
    files = a.list_files("app", keys=["va", "vb"])
    assert set(files) == {"va", "vb"}
    assert "metadata.yml" in files["va"] and "metadata.yml" in files["vb"]
    assert set(a.list_files("app", keys=["vb"])) == {"vb"}


def _break_remote(host, method):
    def fail(*args, **kwargs):
        raise ConnectionError("remote down")

    setattr(host._remote, method, fail)


@pytest.mark.parametrize(
    "method, call",
    [
        ("list_files", lambda h: h.list_files("app")),
        ("list_files", lambda h: h.list_files("app", keys=["va"])),
        ("list_record_names", lambda h: h.list_record_names("app")),
        ("list_snapshots", lambda h: h.list_snapshots("app")),
        ("list_verstrs", lambda h: h.list_verstrs("app")),
        ("list_run_verstrs", lambda h: h.list_run_verstrs("app", "va")),
    ],
)
def test_a_failing_remote_listing_raises(tmp_path, method, call):
    a, _ = _two_hosts(tmp_path)
    _break_remote(a, method)
    with pytest.raises(ConnectionError):
        call(a)


def test_a_failing_remote_log_read_raises_for_the_per_writer_read(tmp_path):
    a, b = _two_hosts(tmp_path)
    b.append_log_entry("app", "va", "wb", entry(1))
    b.sync_log_to_remote("app", "va", "wb")
    _break_remote(a, "log_sizes")
    with pytest.raises(ConnectionError):
        a.load_logs_by_writer("app", "va")


def test_the_merged_log_view_stays_best_effort(tmp_path):
    a, _ = _two_hosts(tmp_path)
    a.append_log_entry("app", "va", "wa", entry(0))
    _break_remote(a, "log_sizes")
    assert [e["values"]["i"] for e in a.load_merged_log("app", "va")] == [0]
