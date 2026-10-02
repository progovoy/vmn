"""Plan 13 §3.2 / phase 1b: comment threads on runs and reports."""
import threading

from exp_helpers import _bootstrap, _exp, _storage
from vmn_exp.reports import comments
from vmn_exp.storage import areas
from vmn_exp.storage.registry import open_store

VERSTR = "1.0.0-dev.abc1234"
RUN = ("run", "root/svc", VERSTR)
REPORT = ("report", "r_abc")


def _store(tmp_path):
    return open_store(f"file://{tmp_path}", area=areas.RUNS)


def test_run_thread_lives_under_comments_app_key_verstr(tmp_path):
    store = _store(tmp_path)
    comments.add(store, RUN, "hello")
    assert (tmp_path / "comments" / "root-svc" / VERSTR / "metadata.yml").is_file()
    meta = store.in_area(areas.COMMENTS).load_metadata("root/svc", VERSTR)
    assert meta["type"] == "comment_thread"
    assert meta["target"] == {"kind": "run", "app": "root/svc", "verstr": VERSTR}


def test_report_thread_lives_under_reports_rid_comments(tmp_path):
    store = _store(tmp_path)
    comments.add(store, REPORT, "hi")
    assert (tmp_path / "reports" / "r_abc" / "comments" / "metadata.yml").is_file()
    assert [c["text"] for c in comments.thread(store, REPORT)] == ["hi"]


def test_claim_race_keeps_every_comment(tmp_path):
    store = _store(tmp_path)
    barrier = threading.Barrier(4)

    def post(i):
        barrier.wait()
        comments.add(_store(tmp_path), RUN, f"c{i}", author={"id": f"w{i}"})

    threads = [threading.Thread(target=post, args=(i,)) for i in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    texts = sorted(c["text"] for c in comments.thread(store, RUN))
    assert texts == ["c0", "c1", "c2", "c3"]


def test_edit_resolve_delete_fold(tmp_path):
    store = _store(tmp_path)
    first = comments.add(store, RUN, "first", anchor={"metric": "loss", "step": 3})
    second = comments.add(store, RUN, "second")
    comments.edit(store, RUN, first, "first, edited")
    comments.resolve(store, RUN, second)
    folded = {c["id"]: c for c in comments.thread(store, RUN)}
    assert folded[first]["text"] == "first, edited"
    assert folded[first]["anchor"] == {"metric": "loss", "step": 3}
    assert folded[first]["resolved"] is False
    assert folded[second]["resolved"] is True
    comments.resolve(store, RUN, second, resolved=False)
    comments.delete(store, RUN, first)
    folded = {c["id"]: c for c in comments.thread(store, RUN)}
    assert folded[second]["resolved"] is False
    assert folded[first]["deleted"] is True
    assert folded[first]["text"] is None


def test_tombstone_keeps_replies(tmp_path):
    store = _store(tmp_path)
    parent = comments.add(store, RUN, "parent")
    reply = comments.add(store, RUN, "reply", reply_to=parent)
    comments.delete(store, RUN, parent)
    folded = comments.thread(store, RUN)
    assert [c["id"] for c in folded] == [parent, reply]
    assert folded[0]["deleted"] is True
    assert folded[1]["reply_to"] == parent and folded[1]["text"] == "reply"


def test_last_writer_wins_on_ts_writer_pos():
    base = {"type": "comment", "id": "c1", "ts": "1", "writer": "a", "pos": 0, "text": "x"}
    entries = [
        base,
        {"type": "comment_edit", "id": "c1", "ts": "3", "writer": "a", "pos": 2, "text": "late"},
        {"type": "comment_edit", "id": "c1", "ts": "2", "writer": "b", "pos": 0, "text": "early"},
    ]
    assert comments.fold(entries)[0]["text"] == "late"
    tie = [
        base,
        {"type": "comment_edit", "id": "c1", "ts": "2", "writer": "b", "pos": 0, "text": "b"},
        {"type": "comment_edit", "id": "c1", "ts": "2", "writer": "a", "pos": 1, "text": "a"},
    ]
    assert comments.fold(tie)[0]["text"] == "b"


def test_author_defaults_to_actor_identity(tmp_path, monkeypatch):
    monkeypatch.setenv("VMN_WRITER_ID", "host-x")
    store = _store(tmp_path)
    comments.add(store, RUN, "a")
    comments.add(store, RUN, "b", author={"id": "p_1", "name": "Dana"})
    first, second = comments.thread(store, RUN)
    assert first["author"]["writer"] == "host-x"
    assert second["author"] == {"id": "p_1", "name": "Dana"}


def test_empty_thread(tmp_path):
    assert comments.thread(_store(tmp_path), RUN) == []


def test_prune_deletes_the_runs_thread(app_layout):
    _bootstrap(app_layout)
    assert _exp(app_layout.app_name) == 0
    storage = _storage(app_layout)
    verstr = storage.list_snapshots(app_layout.app_name)[-1]["verstr"]
    target = ("run", app_layout.app_name, verstr)
    comments.add(storage, target, "note")
    assert comments.thread(storage, target)
    assert _exp(app_layout.app_name, action="prune", version=verstr) == 0
    assert comments.thread(_storage(app_layout), target) == []
