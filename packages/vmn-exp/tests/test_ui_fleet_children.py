"""The fleet summary's children (plan 20 B6): each child carries its label
(``idx``/``name``), its ``params`` and ``metrics`` from the index row. Run
detail no longer serves them (plan 23 S3: a job's runs are its Runs tab)."""
from vmn_exp.core.tree import fleet_summary


def test_children_carry_their_row_label_params_and_metrics():
    rows = {"c1": {"idx": 4, "name": "lr-high", "params": {"lr": 0.1}, "metrics": {"loss": 0.3}}}
    fleet = fleet_summary(
        "p", {"p": ["c1", "c2"]}, read_state=lambda v: None, read_child_row=rows.get,
    )
    c1, c2 = fleet["children"]
    assert (c1["idx"], c1["name"], c1["params"], c1["metrics"]) == (4, "lr-high", {"lr": 0.1}, {"loss": 0.3})
    assert (c2["idx"], c2["name"], c2["params"], c2["metrics"]) == (None, None, {}, {})
