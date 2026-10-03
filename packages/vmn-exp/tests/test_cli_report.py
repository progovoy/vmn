"""Plan 13 §8.3: ``vmn-exp report`` / ``comment`` / ``comments`` (git-free)."""
import json

import pytest

from vmn_exp.cli.main import vmn_exp_run
from vmn_exp.reports import comments, published, store
from vmn_exp.storage.local import LocalSnapshotStorage


@pytest.fixture
def store_dir(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VMN_EXPERIMENT_DIR", raising=False)
    monkeypatch.delenv("VMN_EXPERIMENT_STORE", raising=False)
    return str(tmp_path / "store")


def _run(*argv):
    code, _ = vmn_exp_run(list(argv))
    return code


def _storage(store_dir):
    return LocalSnapshotStorage(store_dir, area="runs")


def _put_new(store_dir, tmp_path, body="# Sweep summary\n\ntext\n"):
    path = tmp_path / "report.md"
    path.write_text(body)
    assert _run("report", "put", "--new", "-f", str(path), "--dir", store_dir) == 0
    (report,) = store.list_reports(_storage(store_dir))
    return report


def test_put_new_titles_from_heading(store_dir, tmp_path):
    report = _put_new(store_dir, tmp_path)
    assert report["title"] == "Sweep summary" and report["body"].startswith("# Sweep")


def test_put_existing_saves_next_revision(store_dir, tmp_path):
    rid = _put_new(store_dir, tmp_path)["rid"]
    path = tmp_path / "v2.md"
    path.write_text("second")
    assert _run("report", "put", rid, "-f", str(path), "--dir", store_dir) == 0
    got = store.get(_storage(store_dir), rid)
    assert got["rev"] == 2 and got["body"] == "second"


def test_put_needs_rid_or_new(store_dir, tmp_path):
    path = tmp_path / "r.md"
    path.write_text("x")
    assert _run("report", "put", "-f", str(path), "--dir", store_dir) == 1


def test_list_and_show(store_dir, tmp_path, capsys):
    rid = _put_new(store_dir, tmp_path)["rid"]
    capsys.readouterr()
    assert _run("report", "list", "--dir", store_dir) == 0
    out = capsys.readouterr().out
    assert rid in out and "Sweep summary" in out
    assert _run("report", "list", "--json", "--dir", store_dir) == 0
    assert [r["rid"] for r in json.loads(capsys.readouterr().out)] == [rid]
    assert _run("report", "show", rid, "--dir", store_dir) == 0
    assert "text" in capsys.readouterr().out
    assert _run("report", "show", "rmissing", "--dir", store_dir) == 1


def test_export_writes_one_html_file(store_dir, tmp_path, capsys):
    rid = _put_new(store_dir, tmp_path)["rid"]
    out = tmp_path / "report.html"
    assert _run("report", "export", rid, "-o", str(out), "--dir", store_dir) == 0
    html = out.read_text()
    assert "Sweep summary" in html and 'id="vmn-report-data"' in html
    assert "not published" in capsys.readouterr().err


def test_export_published_revision_and_unknowns(store_dir, tmp_path, capsys):
    rid = _put_new(store_dir, tmp_path)["rid"]
    published.publish(_storage(store_dir), rid, 1, {"p1": {"app": "a", "verstrs": [], "media": [], "queries": []}})
    out = tmp_path / "r.html"
    assert _run("report", "export", rid, "--rev", "1", "-o", str(out), "--dir", store_dir) == 0
    assert '"p1"' in out.read_text() and "not published" not in capsys.readouterr().err
    assert _run("report", "export", rid, "--rev", "9", "-o", str(out), "--dir", store_dir) == 1
    assert _run("report", "export", "rmissing", "-o", str(out), "--dir", store_dir) == 1


def test_delete(store_dir, tmp_path):
    rid = _put_new(store_dir, tmp_path)["rid"]
    assert _run("report", "delete", rid, "--dir", store_dir) == 0
    assert store.get(_storage(store_dir), rid) is None


def test_comment_and_comments(store_dir, capsys):
    _storage(store_dir).create_exclusive("myapp", "1.0.0-dev.abc", {"verstr": "1.0.0-dev.abc"}, {})
    assert _run("comment", "myapp", "-v", "1.0.0-dev.abc", "looks good", "--dir", store_dir) == 0
    thread = comments.thread(_storage(store_dir), ("run", "myapp", "1.0.0-dev.abc"))
    assert [c["text"] for c in thread] == ["looks good"]
    capsys.readouterr()
    assert _run("comments", "myapp", "-v", "1.0.0-dev.abc", "--dir", store_dir) == 0
    assert "looks good" in capsys.readouterr().out


def test_comment_unknown_run_refused(store_dir):
    assert _run("comment", "myapp", "-v", "9.9.9-dev.zzz", "x", "--dir", store_dir) == 1
