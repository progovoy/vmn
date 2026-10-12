"""A failed run's recorded ``error`` reaches its status fields, rows and queries."""
from vmn_exp.core import tree
from vmn_exp.core.query import filter_rows
from vmn_exp.core.status import status_fields

_FAILED = {
    "state": "finished",
    "exit_code": 1,
    "started_at": "2026-10-01T10:00:00Z",
    "finished_at": "2026-10-01T10:01:00Z",
    "error": {
        "type": "torch.cuda.OutOfMemoryError",
        "message": "CUDA out of memory\nTried to allocate 2 GiB",
        "traceback": "Traceback (most recent call last):\n...",
        "source": "exception",
    },
}


def test_status_fields_carry_the_error_summary():
    fields = status_fields(_FAILED)
    assert fields["error_summary"] == "torch.cuda.OutOfMemoryError: CUDA out of memory"


def test_status_fields_carry_the_signal():
    fields = status_fields(dict(_FAILED, exit_code=137, signal="SIGKILL"))
    assert fields["signal"] == "SIGKILL"


def test_status_fields_without_an_error():
    fields = status_fields({"state": "finished", "exit_code": 0})
    assert fields["error_summary"] is None
    assert fields["signal"] is None
    assert status_fields(None)["error_summary"] is None


def test_status_fields_never_carry_the_traceback():
    assert "error" not in status_fields(_FAILED)


def test_annotated_rows_carry_the_error_summary():
    rows = tree.annotate_rows(
        [{"verstr": "0.0.1"}, {"verstr": "0.0.2"}],
        {"0.0.1": _FAILED, "0.0.2": {"state": "finished", "exit_code": 0}},
    )
    by = {r["verstr"]: r for r in rows}
    assert by["0.0.1"]["error_summary"].startswith("torch.cuda.OutOfMemoryError")
    assert by["0.0.2"]["error_summary"] is None


def _rows():
    return tree.annotate_rows(
        [{"verstr": "0.0.1"}, {"verstr": "0.0.2"}, {"verstr": "0.0.3"}],
        {
            "0.0.1": _FAILED,
            "0.0.2": {"state": "finished", "exit_code": 0},
            "0.0.3": dict(_FAILED, error=None, exit_code=143, signal="SIGTERM",
                          end_reason="stopped"),
        },
    )


def _verstrs(text):
    return [r["verstr"] for r in filter_rows(_rows(), text)]


def test_error_summary_is_queryable():
    assert _verstrs('error_summary ~ "cuda"') == ["0.0.1"]
    assert _verstrs("error_summary = null") == ["0.0.2", "0.0.3"]


def test_signal_and_end_reason_are_queryable():
    assert _verstrs('signal = "SIGTERM"') == ["0.0.3"]
    assert _verstrs('end_reason = "stopped"') == ["0.0.3"]


def test_status_fields_of_the_slim_index_state_carry_the_summary():
    from vmn_exp.core.run_error import slim_run_state
    fields = status_fields(slim_run_state(_FAILED))
    assert fields["error_summary"] == "torch.cuda.OutOfMemoryError: CUDA out of memory"


def test_the_index_keeps_a_slim_run_state():
    import yaml
    from vmn_exp.core.index_record import new_record, _update_run_state

    class Storage:
        def load_file(self, app_name, verstr, name):
            return yaml.dump(_FAILED)

    record = new_record()
    _update_run_state(Storage(), "app", "1.0.0-dev.a", {"run_state.yml": (1, 2)}, record)
    assert "error" not in record["run_state"]
    assert record["run_state"]["error_summary"].startswith("torch.cuda.OutOfMemoryError")
