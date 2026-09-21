"""A mid-run ``params`` log entry must count as params, like ``create``'s do.

``run.log_params()`` appends ``{"type": "params", "params": {...}}`` at any
point during a run; the read side has to honor it the same way it honors the
params recorded at create time.
"""
import json
import os

from helpers import _bootstrap, _experiment, extract_dev_verstr

from version_stamp.cli.experiment import _get_latest_metrics


def _append_log_entry(app_layout, verstr, entry, writer="sdk"):
    path = os.path.join(
        app_layout.repo_path,
        ".vmn",
        app_layout.app_name,
        "experiments",
        verstr,
        f"log.{writer}.jsonl",
    )
    with open(path, "a") as f:
        f.write(json.dumps(entry) + "\n")


def _params_entry(params, ts="2099-01-01T00:00:00Z"):
    return {"timestamp": ts, "type": "params", "params": params}


# ---------------------------------------------------------------------------
# _get_latest_metrics
# ---------------------------------------------------------------------------


def test_params_entry_is_picked_up():
    log = [_params_entry({"lr": 0.01, "batch_size": 32})]
    assert _get_latest_metrics(log) == {"lr": 0.01, "batch_size": 32}


def test_params_entry_coerces_numbers_and_skips_the_rest():
    log = [_params_entry({"lr": "0.01", "steps": "5", "optimizer": "adam"})]
    assert _get_latest_metrics(log) == {"lr": 0.01, "steps": 5.0}


def test_a_later_params_entry_overrides_an_earlier_one():
    log = [
        _params_entry({"lr": 0.01}, ts="2026-01-01T00:00:00Z"),
        _params_entry({"lr": 0.02}, ts="2026-01-01T00:01:00Z"),
    ]
    assert _get_latest_metrics(log) == {"lr": 0.02}


def test_a_params_entry_overrides_create_params():
    log = [
        {"timestamp": "2026-01-01T00:00:00Z", "type": "create", "params": {"lr": 0.01}},
        _params_entry({"lr": 0.05}, ts="2026-01-01T00:01:00Z"),
    ]
    assert _get_latest_metrics(log) == {"lr": 0.05}


def test_create_params_still_work_on_their_own():
    log = [
        {
            "timestamp": "2026-01-01T00:00:00Z",
            "type": "create",
            "params": {"lr": "0.01", "optimizer": "adam"},
        },
        {
            "timestamp": "2026-01-01T00:01:00Z",
            "type": "metrics",
            "values": {"loss": 0.3},
        },
    ]
    assert _get_latest_metrics(log) == {"lr": 0.01, "loss": 0.3}


# ---------------------------------------------------------------------------
# CLI display
# ---------------------------------------------------------------------------


def _experiment_with_params_entry(app_layout, capfd):
    _bootstrap(app_layout)

    app_layout.write_file_commit_and_push("test_repo_0", "dirty.txt", "initial")
    with open(os.path.join(app_layout.repo_path, "dirty.txt"), "w") as f:
        f.write("dirty")

    capfd.readouterr()
    assert _experiment(app_layout.app_name, note="mid-run params") == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None

    _append_log_entry(app_layout, verstr, _params_entry({"lr": 0.25}))
    return verstr


def test_exp_list_shows_a_mid_run_params_entry(app_layout, capfd):
    verstr = _experiment_with_params_entry(app_layout, capfd)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="list") == 0
    out = capfd.readouterr().out
    assert verstr in out
    assert "lr=0.25" in out


def test_exp_show_shows_a_mid_run_params_entry(app_layout, capfd):
    verstr = _experiment_with_params_entry(app_layout, capfd)

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="show", version=verstr) == 0
    out = capfd.readouterr().out
    assert "lr: 0.25" in out
