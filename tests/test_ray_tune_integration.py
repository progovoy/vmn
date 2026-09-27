"""Tests for vmn_exp.integrations.ray_tune.

Unit tests 1-4 run without Ray and without Docker: they use container mode
(VMN_SNAPSHOT_METADATA + VMN_EXPERIMENT_DIR) so that start_run works without a
git checkout.  No app_layout fixture means no Docker dependency.

Test 5 requires ray (pytest.importorskip) and is expected to skip in environments
where ray is not installed.
"""
import pytest
import yaml


# ---------------------------------------------------------------------------
# Shared container-mode fixture
# ---------------------------------------------------------------------------

APP_NAME = "test_ray_app"


@pytest.fixture
def container(tmp_path, monkeypatch):
    """Container mode: fake snapshot metadata + local experiment dir.

    Mirrors the pattern from tests/test_fix_sdk_lifecycle.py::container.
    """
    image = tmp_path / "image"
    image.mkdir()
    (image / "vmn_metadata.yml").write_text(
        yaml.safe_dump(
            {
                "verstr": "0.0.1-dev.abc1234.def5678",
                "app_name": APP_NAME,
                "base_version": "0.0.1",
                "base_commit": "abc1234" * 5 + "abcde",
                "branch": "main",
            }
        )
    )
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    monkeypatch.delenv("VMN_EXPERIMENT_ID", raising=False)
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(image / "vmn_metadata.yml"))
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(store))
    return store


# ---------------------------------------------------------------------------
# Test 1: outer + inner run linkage
# ---------------------------------------------------------------------------


def test_outer_and_inner_run_linkage(container):
    """First on_trial_start creates an outer run; each trial is a nested inner run.

    Asserts:
    - recorder._outer_run is not None after the first trial start
    - outer and inner have distinct verstrs
    - inner run's metadata.parent == outer run's verstr
    - a second trial also links to the same outer run
    """
    from version_stamp.cli.snapshot import get_snapshot_storage

    from vmn_exp.integrations.ray_tune import TuneRecorder

    recorder = TuneRecorder(app_name=APP_NAME, experiment_name="my sweep")
    try:
        recorder.on_trial_start("t1", {"lr": 0.01})

        assert recorder._outer_run is not None, "outer run should be created on first trial"
        outer_id = recorder._outer_run.id
        assert "t1" in recorder._trial_runs
        inner = recorder._trial_runs["t1"]
        inner_id = inner.id
        assert inner_id != outer_id, "inner and outer verstrs must differ"

        recorder.on_trial_complete("t1")

        # Second trial: still uses the same outer run
        recorder.on_trial_start("t2", {"lr": 0.1})
        assert recorder._outer_run.id == outer_id, "outer run must stay the same"
        inner2_id = recorder._trial_runs["t2"].id
        assert inner2_id != outer_id
        recorder.on_trial_complete("t2")
    finally:
        recorder.finish()

    storage = get_snapshot_storage(
        "local", vmn_root_path=str(container), subdir="experiments"
    )
    meta, _ = storage.load(APP_NAME, inner_id)
    assert meta.get("parent") == outer_id, (
        f"inner run parent should be outer run id {outer_id!r}, got {meta.get('parent')!r}"
    )

    meta2, _ = storage.load(APP_NAME, inner2_id)
    assert meta2.get("parent") == outer_id, "second inner run must also parent to outer"


# ---------------------------------------------------------------------------
# Test 2: result series with steps
# ---------------------------------------------------------------------------


def test_result_series_logs_metrics_with_step(container):
    """on_trial_result maps numeric values to metrics with training_iteration as step.

    Ray bookkeeping keys (time_this_iter_s, done, etc.) are dropped.
    """
    from version_stamp.cli.snapshot import get_snapshot_storage

    from vmn_exp.integrations.ray_tune import TuneRecorder

    recorder = TuneRecorder(app_name=APP_NAME)
    inner_id = None
    storage_ref = None
    try:
        recorder.on_trial_start("t1", {})
        inner = recorder._trial_runs["t1"]
        inner_id = inner.id
        storage_ref = inner._storage

        recorder.on_trial_result(
            "t1",
            {
                "loss": 0.5,
                "accuracy": 0.9,
                "training_iteration": 3,
                "time_this_iter_s": 1.23,   # bookkeeping — must be dropped
                "time_total_s": 9.99,        # bookkeeping — must be dropped
                "done": False,               # bool — must be dropped
            },
        )
        recorder.on_trial_complete("t1")
    finally:
        recorder.finish()

    log = storage_ref.load_merged_log(APP_NAME, inner_id)
    metric_entries = [e for e in log if e.get("type") == "metrics"]
    assert metric_entries, "expected at least one metrics log entry"

    # Collect all logged (value, step) tuples by key
    all_values = {}
    for entry in metric_entries:
        step = entry.get("step")
        for k, v in (entry.get("values") or {}).items():
            all_values[k] = (v, step)

    assert "loss" in all_values, "loss should be logged"
    assert all_values["loss"] == (0.5, 3), f"expected (0.5, step=3), got {all_values['loss']}"
    assert "accuracy" in all_values, "accuracy should be logged"
    assert all_values["accuracy"][1] == 3, "accuracy should carry the same step"

    assert "time_this_iter_s" not in all_values, "bookkeeping key must be dropped"
    assert "time_total_s" not in all_values, "bookkeeping key must be dropped"
    assert "done" not in all_values, "bool (non-numeric) key must be dropped"


# ---------------------------------------------------------------------------
# Test 3: config flattening to params
# ---------------------------------------------------------------------------


def test_config_nested_dict_flattened_to_params(container):
    """Nested config dicts are flattened with '.' separator into trial params."""
    from vmn_exp.integrations.ray_tune import TuneRecorder

    config = {
        "lr": 0.01,
        "model": {
            "depth": 3,
            "activation": "relu",
        },
    }

    recorder = TuneRecorder(app_name=APP_NAME)
    inner_id = None
    storage_ref = None
    try:
        recorder.on_trial_start("t1", config)
        inner = recorder._trial_runs["t1"]
        inner_id = inner.id
        storage_ref = inner._storage
        recorder.on_trial_complete("t1")
    finally:
        recorder.finish()

    log = storage_ref.load_merged_log(APP_NAME, inner_id)
    # params come from the 'create' entry (passed via start_run params=)
    create_entry = next((e for e in log if e.get("type") == "create"), None)
    assert create_entry is not None, "expected a create log entry"

    params = create_entry.get("params", {})
    assert params.get("lr") == 0.01, f"expected lr=0.01, got params={params}"
    assert params.get("model.depth") == 3, f"expected model.depth=3, got {params}"
    assert params.get("model.activation") == "relu", f"expected model.activation='relu', got {params}"


# ---------------------------------------------------------------------------
# Test 4: error → failed status
# ---------------------------------------------------------------------------


def test_trial_error_marks_run_failed(container):
    """on_trial_error finishes the inner run with exit_code=1 → failed status."""
    from version_stamp.core.experiment_status import (
        FAILED,
        derive_status,
        load_run_state,
    )

    from vmn_exp.integrations.ray_tune import TuneRecorder

    recorder = TuneRecorder(app_name=APP_NAME)
    inner_id = None
    storage_ref = None
    try:
        recorder.on_trial_start("t1", {"lr": 0.001})
        inner = recorder._trial_runs["t1"]
        inner_id = inner.id
        storage_ref = inner._storage

        recorder.on_trial_error("t1")
    finally:
        recorder.finish()

    state = load_run_state(storage_ref, APP_NAME, inner_id)
    assert state.get("exit_code") == 1, (
        f"error trial must have exit_code=1, got {state.get('exit_code')!r}"
    )
    status = derive_status(state)
    assert status == FAILED, f"error trial status should be {FAILED!r}, got {status!r}"


# ---------------------------------------------------------------------------
# Test 5: real Ray Tune integration (skip if ray not installed)
# ---------------------------------------------------------------------------


def test_real_ray_tune_run_with_vmn_callback(tmp_path, monkeypatch):
    """2-trial tune.run with VmnTuneCallback; requires ray.

    Verifies that the driver-side callback creates 1 outer + 2 inner runs.
    Skipped when ray is not installed.
    """
    pytest.importorskip("ray")
    import ray
    import ray.tune as tune

    # Container mode — no git checkout needed
    image = tmp_path / "image"
    image.mkdir()
    (image / "vmn_metadata.yml").write_text(
        yaml.safe_dump(
            {
                "verstr": "0.0.1-dev.aaa1111.bbb2222",
                "app_name": APP_NAME,
                "base_version": "0.0.1",
                "base_commit": "aaa1111" * 5 + "aaaaa",
                "branch": "main",
            }
        )
    )
    store = tmp_path / "store"
    store.mkdir()
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)
    monkeypatch.delenv("VMN_EXPERIMENT_ID", raising=False)
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(image / "vmn_metadata.yml"))
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(store))

    from version_stamp.cli.snapshot import get_snapshot_storage

    from vmn_exp.integrations.ray_tune import TuneRecorder, make_callback

    recorder = TuneRecorder(app_name=APP_NAME, experiment_name="ray-test sweep")
    callback = make_callback(recorder)

    def trainable(config):
        tune.report(loss=config["x"] ** 2, training_iteration=1)

    ray.init(num_cpus=1, ignore_reinit_error=True)
    try:
        tune.run(
            trainable,
            config={"x": tune.grid_search([1, 2])},
            callbacks=[callback],
            verbose=0,
        )
    finally:
        recorder.finish()
        ray.shutdown()

    storage = get_snapshot_storage(
        "local", vmn_root_path=str(store), subdir="experiments"
    )
    runs = storage.list_snapshots(APP_NAME)
    # 1 outer run + 2 inner runs (one per grid search value) = 3 total
    assert len(runs) == 3, f"expected 3 runs (1 outer + 2 inner), got {len(runs)}"
