"""Plan 39 B6: ``vmn-exp compare --json`` prints the comparison as strict JSON
(``compare_payload``): the runs' logged metrics and the policy behind each,
the metric keys in table order, the params apart and any policy conflicts."""
import argparse
import json
import re

import pytest

from similar_seed import seed, verstr
from vmn_exp.cli.compare_view import compare_payload
from vmn_exp.cli.experiment import experiment_compare
from vmn_exp.cli.main import vmn_exp_run
from vmn_exp.storage.local import LocalSnapshotStorage

APP = "app"


def _bundle(v, metrics=(), params=None, summary=None):
    """A light compare bundle ``(meta, None, log)``; *metrics* is
    ``[(name, [values per step])]``, *summary* ``(name, policy)``."""
    log = [{"type": "create", "params": params or {}}]
    if summary:
        log.append({"type": "define_metric", "name": summary[0], "summary": summary[1]})
    for name, values in metrics:
        log += [{"type": "metrics", "values": {name: x}, "step": i} for i, x in enumerate(values)]
    return {"verstr": v}, None, log


def test_compare_payload_orders_schema_metrics_first():
    runs = [_bundle("a", [("acc", [0.5]), ("loss", [0.3])]), _bundle("b", [("zeta", [1])])]
    payload = compare_payload(runs, {"zeta": {"goal": "max"}, "unlogged": {}})
    assert payload["metrics"] == ["zeta", "acc", "loss"]
    assert [r["verstr"] for r in payload["runs"]] == ["a", "b"]
    assert payload["runs"][0]["metrics"] == {"acc": 0.5, "loss": 0.3}


def test_compare_payload_names_policy_conflicts():
    own = _bundle("a", [("loss", [1.0, 0.2, 0.9])], summary=("loss", "min"))
    plain = _bundle("b", [("loss", [1.0, 0.2, 0.9])])
    payload = compare_payload([own, plain], {})
    assert [r["metric_policy"] for r in payload["runs"]] == [{"loss": "min"}, {}]
    assert [r["metrics"]["loss"] for r in payload["runs"]] == [0.2, 0.9]
    assert payload["conflicts"] == {"loss": "summaries differ: min vs last"}


def test_compare_payload_separates_params():
    runs = [_bundle("a", [("loss", [0.5])], params={"lr": 0.1, "opt": "adam"}),
            _bundle("b", [("loss", [0.4])], params={"lr": 0.2})]
    payload = compare_payload(runs, {})
    assert payload["metrics"] == ["loss"]
    assert payload["params"] == ["lr", "opt"]
    assert payload["runs"][0]["metrics"] == {"loss": 0.5}
    assert payload["runs"][0]["params"] == {"lr": 0.1, "opt": "adam"}
    assert payload["conflicts"] == {}


def test_compare_json_prints_strict_json_and_no_table(tmp_path, capsys):
    storage = LocalSnapshotStorage(str(tmp_path / "store"), area="runs")
    a = seed(storage, APP, verstr(1), params={"lr": 0.1}, metrics={"loss": 0.5})
    b = seed(storage, APP, verstr(2), params={"lr": 0.2}, metrics={"loss": float("nan")})
    args = argparse.Namespace(name=APP, version=[a, b], json=True)
    assert experiment_compare(None, None, storage, args) == 0
    out = capsys.readouterr().out
    payload = json.loads(out, parse_constant=lambda c: (_ for _ in ()).throw(ValueError(c)))
    assert [r["verstr"] for r in payload["runs"]] == [a, b]
    assert [r["metrics"]["loss"] for r in payload["runs"]] == [0.5, None]
    assert payload["params"] == ["lr"]
    assert "vmn-exp diff" not in out


def test_json_help_names_every_action_that_honours_it(capsys):
    with pytest.raises(SystemExit):
        vmn_exp_run(["compare", "--help"])
    out = re.sub(r"\s+", " ", capsys.readouterr().out)
    (owners,) = re.findall(r"--json ([a-z, ]+): print machine-", out)
    assert set(owners.split(", ")) == {
        "compare", "importance", "lineage", "list", "push", "rerun", "show", "similar"}
