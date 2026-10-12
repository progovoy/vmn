"""`vmn-exp ui` with an explicit source (--repo, --store, --config) serves from
any directory; only a bare `vmn-exp ui` needs the enclosing git checkout."""
import pytest
from vmn_exp.cli.main import vmn_exp_run


@pytest.fixture
def served(monkeypatch, tmp_path):
    """Record handle_ui calls instead of starting a server, from a non-git cwd."""
    calls = []
    import vmn_exp.ui.cli as ui_cli

    monkeypatch.setattr(ui_cli, "handle_ui", lambda args: calls.append(args) or 0)
    outside = tmp_path / "not_a_repo"
    outside.mkdir()
    monkeypatch.chdir(outside)
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    return calls, tmp_path


@pytest.mark.parametrize("source", [
    lambda tmp: ["--repo", str(tmp / "some_repo")],
    lambda tmp: ["--store", f"file://{tmp / 'store'}"],
    lambda tmp: ["--config", str(tmp / "server.yml")],
], ids=["repo", "store", "config"])
def test_an_explicit_source_serves_outside_a_git_checkout(served, source):
    calls, tmp = served
    code, _ = vmn_exp_run(["ui", "--no-browser", *source(tmp)])
    assert code == 0
    assert len(calls) == 1


def test_a_bare_ui_outside_a_git_checkout_still_asks_for_one(served, capfd):
    calls, _ = served
    code, _ = vmn_exp_run(["ui", "--no-browser"])
    assert code == 1
    assert calls == []
    out = capfd.readouterr()
    assert "Not inside a git repository" in out.err + out.out
