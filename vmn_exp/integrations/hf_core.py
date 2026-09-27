"""Pure utility functions for the HuggingFace Trainer integration.

No transformers import here — this module must stay importable without
the transformers package installed.

Key design decisions
--------------------
* ``rewrite_logs`` maps HF Trainer ``on_log`` callback dicts to vmn metric
  namespaces: ``eval/<key>`` / ``test/<key>`` / ``train/<key>``.
  Timing/bookkeeping summary keys are dropped (mirrors WandB/MLflow callback
  behaviour): ``total_flos``, ``*_runtime``, ``*_samples_per_second``,
  ``*_steps_per_second``.  ``epoch`` becomes ``train/epoch``.  Non-numeric
  values are dropped.

* ``params_from`` converts a TrainingArguments ``to_dict()`` output into flat
  params, excluding:
    - any key containing the substring ``"token"`` (avoids leaking secrets)
    - ``"logging_dir"`` (noise, not a model/run parameter)
    - ``"_n_gpu"`` and other leading-underscore runtime attrs
  Model config keys that differ from provided defaults are included prefixed
  with ``"model."``.

* ``is_world_process_zero`` accepts either a plain bool or a
  ``TrainerState``-style object carrying the attribute.

* ``checkpoint_artifacts`` lists ``checkpoint-<step>`` sub-directories sorted
  by ascending step number.
"""

from __future__ import annotations

import os
import pathlib
from typing import Dict, List, Optional

# Keys dropped from trainer logs regardless of prefix —
# timing metadata / FLOPs are not per-step metrics.
_SUMMARY_SUFFIXES = ("_runtime", "_samples_per_second", "_steps_per_second")
_SUMMARY_EXACT = {"total_flos"}


def _is_numeric(value: object) -> bool:
    """Return True for int (incl. bool) and float."""
    return isinstance(value, (int, float))


def _is_summary_key(key: str) -> bool:
    if key in _SUMMARY_EXACT:
        return True
    return any(key.endswith(s) for s in _SUMMARY_SUFFIXES)


def rewrite_logs(logs: Dict[str, object]) -> Dict[str, float]:
    """Rewrite an HF Trainer on_log dict into vmn metric namespaces.

    Args:
        logs: Raw dict from the Trainer's on_log callback.

    Returns:
        Dict with keys in one of the forms ``eval/<name>``,
        ``test/<name>``, or ``train/<name>``.  Non-numeric values and
        summary/timing keys are dropped.
    """
    out: Dict[str, float] = {}
    for key, value in logs.items():
        if not _is_numeric(value):
            continue
        if _is_summary_key(key):
            continue
        if key.startswith("eval_"):
            out[f"eval/{key[len('eval_'):]}" ] = value  # type: ignore[assignment]
        elif key.startswith("test_"):
            out[f"test/{key[len('test_'):]}" ] = value  # type: ignore[assignment]
        else:
            out[f"train/{key}"] = value  # type: ignore[assignment]
    return out


# Keys dropped from TrainingArguments to_dict output.
_ARGS_DROP_EXACT = {"logging_dir"}


def _should_drop_arg(key: str) -> bool:
    if key in _ARGS_DROP_EXACT:
        return True
    if key.startswith("_"):
        return True
    if "token" in key.lower():
        return True
    return False


def params_from(
    args_dict: Dict[str, object],
    model_config_dict: Optional[Dict[str, object]] = None,
    default_config_dict: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    """Convert TrainingArguments and optional model config to flat params.

    Args:
        args_dict: ``TrainingArguments.to_dict()`` output (or any dict).
        model_config_dict: ``model.config.to_dict()`` output, if available.
        default_config_dict: Default config values (e.g. from the config
            class constructor).  When provided, only keys whose value
            differs from the default are included, prefixed ``"model."``.
            When ``None``, all model config keys are included.

    Returns:
        Flat dict suitable for ``run.log_params()``.
    """
    params: Dict[str, object] = {}

    for key, value in args_dict.items():
        if _should_drop_arg(key):
            continue
        params[key] = value

    if model_config_dict is not None:
        for key, value in model_config_dict.items():
            if default_config_dict is not None:
                if key in default_config_dict and default_config_dict[key] == value:
                    continue
            params[f"model.{key}"] = value

    return params


def is_world_process_zero(state_or_flag: object) -> bool:
    """Return whether this process is rank-0 (world process zero).

    Args:
        state_or_flag: Either a plain ``bool``, or a ``TrainerState``
            instance (or any object) with an ``is_world_process_zero``
            attribute.

    Returns:
        ``True`` when this is the main process (rank 0).
    """
    if isinstance(state_or_flag, bool):
        return state_or_flag
    attr = getattr(state_or_flag, "is_world_process_zero", True)
    if callable(attr):
        return bool(attr())
    return bool(attr)


def checkpoint_artifacts(output_dir: str) -> List[str]:
    """List checkpoint directories inside *output_dir*, sorted by step.

    Args:
        output_dir: Path to the Trainer output directory.

    Returns:
        Sorted list of absolute paths to ``checkpoint-<N>`` directories,
        ordered by ascending step number.  Returns an empty list if
        *output_dir* does not exist.
    """
    base = pathlib.Path(output_dir)
    if not base.is_dir():
        return []

    checkpoints = []
    for entry in base.iterdir():
        if entry.is_dir() and entry.name.startswith("checkpoint-"):
            suffix = entry.name[len("checkpoint-"):]
            if suffix.isdigit():
                checkpoints.append((int(suffix), str(entry)))

    checkpoints.sort(key=lambda t: t[0])
    return [path for _, path in checkpoints]
