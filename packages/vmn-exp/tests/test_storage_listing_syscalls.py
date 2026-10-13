"""A record directory's listing skips the folders it does not have
(plan 23 S9).

Most records have a ``log/`` folder and no ``metrics/`` one. Opening and
stat-ing the missing one cost two failing syscalls per record per full
listing — at 100k records a second or more where every open is slow. A
scan opens only the folders its stat found, and a settled record whose own
signature has not moved (a folder created in it would move it) stats only
the folders it had.
"""
import os
import time

import pytest

from vmn_exp.storage import listing

HOUR_NS = 3600 * 10**9


@pytest.fixture
def record(tmp_path):
    path = tmp_path / "rec"
    (path / "log").mkdir(parents=True)
    (path / "metadata.yml").write_text("verstr: x\n")
    (path / "log" / "w.jsonl").write_text("{}\n")
    then = time.time_ns() - HOUR_NS
    for p in (path / "log", path):
        os.utime(p, ns=(then, then))
    return str(path)


def _spy(monkeypatch, name):
    calls = []
    real = getattr(os, name)

    def spy(path, *args, **kwargs):
        calls.append(os.fspath(path))
        return real(path, *args, **kwargs)

    monkeypatch.setattr(os, name, spy)
    return calls


def _metrics(record):
    return os.path.join(record, "metrics")


@pytest.mark.parametrize("identity", [False, True])
def test_a_scan_opens_no_missing_folder(record, monkeypatch, identity):
    scans = _spy(monkeypatch, "scandir")

    files, _ = listing.scan_dir(record, identity=identity)

    assert set(files) == {"metadata.yml", "log/w.jsonl"}
    assert _metrics(record) not in scans


def test_a_settled_record_stats_no_missing_folder(record, monkeypatch):
    _, known = listing.scan_dir(record)
    stats = _spy(monkeypatch, "stat")

    files, again = listing.scan_dir(record, known)

    assert set(files) == {"metadata.yml", "log/w.jsonl"}
    assert again == known
    assert _metrics(record) not in stats


def test_a_folder_created_in_a_settled_record_is_listed(record):
    _, known = listing.scan_dir(record)
    os.mkdir(_metrics(record))
    with open(os.path.join(_metrics(record), "w.vms"), "w") as f:
        f.write("x")

    files, _ = listing.scan_dir(record, known)

    assert "metrics/w.vms" in files
