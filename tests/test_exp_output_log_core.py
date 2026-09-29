"""The capped ``output.log`` a run keeps of its console output.

Bytes in, bytes out: nothing is decoded, so a child printing Latin-1 or a
progress bar's raw control codes can never make capture fail. Past the cap
the start and the end are kept — a crash's traceback is at the end, and the
config a job printed is at the start.
"""
import os
import threading

from helpers import _bootstrap, _exp, _storage, extract_dev_verstr

from vmn_exp.core import output_log as ol


def test_small_output_is_kept_verbatim():
    log = ol.OutputLog(cap_bytes=1000)
    log.write(b"hello ")
    log.write(b"world\n")
    assert log.render() == b"hello world\n"


def test_output_past_the_cap_keeps_head_and_tail_with_an_omission_marker():
    log = ol.OutputLog(cap_bytes=100)
    log.write(b"H" * 50)
    for _ in range(100):
        log.write(b"m" * 10)
    log.write(b"T" * 50)

    out = log.render()
    assert out.startswith(b"H" * 50)
    assert out.endswith(b"T" * 50)
    assert b"mm" not in out
    assert b"1000 bytes of output omitted" in out
    marker = out[50:-50]
    assert len(out) - len(marker) == 100


def test_one_huge_write_is_capped_too():
    log = ol.OutputLog(cap_bytes=10)
    log.write(bytes(range(256)) * 4)
    out = log.render()
    data = bytes(range(256)) * 4
    assert out.startswith(data[:5])
    assert out.endswith(data[-5:])
    assert b"1014 bytes of output omitted" in out


def test_non_utf8_bytes_are_stored_untouched():
    log = ol.OutputLog(cap_bytes=1000)
    raw = b"caf\xe9 \xff\xfe\x00 \x1b[31mred\x1b[0m\n"
    log.write(raw)
    assert log.render() == raw


def test_dirty_tracks_writes_since_the_last_render_was_taken():
    log = ol.OutputLog(cap_bytes=1000)
    assert not log.dirty
    log.write(b"x")
    assert log.dirty
    log.take()
    assert not log.dirty
    log.write(b"y")
    assert log.dirty


def test_concurrent_writers_lose_no_bytes():
    log = ol.OutputLog(cap_bytes=10 ** 6)

    def spam(ch):
        for _ in range(500):
            log.write(ch * 10)

    threads = [threading.Thread(target=spam, args=(c,)) for c in (b"a", b"b")]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    out = log.render()
    assert out.count(b"a") == 5000 and out.count(b"b") == 5000


def test_cap_bytes_from_flag_then_env_then_default(monkeypatch):
    monkeypatch.delenv(ol.OUTPUT_CAP_ENV, raising=False)
    assert ol.output_cap_bytes(None) == ol.DEFAULT_OUTPUT_CAP_MB * 1024 * 1024
    monkeypatch.setenv(ol.OUTPUT_CAP_ENV, "2")
    assert ol.output_cap_bytes(None) == 2 * 1024 * 1024
    assert ol.output_cap_bytes(0.5) == 512 * 1024
    monkeypatch.setenv(ol.OUTPUT_CAP_ENV, "junk")
    assert ol.output_cap_bytes(None) == ol.DEFAULT_OUTPUT_CAP_MB * 1024 * 1024


def test_pump_tees_to_the_destination_and_the_sink(tmp_path):
    r, w = os.pipe()
    dest = tmp_path / "dest"
    got = []
    with open(dest, "wb") as f:
        os.write(w, b"one\ntwo \xff\n")
        os.close(w)
        ol.pump(r, f.fileno(), got.append)
    os.close(r)
    assert dest.read_bytes() == b"one\ntwo \xff\n"
    assert b"".join(got) == b"one\ntwo \xff\n"


def test_pump_keeps_draining_when_the_destination_or_sink_fails():
    r, w = os.pipe()
    os.write(w, b"a" * 1000)
    os.close(w)
    bad_fd = 987654  # not open

    def broken_sink(_):
        raise RuntimeError("boom")

    ol.pump(r, bad_fd, broken_sink)  # returns at EOF, never raises
    os.close(r)


def test_output_artifact_uploads_output_log_only_when_changed(app_layout, capfd):
    _bootstrap(app_layout)
    capfd.readouterr()
    assert _exp(app_layout.app_name, note="x") == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    storage = _storage(app_layout)

    art = ol.OutputArtifact(storage, app_layout.app_name, verstr, cap_bytes=1000)
    assert art.upload() is False  # nothing written yet
    art.write(b"line 1\n")
    assert art.upload() is True
    assert art.upload() is False
    path = storage.artifact_local_path(app_layout.app_name, verstr, ol.OUTPUT_LOG_NAME)
    with open(path, "rb") as f:
        assert f.read() == b"line 1\n"

    entry = art.artifact_entry()
    assert entry["type"] == "artifact"
    assert entry["path"] == ol.OUTPUT_LOG_NAME
    assert entry["size"] == len(b"line 1\n")
    assert entry["sha256"]
