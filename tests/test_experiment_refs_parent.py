"""Resolving a new run's parent, shared by ``vmn exp create/run`` and the SDK."""
import os

import pytest
import yaml

from version_stamp.cli.snapshot import get_snapshot_storage
from version_stamp.core.experiment_refs import resolve_parent
from version_stamp.core.logging import init_stamp_logger

APP = "app"
RUN = "0.0.1-dev.aaaa111.bbbb222"


@pytest.fixture(autouse=True)
def _init_logger():
    init_stamp_logger()


def _storage_with_run(tmp_path):
    path = os.path.join(tmp_path, ".vmn", APP, "experiments", RUN)
    os.makedirs(path)
    with open(os.path.join(path, "metadata.yml"), "w") as f:
        yaml.dump({"verstr": RUN, "timestamp": "2026-09-21T12:00:01Z"}, f)
    return get_snapshot_storage("local", vmn_root_path=str(tmp_path), subdir="experiments")


def test_no_ref_means_no_parent(tmp_path):
    assert resolve_parent(_storage_with_run(tmp_path), APP) == (None, None)


def test_an_explicit_ref_resolves_through_storage(tmp_path):
    storage = _storage_with_run(tmp_path)

    assert resolve_parent(storage, APP, "@1") == (RUN, None)


def test_an_explicit_ref_wins_over_the_env_ref(tmp_path):
    storage = _storage_with_run(tmp_path)

    assert resolve_parent(storage, APP, RUN, env_ref="@9") == (RUN, None)


def test_an_unknown_explicit_ref_is_an_error(tmp_path):
    storage = _storage_with_run(tmp_path)

    assert resolve_parent(storage, APP, "0.0.9-dev.nope") == (None, 1)


def test_the_env_ref_is_used_when_there_is_no_explicit_one(tmp_path):
    storage = _storage_with_run(tmp_path)

    assert resolve_parent(storage, APP, env_ref="@latest") == (RUN, None)


def test_a_stale_env_ref_is_dropped_not_an_error(tmp_path):
    storage = _storage_with_run(tmp_path)

    assert resolve_parent(storage, APP, env_ref="0.0.9-dev.nope") == (None, None)
