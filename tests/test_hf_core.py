"""Tests for vmn_exp.integrations.hf_core — no transformers required."""
import os
import subprocess
import sys
import tempfile
import pathlib

import pytest

from vmn_exp.integrations.hf_core import (
    rewrite_logs,
    params_from,
    is_world_process_zero,
    checkpoint_artifacts,
)


# ---------------------------------------------------------------------------
# rewrite_logs
# ---------------------------------------------------------------------------

def test_rewrite_logs_eval_prefix():
    result = rewrite_logs({"eval_loss": 0.5, "eval_accuracy": 0.9})
    assert result == {"eval/loss": 0.5, "eval/accuracy": 0.9}


def test_rewrite_logs_test_prefix():
    result = rewrite_logs({"test_loss": 0.3, "test_f1": 0.8})
    assert result == {"test/loss": 0.3, "test/f1": 0.8}


def test_rewrite_logs_train_prefix_default():
    result = rewrite_logs({"loss": 0.4, "learning_rate": 1e-5})
    assert result == {"train/loss": 0.4, "train/learning_rate": 1e-5}


def test_rewrite_logs_epoch_mapped_to_train():
    result = rewrite_logs({"epoch": 1.0, "loss": 0.2})
    assert "train/epoch" in result
    assert result["train/epoch"] == 1.0


def test_rewrite_logs_drops_non_numeric_values():
    result = rewrite_logs({"loss": 0.5, "tag": "some_string", "flag": True})
    # True is technically int (bool), so it stays; string is dropped
    assert "train/tag" not in result
    assert "train/loss" in result


def test_rewrite_logs_drops_summary_keys():
    """total_flos and train_runtime-style timing keys should be dropped."""
    result = rewrite_logs({
        "total_flos": 1234567,
        "train_runtime": 99.5,
        "train_samples_per_second": 12.3,
        "train_steps_per_second": 4.5,
        "eval_runtime": 5.1,
        "eval_samples_per_second": 20.0,
        "eval_steps_per_second": 10.0,
        "loss": 0.2,
    })
    assert "train/total_flos" not in result
    assert "train/train_runtime" not in result
    assert "train/train_samples_per_second" not in result
    assert "train/train_steps_per_second" not in result
    assert "eval/runtime" not in result
    assert "eval/samples_per_second" not in result
    assert "eval/steps_per_second" not in result
    # Real metric still present
    assert "train/loss" in result


def test_rewrite_logs_mixed_prefixes():
    result = rewrite_logs({
        "eval_loss": 0.6,
        "test_loss": 0.4,
        "loss": 0.8,
        "epoch": 2.0,
    })
    assert result["eval/loss"] == 0.6
    assert result["test/loss"] == 0.4
    assert result["train/loss"] == 0.8
    assert result["train/epoch"] == 2.0


# ---------------------------------------------------------------------------
# params_from
# ---------------------------------------------------------------------------

def test_params_from_excludes_token_keys():
    args = {
        "learning_rate": 0.001,
        "push_to_hub_token": "secret",
        "hub_token": "alsosecret",
        "token": "anothersecret",
        "num_train_epochs": 3,
    }
    result = params_from(args)
    for key in result:
        assert "token" not in key.lower(), f"token key leaked: {key}"
    assert "learning_rate" in result
    assert "num_train_epochs" in result


def test_params_from_drops_logging_dir():
    args = {
        "learning_rate": 0.001,
        "logging_dir": "/tmp/logs",
        "output_dir": "/tmp/out",
    }
    result = params_from(args)
    assert "logging_dir" not in result
    assert "output_dir" in result   # output_dir is kept


def test_params_from_model_config_diff_only():
    """Only model config keys differing from defaults are included, prefixed model."""
    model_config = {
        "hidden_size": 768,
        "num_hidden_layers": 12,
        "vocab_size": 30522,
    }
    defaults = {
        "hidden_size": 768,     # same as default — not included
        "num_hidden_layers": 6,  # DIFFERENT — included
        "vocab_size": 30522,    # same — not included
        "attention_probs_dropout_prob": 0.1,  # default-only key — not in model_config, ignored
    }
    result = params_from({}, model_config_dict=model_config, default_config_dict=defaults)
    assert "model.num_hidden_layers" in result
    assert result["model.num_hidden_layers"] == 12
    assert "model.hidden_size" not in result
    assert "model.vocab_size" not in result


def test_params_from_model_config_no_defaults():
    """When no defaults provided, all model config keys are included."""
    model_config = {"hidden_size": 512, "num_layers": 6}
    result = params_from({}, model_config_dict=model_config)
    assert "model.hidden_size" in result
    assert "model.num_layers" in result


def test_params_from_empty():
    assert params_from({}) == {}


# ---------------------------------------------------------------------------
# is_world_process_zero
# ---------------------------------------------------------------------------

def test_is_world_process_zero_true_flag():
    assert is_world_process_zero(True) is True


def test_is_world_process_zero_false_flag():
    assert is_world_process_zero(False) is False


def test_is_world_process_zero_state_object():
    class FakeState:
        is_world_process_zero = True

    assert is_world_process_zero(FakeState()) is True


def test_is_world_process_zero_state_object_false():
    class FakeState:
        is_world_process_zero = False

    assert is_world_process_zero(FakeState()) is False


# ---------------------------------------------------------------------------
# checkpoint_artifacts
# ---------------------------------------------------------------------------

def test_checkpoint_artifacts_sorted_by_step():
    with tempfile.TemporaryDirectory() as tmpdir:
        base = pathlib.Path(tmpdir)
        (base / "checkpoint-100").mkdir()
        (base / "checkpoint-500").mkdir()
        (base / "checkpoint-50").mkdir()
        (base / "other-dir").mkdir()
        (base / "not-a-checkpoint").mkdir()

        result = checkpoint_artifacts(tmpdir)
        names = [pathlib.Path(p).name for p in result]
        assert names == ["checkpoint-50", "checkpoint-100", "checkpoint-500"]


def test_checkpoint_artifacts_empty_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        result = checkpoint_artifacts(tmpdir)
        assert result == []


def test_checkpoint_artifacts_missing_dir():
    result = checkpoint_artifacts("/nonexistent/path/xyz")
    assert result == []


# ---------------------------------------------------------------------------
# no transformers import
# ---------------------------------------------------------------------------

def test_hf_core_does_not_import_transformers():
    """Importing hf_core must not cause transformers to be imported."""
    code = (
        "import vmn_exp.integrations.hf_core; "
        "import sys; "
        "assert 'transformers' not in sys.modules, "
        "f'transformers was imported: {[k for k in sys.modules if \"transformers\" in k]}'"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"transformers was imported or other error:\n"
        f"stdout: {result.stdout}\nstderr: {result.stderr}"
    )
