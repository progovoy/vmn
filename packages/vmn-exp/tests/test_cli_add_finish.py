"""``vmn-exp add <app> -v <ref> --finish <code> [--error] [--end-reason] [--force]``:
the CLI's ``manage.finish_run`` (plan 28 API3)."""
from exp_helpers import _bootstrap, _exp, _storage

from vmn_exp.core.status import load_run_state, status_fields
from vmn_exp.sdk import create_run, start_run


def _waiting_run(app_layout):
    _bootstrap(app_layout)
    return create_run(app_layout.app_name, capture_env=False)


def _state(app_layout, verstr):
    return load_run_state(_storage(app_layout), app_layout.app_name, verstr)


def _add(app_layout, verstr, *extra):
    return _exp(app_layout.app_name, action="add", version=verstr, extra_args=list(extra))


def test_add_finish_records_the_final_state(app_layout):
    verstr = _waiting_run(app_layout)

    err = _add(app_layout, verstr, "--finish", "2", "--error", "pod lost",
               "--end-reason", "closed", "--note", "closed at study end")

    assert err == 0
    state = _state(app_layout, verstr)
    assert (state["state"], state["exit_code"], state["end_reason"]) == (
        "finished", 2, "closed")
    assert status_fields(state)["error_summary"] == "pod lost"
    log = _storage(app_layout).load_merged_log(app_layout.app_name, verstr)
    assert [e["text"] for e in log if e["type"] == "note"] == ["closed at study end"]


def test_add_finish_refuses_a_finished_run_without_force(app_layout):
    verstr = _waiting_run(app_layout)
    assert _add(app_layout, verstr, "--finish", "0") == 0

    assert _add(app_layout, verstr, "--finish", "1") == 1
    assert _state(app_layout, verstr)["exit_code"] == 0

    assert _add(app_layout, verstr, "--finish", "1", "--force") == 0
    assert _state(app_layout, verstr)["exit_code"] == 1


def test_add_error_needs_finish(app_layout):
    verstr = _waiting_run(app_layout)
    assert _add(app_layout, verstr, "--error", "pod lost") == 1
    assert _state(app_layout, verstr) is None


def test_add_finish_force_live_never_refinishes(app_layout):
    verstr = _waiting_run(app_layout)
    assert _add(app_layout, verstr, "--finish", "0") == 0

    assert _add(app_layout, verstr, "--finish", "1", "--force-live") == 1
    assert _state(app_layout, verstr)["exit_code"] == 0


def test_add_finish_force_live_finishes_a_live_run(app_layout):
    _bootstrap(app_layout)
    run = start_run(app_layout.app_name, capture_env=False)
    try:
        assert _add(app_layout, run.id, "--finish", "143", "--force-live") == 0
        assert _state(app_layout, run.id)["exit_code"] == 143
    finally:
        run.finish()
