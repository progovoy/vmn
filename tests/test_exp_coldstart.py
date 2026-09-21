"""The SDK must cold-start a repo, exactly as ``vmn exp create``/``run`` do.

``vmn exp`` auto-initializes vmn tracking and stamps a ``0.0.0`` baseline on its
first use in a fresh repo. ``start_run()`` is documented as the in-process
equivalent of ``vmn exp run``, so it has to do the same — the other SDK tests all
bootstrap the app first, which is exactly how this gap survived.
"""
import os

import pytest
from helpers import _experiment, _storage

from version_stamp.exp import start_run


@pytest.fixture(autouse=True)
def _clean_experiment_env():
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        os.environ.pop(key, None)
    yield
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        os.environ.pop(key, None)


def test_start_run_cold_starts_an_untracked_repo(app_layout, capfd):
    # Deliberately no _run_vmn_init / _init_app / _stamp_app: this is what a
    # user's very first start_run() in a fresh repo sees.
    with start_run(app_layout.app_name, note="first sdk run") as run:
        run.log_metric("acc", 0.5)
        verstr = run.id

    assert verstr

    metas = _storage(app_layout).list_snapshots(app_layout.app_name)
    assert [m["verstr"] for m in metas] == [verstr]

    capfd.readouterr()
    assert _experiment(app_layout.app_name, action="list") == 0
    out = capfd.readouterr().out
    assert verstr in out
    assert "first sdk run" in out


def test_cold_started_app_is_tracked_and_stamped(app_layout):
    with start_run(app_layout.app_name) as run:
        assert run.id.startswith("0.0.0-dev.")

    assert os.path.isfile(os.path.join(app_layout.repo_path, ".vmn", "conf.yml"))
    assert os.path.isfile(
        os.path.join(app_layout.repo_path, ".vmn", app_layout.app_name, "conf.yml")
    )


def test_second_start_run_does_not_reinitialize(app_layout):
    with start_run(app_layout.app_name) as first:
        pass
    with start_run(app_layout.app_name) as second:
        pass

    assert first.id != second.id
    verstrs = [
        m["verstr"] for m in _storage(app_layout).list_snapshots(app_layout.app_name)
    ]
    assert sorted(verstrs) == sorted([first.id, second.id])
