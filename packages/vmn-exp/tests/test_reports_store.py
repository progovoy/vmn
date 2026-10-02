"""Reports store (plan 13 §3.1, §3.3): header + immutable revisions."""
import re
import threading

import pytest
from s3_helpers import mocked_bucket, s3_storage

from vmn_exp.core.record_format import FORMAT_VERSION_KEY
from vmn_exp.reports import log as rlog
from vmn_exp.reports import store as rstore
from vmn_exp.storage.areas import REPORTS
from vmn_exp.storage.local import LocalSnapshotStorage


@pytest.fixture
def storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "store"), "runs")


@pytest.fixture
def s3(monkeypatch):
    with mocked_bucket(monkeypatch):
        yield s3_storage()


def test_create_claims_header_and_v1(storage, tmp_path):
    rid = rstore.create(storage, "My report", "# hi")
    assert re.fullmatch(r"r[a-z2-7]{12}", rid)
    reports = storage.in_area(REPORTS)
    header = reports.load_metadata(rid, "header")
    assert header["type"] == "report_header" and header[FORMAT_VERSION_KEY] == 1
    v1 = reports.load_metadata(rid, "v1")
    assert v1["type"] == "report_revision" and v1["base"] == 0
    assert v1[FORMAT_VERSION_KEY] == 1
    assert (tmp_path / "store" / "reports" / rid / "v1" / "report.md").read_text() == "# hi"
    report = rstore.get(storage, rid)
    assert report["title"] == "My report"
    assert report["rev"] == 1 and report["body"] == "# hi"
    assert report["author"]["writer"]


def test_save_appends_next_revision(storage):
    rid = rstore.create(storage, "t", "one")
    assert rstore.save(storage, rid, 1, "two", "edit") == 2
    assert rstore.get(storage, rid)["body"] == "two"
    rev = rstore.revision(storage, rid, 2)
    assert rev["base"] == 1 and rev["message"] == "edit" and rev["body"] == "two"
    assert rstore.revision(storage, rid, 1)["body"] == "one"


def test_stale_base_returns_conflict_with_newer_revision(storage):
    rid = rstore.create(storage, "t", "one")
    rstore.save(storage, rid, 1, "two", "a")
    result = rstore.save(storage, rid, 1, "mine", "b")
    assert isinstance(result, rstore.Conflict)
    assert result.rev == 2 and result.body == "two"
    assert result.author["writer"]
    assert rstore.get(storage, rid)["body"] == "two"


def _race(storage, rid, n=8):
    barrier = threading.Barrier(n)
    results = []

    def worker(i):
        barrier.wait()
        results.append(rstore.save(storage, rid, 1, f"body{i}", ""))

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return results


def test_racing_saves_exactly_one_wins_local(storage):
    rid = rstore.create(storage, "t", "one")
    results = _race(storage, rid)
    assert results.count(2) == 1
    losers = [r for r in results if r != 2]
    assert len(losers) == 7
    assert all(isinstance(r, rstore.Conflict) and r.rev == 2 for r in losers)


def test_racing_saves_exactly_one_wins_s3(s3):
    rid = rstore.create(s3, "t", "one")
    results = _race(s3, rid, n=4)
    assert results.count(2) == 1
    assert sum(isinstance(r, rstore.Conflict) for r in results) == 3


def test_header_fold_last_writer_wins():
    entries = [
        {"type": "title", "ts": "2026-01-01T00:00:02", "writer": "a", "pos": 1, "title": "B"},
        {"type": "title", "ts": "2026-01-01T00:00:01", "writer": "b", "pos": 0, "title": "A"},
        {"type": "pinned", "ts": "2026-01-01T00:00:01", "writer": "a", "pos": 0, "pinned": True},
        {"type": "archived", "ts": "2026-01-01T00:00:03", "writer": "a", "pos": 2,
         "archived": True},
        {"type": "published", "ts": "2026-01-01T00:00:03", "writer": "b", "pos": 1, "rev": 1},
        {"type": "published", "ts": "2026-01-01T00:00:03", "writer": "c", "pos": 0, "rev": 2},
    ]
    folded = rlog.fold_header(entries)
    assert folded == {"title": "B", "archived": True, "pinned": True, "published_rev": 2}
    assert rlog.fold_header(list(reversed(entries))) == folded


def test_header_writes_fold(storage):
    rid = rstore.create(storage, "t", "x")
    rlog.set_title(storage, rid, "new")
    rlog.set_archived(storage, rid, True)
    rlog.set_pinned(storage, rid, True)
    rlog.set_published(storage, rid, 1)
    report = rstore.get(storage, rid)
    assert (report["title"], report["archived"], report["pinned"],
            report["published_rev"]) == ("new", True, True, 1)


def test_list_and_delete(storage):
    a = rstore.create(storage, "a", "x")
    b = rstore.create(storage, "b", "y")
    rstore.save(storage, b, 1, "z", "")
    rows = {r["rid"]: r for r in rstore.list_reports(storage)}
    assert set(rows) == {a, b}
    assert rows[b]["rev"] == 2 and rows[b]["title"] == "b"
    rstore.delete(storage, b)
    assert [r["rid"] for r in rstore.list_reports(storage)] == [a]
    assert rstore.get(storage, b) is None
    assert not storage.in_area(REPORTS).list_record_names(b)


def test_list_and_delete_s3(s3):
    rid = rstore.create(s3, "a", "x")
    assert [r["rid"] for r in rstore.list_reports(s3)] == [rid]
    rstore.delete(s3, rid)
    assert rstore.list_reports(s3) == []
