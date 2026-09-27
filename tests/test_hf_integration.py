"""Integration tests for the HuggingFace Transformers autolog adapter (D2+D3).

Tests that do NOT require transformers run unconditionally.
Tests that DO require transformers are gated with pytest.importorskip.
"""
from __future__ import annotations

import subprocess
import sys
import types
import unittest.mock as mock

import pytest


# ---------------------------------------------------------------------------
# Lazy-import boundary tests (no transformers needed)
# ---------------------------------------------------------------------------

def test_import_vmn_exp_integrations_hf_does_not_import_transformers():
    """Importing the hf module must not pull in transformers."""
    code = (
        "import vmn_exp.integrations.hf; "
        "import sys; "
        "assert 'transformers' not in sys.modules, "
        "'transformers was imported by vmn_exp.integrations.hf'"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"transformers was imported or other error:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_autolog_import_does_not_import_transformers():
    """Importing autolog must not import transformers."""
    code = (
        "from version_stamp.exp import autolog; "
        "import sys; "
        "assert 'transformers' not in sys.modules, "
        "'transformers pulled in by autolog import'"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True,
    )
    assert result.returncode == 0, (
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )


def test_autolog_call_without_transformers_does_not_crash():
    """autolog() called when transformers is absent is a silent no-op."""
    from version_stamp.exp import autolog, autolog_disable
    try:
        autolog(frameworks=["transformers"])  # should not raise
    finally:
        autolog_disable()


# ---------------------------------------------------------------------------
# VmnCallback unit tests with stub objects (no real transformers)
# ---------------------------------------------------------------------------

def _make_stub_args(**kw):
    """Minimal TrainingArguments stub."""
    obj = types.SimpleNamespace(**kw)
    obj.to_dict = lambda: dict(vars(obj))
    return obj


def _make_stub_state(step=0, is_world_process_zero=True):
    return types.SimpleNamespace(
        global_step=step,
        is_world_process_zero=is_world_process_zero,
    )


def _make_stub_control():
    return types.SimpleNamespace()


def test_vmn_callback_no_run_is_noop(tmp_path):
    """When there is no active run, VmnCallback callbacks do nothing."""
    # Stub transformers.TrainerCallback so we don't need the real package
    fake_transformers = types.ModuleType("transformers")
    class _FakeTrainerCallback:
        pass
    fake_transformers.TrainerCallback = _FakeTrainerCallback
    # Temporarily inject the stub so the lazy builder finds it
    orig = sys.modules.get("transformers")
    sys.modules["transformers"] = fake_transformers
    try:
        # Reset the cached class so it's rebuilt with the stub
        import vmn_exp.integrations.hf as hf_mod
        hf_mod._vmn_callback_class = None

        cb = hf_mod.VmnCallback()
        args = _make_stub_args(learning_rate=1e-4, output_dir=str(tmp_path))
        state = _make_stub_state()
        ctrl = _make_stub_control()

        # None of these should raise even with no active run
        with mock.patch("version_stamp.exp.context.current_run", return_value=None):
            cb.on_train_begin(args, state, ctrl)
            cb.on_log(args, state, ctrl, logs={"loss": 0.5})
            cb.on_save(args, state, ctrl)
    finally:
        hf_mod._vmn_callback_class = None
        if orig is None:
            sys.modules.pop("transformers", None)
        else:
            sys.modules["transformers"] = orig


def test_vmn_callback_logs_params_on_train_begin(tmp_path):
    """on_train_begin logs learning_rate as a param when a run is open."""
    fake_transformers = types.ModuleType("transformers")
    class _FakeTrainerCallback:
        pass
    fake_transformers.TrainerCallback = _FakeTrainerCallback
    orig = sys.modules.get("transformers")
    sys.modules["transformers"] = fake_transformers
    try:
        import vmn_exp.integrations.hf as hf_mod
        hf_mod._vmn_callback_class = None

        cb = hf_mod.VmnCallback()
        args = _make_stub_args(learning_rate=2e-5, output_dir=str(tmp_path))
        state = _make_stub_state()
        ctrl = _make_stub_control()

        fake_run = mock.MagicMock()
        with mock.patch("version_stamp.exp.context.current_run", return_value=fake_run):
            cb.on_train_begin(args, state, ctrl)

        params_call_kwargs = fake_run.log_params.call_args
        assert params_call_kwargs is not None, "log_params was not called"
        recorded = params_call_kwargs[0][0]
        assert "learning_rate" in recorded
        assert recorded["learning_rate"] == pytest.approx(2e-5)
    finally:
        hf_mod._vmn_callback_class = None
        if orig is None:
            sys.modules.pop("transformers", None)
        else:
            sys.modules["transformers"] = orig


def test_vmn_callback_logs_metrics_on_log():
    """on_log logs rewritten metrics with the correct step."""
    fake_transformers = types.ModuleType("transformers")
    class _FakeTrainerCallback:
        pass
    fake_transformers.TrainerCallback = _FakeTrainerCallback
    orig = sys.modules.get("transformers")
    sys.modules["transformers"] = fake_transformers
    try:
        import vmn_exp.integrations.hf as hf_mod
        hf_mod._vmn_callback_class = None

        cb = hf_mod.VmnCallback()
        args = _make_stub_args(output_dir="/tmp")
        state = _make_stub_state(step=5)
        ctrl = _make_stub_control()

        fake_run = mock.MagicMock()
        with mock.patch("version_stamp.exp.context.current_run", return_value=fake_run):
            cb.on_log(args, state, ctrl, logs={"loss": 0.3, "eval_loss": 0.5})

        fake_run.log_metrics.assert_called_once()
        metrics_dict, call_kwargs = fake_run.log_metrics.call_args[0][0], fake_run.log_metrics.call_args[1]
        assert "train/loss" in metrics_dict
        assert "eval/loss" in metrics_dict
        assert call_kwargs.get("step") == 5 or fake_run.log_metrics.call_args[1].get("step") == 5
    finally:
        hf_mod._vmn_callback_class = None
        if orig is None:
            sys.modules.pop("transformers", None)
        else:
            sys.modules["transformers"] = orig


# ---------------------------------------------------------------------------
# Callback-not-doubled test (stub Trainer with add_callback)
# ---------------------------------------------------------------------------

def test_callback_not_doubled_on_autolog():
    """Patching Trainer.__init__ should add VmnCallback exactly once."""
    fake_transformers = types.ModuleType("transformers")
    class _FakeTrainerCallback:
        pass
    fake_transformers.TrainerCallback = _FakeTrainerCallback
    orig_tf = sys.modules.get("transformers")
    sys.modules["transformers"] = fake_transformers

    # Create a minimal stub for transformers.trainer submodule
    fake_trainer_mod = types.ModuleType("transformers.trainer")

    class _FakeCallbackHandler:
        def __init__(self):
            self.callbacks = []

    class FakeTrainer:
        def __init__(self, model=None, args=None, **kwargs):
            self.callback_handler = _FakeCallbackHandler()
            self._added_callbacks = []

        def add_callback(self, cb):
            self.callback_handler.callbacks.append(cb)
            self._added_callbacks.append(cb)

    fake_trainer_mod.Trainer = FakeTrainer
    orig_tm = sys.modules.get("transformers.trainer")
    sys.modules["transformers.trainer"] = fake_trainer_mod

    try:
        import vmn_exp.integrations.hf as hf_mod
        hf_mod._vmn_callback_class = None

        from version_stamp.exp import autolog, autolog_disable
        from version_stamp.exp.autolog_hf import _maybe_add_callback

        # Simulate patching by applying _discover_hf and then calling _maybe_add_callback
        trainer = FakeTrainer()
        _maybe_add_callback(trainer)
        vmn_count = sum(
            1 for cb in trainer.callback_handler.callbacks
            if type(cb).__name__ == "VmnCallback"
        )
        assert vmn_count == 1, f"Expected 1 VmnCallback, got {vmn_count}"

        # Add again — must not double
        _maybe_add_callback(trainer)
        vmn_count2 = sum(
            1 for cb in trainer.callback_handler.callbacks
            if type(cb).__name__ == "VmnCallback"
        )
        assert vmn_count2 == 1, f"Expected still 1 VmnCallback after second call, got {vmn_count2}"
    finally:
        hf_mod._vmn_callback_class = None
        if orig_tf is None:
            sys.modules.pop("transformers", None)
        else:
            sys.modules["transformers"] = orig_tf
        if orig_tm is None:
            sys.modules.pop("transformers.trainer", None)
        else:
            sys.modules["transformers.trainer"] = orig_tm


def test_autolog_transformers_in_supported_frameworks():
    """'transformers' must appear in SUPPORTED_FRAMEWORKS."""
    from version_stamp.exp.autolog import SUPPORTED_FRAMEWORKS
    assert "transformers" in SUPPORTED_FRAMEWORKS


def test_transformers_adapter_has_watch():
    """The transformers adapter must declare a watch= submodule."""
    from version_stamp.exp.autolog import SUPPORTED_FRAMEWORKS
    adapter = SUPPORTED_FRAMEWORKS["transformers"]
    assert hasattr(adapter, "watch"), "adapter has no watch field"
    assert "transformers.trainer" in adapter.watch


# ---------------------------------------------------------------------------
# Real transformers + torch tests (skipped if not available)
# ---------------------------------------------------------------------------

@pytest.mark.slow
def test_real_hf_trainer_autologs(tmp_path, monkeypatch):
    """Full round-trip: tiny BertConfig, 2 steps, autolog records metrics.

    Uses VMN_SNAPSHOT_METADATA + VMN_EXPERIMENT_DIR so no Docker / git repo
    is required for this standalone test.
    """
    import warnings

    # Disable TF backend before any transformers import to avoid Keras 3 conflict.
    import os as _os
    _os.environ["USE_TF"] = "0"

    pytest.importorskip("transformers")
    torch = pytest.importorskip("torch")
    import yaml

    from transformers import (  # noqa: PLC0415
        BertConfig,
        BertForMaskedLM,
        Trainer,
        TrainingArguments,
    )

    from version_stamp.exp import autolog, autolog_disable, start_run  # noqa: E402
    from version_stamp.exp.reader import get_run, list_runs  # noqa: E402

    # -- git-free setup -------------------------------------------------------
    image = tmp_path / "image"
    image.mkdir()
    exp_dir = tmp_path / "experiments"
    exp_dir.mkdir()
    meta = {
        "verstr": "0.1.0-dev.abc1234.0000000",
        "app_name": "hf_autolog_test",
        "base_version": "0.1.0",
        "base_commit": "abc1234",
    }
    (image / "vmn_metadata.yml").write_text(yaml.safe_dump(meta))
    monkeypatch.setenv("VMN_SNAPSHOT_METADATA", str(image / "vmn_metadata.yml"))
    monkeypatch.setenv("VMN_EXPERIMENT_DIR", str(exp_dir))
    monkeypatch.delenv("VMN_WORKING_DIR", raising=False)

    # -- tiny model + dataset --------------------------------------------------
    config = BertConfig(
        hidden_size=32,
        num_hidden_layers=1,
        num_attention_heads=1,
        intermediate_size=64,
        vocab_size=100,
    )
    model = BertForMaskedLM(config)

    class _DS(torch.utils.data.Dataset):
        def __len__(self):
            return 4

        def __getitem__(self, idx):
            return {
                "input_ids": torch.randint(0, 100, (16,)),
                "attention_mask": torch.ones(16, dtype=torch.long),
                "labels": torch.randint(0, 100, (16,)),
            }

    training_args = TrainingArguments(
        output_dir=str(tmp_path / "trainer_out"),
        max_steps=2,
        logging_steps=1,
        use_cpu=True,
        report_to=[],
        save_strategy="no",
    )

    # -- autolog + train -------------------------------------------------------
    autolog(frameworks=["transformers"])
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            with start_run() as run:  # app_name resolved from VMN_SNAPSHOT_METADATA
                verstr = run.id
                trainer = Trainer(
                    model=model,
                    args=training_args,
                    train_dataset=_DS(),
                )
                trainer.train()
    finally:
        autolog_disable()

    # -- read back the recorded run -------------------------------------------
    from vmn_exp.storage.local import LocalSnapshotStorage  # noqa: E402

    storage = LocalSnapshotStorage(str(exp_dir), subdir="experiments")
    detail = get_run("hf_autolog_test", verstr, storage=storage)

    # series["train/loss"]: 2 logging steps → 2 step entries
    series = detail.get("series", {})
    loss_series = series.get("train/loss", [])
    assert len(loss_series) >= 2, (
        f"Expected >= 2 train/loss points, got {loss_series!r}; series keys: {list(series)}"
    )

    # learning_rate must be logged as a param
    params = detail.get("params", {})
    assert "learning_rate" in params, (
        f"params missing learning_rate; got: {list(params)}"
    )

    # Query language: metrics."train/loss" > 0 must match
    from vmn_exp.core.query import compile_query  # noqa: E402

    rows = list_runs("hf_autolog_test", storage=storage)
    assert rows, "no runs returned by list_runs"
    q = compile_query('metrics."train/loss" > 0')
    assert any(q(row) for row in rows), (
        f"query did not match any row; rows={rows!r}"
    )
