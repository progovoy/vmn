"""Plan 13 §8.2: the per-workspace report index and comment counts."""
import pytest

from vmn_exp.core.index_store import SqliteStore
from vmn_exp.core.query import filter_rows
from vmn_exp.reports import comments
from vmn_exp.reports import store as rstore
from vmn_exp.reports.index import ReportIndex
from vmn_exp.reports.panels import panel_refs
from vmn_exp.storage.journal import journaled
from vmn_exp.storage.local import LocalSnapshotStorage

PINNED = """# A
```vmn-panel
v: 1
id: p1
type: curves
app: trainer
runs: {verstrs: ["0.1.0-dev.a", "0.1.0-dev.b"]}
```
```vmn-panel
v: 1
id: p2
type: table
app: other/svc
runs: {query: 'status = succeeded'}
```
```python
app: ignored
```
"""


class Clock:
    def __init__(self):
        self.now = 1_800_000_000.0

    def __call__(self):
        return self.now


@pytest.fixture
def clock():
    return Clock()


@pytest.fixture
def storage(tmp_path, clock):
    return journaled(LocalSnapshotStorage(str(tmp_path / "store"), "runs"), clock=clock)


def _index(storage, clock, cache=None, full_sweep_sec=3600):
    return ReportIndex(storage, cache=cache, clock=clock, full_sweep_sec=full_sweep_sec)


def test_panel_refs_pinned_and_query():
    assert panel_refs(PINNED) == [("trainer", ["0.1.0-dev.a", "0.1.0-dev.b"]),
                                  ("other/svc", None)]


def test_panel_refs_skips_bad_yaml_and_missing_app():
    body = "```vmn-panel\n: [\n```\n```vmn-panel\nid: x\n```\n"
    assert panel_refs(body) == []


def test_index_lists_reports_and_reverse_map(storage, clock):
    rid = rstore.create(storage, "T", PINNED)
    index = _index(storage, clock)
    index.refresh()
    [row] = index.reports()
    assert row["rid"] == rid and row["title"] == "T" and row["rev"] == 1 and "body" not in row
    assert index.using("trainer", "0.1.0-dev.a") == [rid]
    assert index.using("trainer", "0.1.0-dev.zzz") == []
    assert index.using("trainer") == [rid]
    assert index.using("other/svc", "anything") == [rid]
    assert index.using("nobody") == []


def test_journal_entries_refresh_without_full_sweep(storage, clock, monkeypatch):
    index = _index(storage, clock)
    index.refresh()
    monkeypatch.setattr(rstore, "list_reports", lambda s: pytest.fail("full listing"))
    clock.now += 2
    rid = rstore.create(storage, "New", PINNED)
    clock.now += 1
    index.refresh()
    assert [r["rid"] for r in index.reports()] == [rid]
    rstore.save(storage, rid, 1, "no panels")
    clock.now += 1
    index.refresh()
    assert index.reports()[0]["rev"] == 2 and index.using("trainer") == []
    rstore.delete(storage, rid)
    clock.now += 1
    index.refresh()
    assert index.reports() == []


def test_comment_counts_from_journal(storage, clock):
    index = _index(storage, clock)
    index.refresh()
    target = ("run", "trainer", "0.1.0-dev.a")
    first = comments.add(storage, target, "one")
    comments.add(storage, target, "reply", reply_to=first)
    second = comments.add(storage, target, "two")
    comments.resolve(storage, target, second)
    gone = comments.add(storage, target, "oops")
    comments.delete(storage, target, gone)
    clock.now += 1
    index.refresh()
    assert index.comment_counts("trainer") == {"0.1.0-dev.a": {"total": 3, "unresolved": 1}}
    assert index.comment_counts("other") == {}


def test_full_build_counts_existing_threads(storage, clock):
    comments.add(storage, ("run", "root/svc", "0.0.1"), "x")
    index = _index(storage, clock)
    index.refresh()
    assert index.comment_counts("root/svc") == {"0.0.1": {"total": 1, "unresolved": 1}}


def test_generation_moves_on_change_only(storage, clock):
    index = _index(storage, clock)
    index.refresh()
    before = index.generation
    clock.now += 1
    index.refresh()
    assert index.generation == before
    comments.add(storage, ("run", "trainer", "0.0.1"), "x")
    clock.now += 1
    index.refresh()
    assert index.generation > before


def test_state_persists_in_cache_kv(storage, clock, tmp_path, monkeypatch):
    cache = SqliteStore(str(tmp_path / "cache.sqlite"))
    rid = rstore.create(storage, "T", PINNED)
    _index(storage, clock, cache).refresh()
    monkeypatch.setattr(rstore, "list_reports", lambda s: pytest.fail("full listing"))
    again = _index(storage, clock, cache)
    clock.now += 1
    again.refresh()
    assert [r["rid"] for r in again.reports()] == [rid]
    assert again.using("trainer", "0.1.0-dev.b") == [rid]


def test_storage_without_journal_rebuilds_each_sweep(tmp_path, clock):
    plain = LocalSnapshotStorage(str(tmp_path / "plain"), "runs")
    index = _index(plain, clock, full_sweep_sec=0)
    index.refresh()
    rid = rstore.create(plain, "T", "")
    index.refresh()
    assert [r["rid"] for r in index.reports()] == [rid]


def test_comments_unresolved_query():
    rows = [{"verstr": "a", "comments": {"total": 2, "unresolved": 1}},
            {"verstr": "b", "comments": {"total": 1, "unresolved": 0}},
            {"verstr": "c"}]
    assert [r["verstr"] for r in filter_rows(rows, "comments.unresolved > 0")] == ["a"]
    extra = {"comments": lambda v: {"total": 1, "unresolved": 1} if v == "c" else None}
    lean = [{"verstr": "b"}, {"verstr": "c"}]
    assert [r["verstr"] for r in filter_rows(lean, "comments.total >= 1", extra=extra)] == ["c"]
