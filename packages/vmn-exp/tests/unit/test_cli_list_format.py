"""``vmn-exp list`` row text: pure formatting, strings and dicts in."""
from vmn_exp.cli.experiment import _format_list_row, _status_token
from vmn_exp.core.metric_summary import SchemaPolicies

TS = "2026-01-01T00:00:00Z"


def _row(metrics, **meta):
    return {"idx": 3, "meta": dict({"verstr": "v3", "timestamp": TS}, **meta),
            "metrics": metrics}


def test_format_list_row_columns_and_missing_values():
    row = _row({"loss": 0.5, "acc": 0.9}, name="baseline", note="first", archived=True)
    text = _format_list_row(row, {"status": "succeeded"}, ["acc", "loss", "f1"],
                            SchemaPolicies({}), 1, "^[1]")
    assert text.startswith("  [3] v3 'baseline' [archived] ^[1]  succeeded  (")
    assert text.endswith("acc=0.9  loss=0.5 - first")
    assert "f1=" not in text


def test_format_list_row_marks_a_metric_whose_steps_went_back():
    row = _row({"loss": 0.5}, step_restarts={"loss": 1})
    text = _format_list_row(row, {"status": "running"}, ["loss"], SchemaPolicies({}), 0, "")
    assert text.endswith("loss=0.5 (steps went back)")


def test_status_token_and_lost_text():
    assert _status_token({"status": "running"}) == "running"
    assert _status_token({"status": "succeeded", "tree_status": "failed"}) == "succeeded/failed"
    assert _status_token({"status": "running", "tree_status": "running", "lost_below": 2}) == (
        "running · 2 lost")
    sweep = {"status": "running", "tree_status": "created", "sweep_trials": 16,
             "sweep_planned": 20}
    assert _status_token(sweep) == "running/created (16/20 incomplete)"
