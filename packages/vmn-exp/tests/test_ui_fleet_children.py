"""The fleet table's children (plan 20 B6): each child carries its label
(``idx``/``name``), its ``params`` and ``metrics`` from the index row, and in
run detail how far it got (``last_step``: ``{step, of}``)."""
import pytest
from run_code_seed import client, finished_state, metrics, run_url, seed_run
from vmn_exp.core.tree import fleet_summary

OUTER = "0.0.1-dev.r1"
A, B = "0.0.1-dev.r2", "0.0.1-dev.r3"


def _params(values):
    return {"type": "params", "params": values}


def test_children_carry_their_row_label_params_and_metrics():
    rows = {"c1": {"idx": 4, "name": "lr-high", "params": {"lr": 0.1}, "metrics": {"loss": 0.3}}}
    fleet = fleet_summary(
        "p", {"p": ["c1", "c2"]}, read_state=lambda v: None, read_child_row=rows.get,
    )
    c1, c2 = fleet["children"]
    assert (c1["idx"], c1["name"], c1["params"], c1["metrics"]) == (4, "lr-high", {"lr": 0.1}, {"loss": 0.3})
    assert (c2["idx"], c2["name"], c2["params"], c2["metrics"]) == (None, None, {}, {})


def _seed(app_layout):
    seed_run(app_layout, OUTER, 1, finished_state(0))
    seed_run(app_layout, A, 2, finished_state(0), parent=OUTER, name="a",
             entries=[_params({"epochs": 10, "lr": 0.1}), metrics({"loss": 0.5}, step=3)])
    seed_run(app_layout, B, 3, finished_state(0), parent=OUTER,
             entries=[_params({"lr": 0.2})])


def _children(app_layout):
    pytest.importorskip("fastapi")
    resp = client(app_layout).get(run_url(app_layout, OUTER))
    assert resp.status_code == 200, resp.text
    return {c["verstr"]: c for c in resp.json()["status"]["fleet"]["children"]}


def test_detail_children_carry_their_last_step_of_the_planned_total(app_layout):
    _seed(app_layout)
    children = _children(app_layout)
    assert children[A]["last_step"] == {"step": 3, "of": 10}
    assert children[A]["name"] == "a"
    assert isinstance(children[A]["idx"], int)
    assert children[A]["params"] == {"epochs": 10, "lr": 0.1}


def test_a_child_that_logged_no_step_has_no_last_step(app_layout):
    _seed(app_layout)
    assert _children(app_layout)[B]["last_step"] is None
