"""``vmn-exp ui diag`` needs no git checkout: outside one it used to exit
"Not inside a git repository", and inside a big one it sat in vmn's repo
startup before ever reading the dump."""
import json

from vmn_exp.cli.main import main


def test_diag_summarize_runs_outside_a_git_repo(tmp_path, monkeypatch, capsys):
    dump = tmp_path / "dump.json"
    dump.write_text(json.dumps({"pid": 1, "threads": {}, "requests": {}}))
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)

    assert main(["ui", "diag", "--summarize", str(dump)]) == 0
    assert "Not inside a git repository" not in capsys.readouterr().err


def test_diag_skips_the_repo_startup_inside_a_checkout(tmp_path, monkeypatch):
    from version_stamp.cli import entry

    (tmp_path / ".git").mkdir()
    dump = tmp_path / "dump.json"
    dump.write_text(json.dumps({"pid": 1}))
    monkeypatch.chdir(tmp_path)

    def no_startup():
        raise AssertionError("vmn's repo startup ran")

    monkeypatch.setattr(entry, "resolve_root_path", no_startup)

    assert main(["ui", "diag", "--summarize", str(dump)]) == 0
