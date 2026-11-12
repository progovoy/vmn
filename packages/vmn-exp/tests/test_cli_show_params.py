"""Plan 39 B2: ``vmn-exp show`` and ``compare`` print a run's params as
params, not among its metrics. Numeric params are folded into the fold's
``metrics`` map (sorting and charts use it); the text views split them out."""
import argparse

from similar_seed import seed, verstr
from vmn_exp.cli.experiment import experiment_compare, experiment_show
from vmn_exp.cli.views import split_params
from vmn_exp.core.real_io import RealConsole
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.core.real_io import RealClock

APP = "app"


def test_split_params_moves_a_folded_param_out_of_metrics():
    logged, params = split_params({"lr": 0.1, "loss": 0.5}, {"lr": 0.1}, [])
    assert logged == {"loss": 0.5}
    assert params == {"lr": 0.1}


def test_split_params_keeps_a_metric_logged_under_a_param_name():
    logged, params = split_params({"lr": 0.2}, {"lr": 0.1}, ["lr"])
    assert logged == {"lr": 0.2}
    assert params == {"lr": 0.1}


def test_split_params_keeps_non_numeric_params():
    logged, params = split_params({}, {"opt": "adam", "lr": 0.1}, [])
    assert logged == {}
    assert params == {"opt": "adam", "lr": 0.1}


def _storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path / "store"), area="runs")


def _args(*versions):
    return argparse.Namespace(name=APP, version=list(versions), json=False)


def _show(storage, capsys, v):
    assert experiment_show(None, None, storage, _args(v), RealConsole(), clock=RealClock()) == 0
    return capsys.readouterr().out


def _section(out, heading):
    """The indented lines under *heading* (``Params:``) up to the next blank."""
    lines = out.splitlines()
    start = [i for i, line in enumerate(lines) if line.strip() == heading]
    assert start, f"no {heading} in:\n{out}"
    body = []
    for line in lines[start[0] + 1:]:
        if not line.strip():
            break
        body.append(line.strip())
    return body


def test_show_prints_a_param_under_params_not_metrics(tmp_path, capsys):
    storage = _storage(tmp_path)
    v = seed(storage, APP, verstr(1), params={"lr": 0.25}, metrics={"loss": 0.5})
    out = _show(storage, capsys, v)
    assert _section(out, "Params:") == ["lr: 0.25"]
    assert _section(out, "Metrics:") == ["loss: 0.5"]


def test_show_prints_a_string_param(tmp_path, capsys):
    storage = _storage(tmp_path)
    v = seed(storage, APP, verstr(1), params={"opt": "adam"})
    assert _section(_show(storage, capsys, v), "Params:") == ["opt: adam"]


def test_show_omits_the_metrics_heading_when_only_params_exist(tmp_path, capsys):
    storage = _storage(tmp_path)
    v = seed(storage, APP, verstr(1), params={"lr": 0.25})
    out = _show(storage, capsys, v)
    assert "Metrics:" not in out
    assert _section(out, "Params:") == ["lr: 0.25"]


def test_compare_lists_params_in_their_own_table(tmp_path, capsys):
    storage = _storage(tmp_path)
    a = seed(storage, APP, verstr(1), params={"lr": 0.1}, metrics={"loss": 0.5})
    b = seed(storage, APP, verstr(2), params={"lr": 0.2}, metrics={"loss": 0.4})
    assert experiment_compare(None, None, storage, _args(a, b), RealConsole()) == 0
    lines = capsys.readouterr().out.splitlines()
    metric_head = next(i for i, line in enumerate(lines) if line.startswith("metric "))
    param_head = next(i for i, line in enumerate(lines) if line.startswith("param "))
    assert metric_head < param_head
    metric_rows = [line.split()[0] for line in lines[metric_head + 2:param_head] if line.strip()]
    assert metric_rows == ["loss"]
    assert lines[param_head + 2].split() == ["lr", "0.1", "0.2"]
