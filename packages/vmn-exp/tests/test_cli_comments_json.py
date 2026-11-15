"""Plan 39 B6: ``vmn-exp comments --json`` prints a run's thread as stored
(a deleted comment keeps its flag and loses its text); ``vmn-exp comment
--json`` prints ``{"id": ...}`` of the new comment."""
import argparse
import json

from similar_seed import seed, verstr
from vmn_exp.cli.comment import comment_run, comments_run
from vmn_exp.reports import comments
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.core.real_io import RealRandom
from vmn_exp.core.real_io import real_io

APP = "app"
AUTHOR = {"name": "ann"}


def _seeded(tmp_path):
    storage = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    return storage, seed(storage, APP, verstr(1))


def _args(v, **kw):
    return argparse.Namespace(name=APP, version_ref=v, json=True, **kw)


def _json_out(capsys):
    return json.loads(capsys.readouterr().out)


def test_comments_json_lists_the_thread(tmp_path, capsys):
    storage, v = _seeded(tmp_path)
    target = ("run", APP, v)
    first = comments.add(storage, target, "hello", author=AUTHOR, random=RealRandom(), env=real_io().env, host=real_io().host)
    second = comments.add(storage, target, "re", reply_to=first, author=AUTHOR, random=RealRandom(), env=real_io().env, host=real_io().host)
    assert comments_run(storage, _args(v)) == 0
    thread = _json_out(capsys)
    assert [(c["id"], c["text"], c["reply_to"]) for c in thread] == [
        (first, "hello", None), (second, "re", first)]
    assert thread[0]["author"] == AUTHOR
    assert thread[0]["deleted"] is False and thread[0]["ts"]


def test_comment_json_prints_the_new_id(tmp_path, capsys):
    storage, v = _seeded(tmp_path)
    assert comment_run(storage, _args(v, text="hi"), random=RealRandom(), env=real_io().env, host=real_io().host) == 0
    out = _json_out(capsys)
    assert list(out) == ["id"]
    assert [c["id"] for c in comments.thread(storage, ("run", APP, v))] == [out["id"]]


def test_a_deleted_comment_keeps_its_flag_and_no_text(tmp_path, capsys):
    storage, v = _seeded(tmp_path)
    target = ("run", APP, v)
    cid = comments.add(storage, target, "oops", author=AUTHOR, random=RealRandom(), env=real_io().env, host=real_io().host)
    comments.delete(storage, target, cid, env=real_io().env, host=real_io().host)
    assert comments_run(storage, _args(v)) == 0
    (c,) = _json_out(capsys)
    assert c["id"] == cid and c["deleted"] is True
    assert "text" not in c
