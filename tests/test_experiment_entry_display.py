"""Human-readable rendering of the log entry types the Python SDK appends.

``run.log_params()`` appends ``{"type": "params", ...}`` and an exception
escaping ``start_run()`` appends ``{"type": "error", ...}``. ``exp show`` used
to print those as bare type names, and ``exp diff`` only looked at the params
recorded on the ``create`` entry.
"""
import os

from helpers import _bootstrap, _experiment, _storage, extract_dev_verstr

from version_stamp.core.experiment_log import effective_params


def _append(app_layout, verstr, entry):
    _storage(app_layout).append_log_entry(
        app_layout.app_name, verstr, "sdk", entry
    )


def _params_entry(params, ts="2099-01-01T00:00:00Z"):
    return {"timestamp": ts, "type": "params", "params": params}


def _error_entry(exception, message, ts="2099-01-01T00:00:01Z"):
    return {
        "timestamp": ts,
        "type": "error",
        "exception": exception,
        "message": message,
    }


def _create_experiment(app_layout, capfd, note, marker=None, metrics=None):
    """Create one dirty-tree experiment and return its verstr."""
    if marker is not None:
        path = os.path.join(app_layout.repo_path, "shared.txt")
        with open(path, "w") as f:
            f.write(marker + "\n")

    capfd.readouterr()
    assert (
        _experiment(app_layout.app_name, note=note, metrics=metrics) == 0
    )
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None
    return verstr


def _show(app_layout, capfd, verstr):
    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="show", version=verstr) == 0
    return capfd.readouterr().out


# ---------------------------------------------------------------------------
# exp show
# ---------------------------------------------------------------------------


def test_exp_show_renders_a_params_entry_with_its_values(app_layout, capfd):
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "dirty.txt", "initial")
    with open(os.path.join(app_layout.repo_path, "dirty.txt"), "w") as f:
        f.write("dirty")

    verstr = _create_experiment(app_layout, capfd, "sdk params")
    _append(app_layout, verstr, _params_entry({"lr": 0.25, "optimizer": "adam"}))

    out = _show(app_layout, capfd, verstr)
    assert "params: lr=0.25, optimizer=adam" in out


def test_exp_show_renders_an_error_entry_with_exception_and_message(
    app_layout, capfd
):
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "dirty.txt", "initial")
    with open(os.path.join(app_layout.repo_path, "dirty.txt"), "w") as f:
        f.write("dirty")

    verstr = _create_experiment(app_layout, capfd, "sdk error")
    _append(app_layout, verstr, _error_entry("ValueError", "bad input"))

    out = _show(app_layout, capfd, verstr)
    assert "error: ValueError: bad input" in out


def test_exp_show_keeps_the_existing_entry_lines_unchanged(app_layout, capfd):
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "dirty.txt", "initial")
    with open(os.path.join(app_layout.repo_path, "dirty.txt"), "w") as f:
        f.write("dirty")

    verstr = _create_experiment(
        app_layout, capfd, "the note", metrics=["loss=0.5"]
    )
    assert (
        _experiment(
            app_layout.app_name,
            action="add",
            version=verstr,
            note="a later note",
        )
        == 0
    )

    artifact = os.path.join(app_layout.repo_path, "art.txt")
    with open(artifact, "w") as f:
        f.write("12345")
    assert (
        _experiment(
            app_layout.app_name, action="add", version=verstr, attach=artifact
        )
        == 0
    )

    out = _show(app_layout, capfd, verstr)
    assert "created: the note" in out
    assert "metrics: loss=0.5" in out
    assert "note: a later note" in out
    assert "artifact: " in out and "bytes)" in out


# ---------------------------------------------------------------------------
# params folding (exp diff's delta line)
# ---------------------------------------------------------------------------


def test_create_entry_params_still_read_from_the_create_entry():
    log = [{"type": "create", "params": {"lr": "0.01", "optimizer": "adam"}}]
    assert effective_params(log) == {"lr": "0.01", "optimizer": "adam"}


def test_create_entry_params_folds_a_mid_run_params_entry():
    log = [
        {"type": "create", "params": {"lr": 0.01}},
        _params_entry({"batch_size": 32}),
    ]
    assert effective_params(log) == {"lr": 0.01, "batch_size": 32}


def test_a_params_entry_overrides_a_create_param():
    log = [
        {"type": "create", "params": {"lr": 0.01}},
        _params_entry({"lr": 0.05}, ts="2026-01-01T00:01:00Z"),
    ]
    assert effective_params(log) == {"lr": 0.05}


def test_a_later_params_entry_wins():
    log = [
        _params_entry({"lr": 0.01}, ts="2026-01-01T00:00:00Z"),
        _params_entry({"lr": 0.02}, ts="2026-01-01T00:01:00Z"),
    ]
    assert effective_params(log) == {"lr": 0.02}


def test_params_entries_keep_non_numeric_values_verbatim():
    log = [_params_entry({"optimizer": "adam"})]
    assert effective_params(log) == {"optimizer": "adam"}


# ---------------------------------------------------------------------------
# exp diff
# ---------------------------------------------------------------------------


def _two_experiments(app_layout, capfd):
    app_layout.write_file_commit_and_push("test_repo_0", "shared.txt", "base line")
    v_alpha = _create_experiment(
        app_layout, capfd, "alpha", marker="ALPHA_MARKER_LINE"
    )
    v_beta = _create_experiment(app_layout, capfd, "beta", marker="BETA_MARKER_LINE")
    return v_alpha, v_beta


def _diff(app_layout, capfd, v_alpha, v_beta):
    capfd.readouterr()
    assert (
        _experiment(app_layout.app_name, action="diff", version=[v_alpha, v_beta])
        == 0
    )
    return capfd.readouterr().out


def test_exp_diff_params_line_reflects_a_mid_run_params_entry(app_layout, capfd):
    _bootstrap(app_layout)
    v_alpha, v_beta = _two_experiments(app_layout, capfd)

    _append(app_layout, v_alpha, _params_entry({"optimizer": "sgd"}))
    _append(app_layout, v_beta, _params_entry({"optimizer": "adam"}))

    out = _diff(app_layout, capfd, v_alpha, v_beta)
    assert "params: optimizer sgd -> adam" in out


def test_exp_diff_params_line_prefers_a_params_entry_over_create(app_layout, capfd):
    _bootstrap(app_layout)
    v_alpha, v_beta = _two_experiments(app_layout, capfd)

    storage = _storage(app_layout)
    for verstr, lr in ((v_alpha, 0.1), (v_beta, 0.1)):
        storage.append_log_entry(
            app_layout.app_name,
            verstr,
            "create_params",
            {"timestamp": "2020-01-01T00:00:00Z", "type": "create", "params": {"lr": lr}},
        )
    _append(app_layout, v_beta, _params_entry({"lr": 0.9}))

    out = _diff(app_layout, capfd, v_alpha, v_beta)
    assert "params: lr 0.1 -> 0.9" in out
