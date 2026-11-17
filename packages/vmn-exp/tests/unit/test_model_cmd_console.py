"""``vmn-exp model`` writes through the Console port (plan 44 G16)."""
from types import SimpleNamespace

from fake_checkout import FakeCheckout
from fakes.clock import FakeClock
from fakes.console import FakeConsole
from fakes.env import FakeEnv
from vmn_exp.cli.model_cmd import model_run_without_repo
from vmn_exp.core.ports import IO
from vmn_exp.registry.store import ensure_model, register_version
from vmn_exp.storage.local import LocalSnapshotStorage

RUN = {"app": "app", "verstr": "0.0.1-dev.aaaaaaa.0000001"}


def _registered(tmp_path, *names):
    storage = LocalSnapshotStorage(str(tmp_path), area="runs")
    for name in names:
        ensure_model(storage, name)
        register_version(storage, name, RUN)


def _model(tmp_path, action, **kw):
    console = FakeConsole()
    io = IO(clock=FakeClock(), env=FakeEnv(), processes=None, random=None, host=None, console=console)
    args = SimpleNamespace(action=action, dir=str(tmp_path), store=None, bucket=None,
                           prefix=None, endpoint_url=None, kind=None, json=False, **kw)
    return model_run_without_repo(args, io, FakeCheckout(root=None)), console


def test_model_list_lines(tmp_path, capsys):
    _registered(tmp_path, "clf", "reg")
    code, console = _model(tmp_path, "list")
    assert code == 0
    assert sorted(console.stdout.splitlines()) == ["clf", "reg"]
    assert capsys.readouterr() == ("", "")


def test_model_show_and_resolve_lines(tmp_path):
    _registered(tmp_path, "clf")
    code, console = _model(tmp_path, "show", model_name="clf")
    assert code == 0
    assert console.stdout.splitlines()[:2] == ["Model: clf", "  Kind: model"]
    code, console = _model(tmp_path, "resolve", model_name="clf@1")
    assert code == 0
    assert console.stdout.splitlines()[0] == "model:    clf"

