"""The run-detail log cache of a ``vmn-exp ui`` over a plain local root parses
a log again once it changed other than by an append — an in-place rewrite of
the same size included — so it always answers what a full parse does."""
import os

from vmn_exp.core.log import load_log
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.ui.readers.parsed_logs import ParsedLogs

APP, V, W = "app", "v1", "w"


def _note(n, text):
    return {"type": "note", "note": text, "timestamp": f"2026-01-01T00:00:0{n}Z"}


def _notes(cache, storage):
    return [entry["note"] for entry in cache.get(storage, APP, V, load_log).log()]


def _rewrite_in_place(path, old, new):
    data = open(path, "rb").read()
    stat = os.stat(path)
    with open(path, "r+b") as f:  # same size, same inode
        f.write(data.replace(old, new))
    os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns + 1_000_000))


def test_a_same_size_in_place_rewrite_is_parsed_again(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path / "store"))
    storage.save(APP, V, {"verstr": V, "timestamp": "2026-01-01T00:00:00Z"}, {})
    storage.append_log_entry(APP, V, W, _note(1, "aaaa"))
    cache = ParsedLogs()
    assert _notes(cache, storage) == ["aaaa"]
    storage.append_log_entry(APP, V, W, _note(2, "bbbb"))
    assert _notes(cache, storage) == ["aaaa", "bbbb"]

    log = os.path.join(storage._snapshot_dir(APP, V), "log", f"{W}.jsonl")
    _rewrite_in_place(log, b"bbbb", b"cccc")

    assert _notes(cache, storage) == ["aaaa", "cccc"]
    storage.append_log_entry(APP, V, W, _note(3, "dddd"))
    assert cache.get(storage, APP, V, load_log).log() == load_log(storage, APP, V)
    assert _notes(cache, storage) == ["aaaa", "cccc", "dddd"]
