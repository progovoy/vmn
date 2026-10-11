"""`vmn-exp create`'s cold start in a CI-style detached checkout commits on the
real branch and pushes it, like `vmn stamp` (plan 17 F6)."""
import os

import pytest
from exp_helpers import _experiment
from island_helpers import (  # noqa: F401 (_no_ci_env is an autouse fixture)
    _branches,
    _ci_checkout,
    _current,
    _no_ci_env,
    _out,
)


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        monkeypatch.delenv(key, raising=False)


def test_cli_cold_start_at_the_remote_tip_commits_on_the_real_branch(app_layout):
    repo = app_layout.repo_path
    default = _current(repo)
    _ci_checkout(repo, default)

    assert _experiment(app_layout.app_name, action="create") == 0

    assert _current(repo) == default
    assert _branches(repo) == [default]
    assert _out(repo, "rev-parse", "HEAD") == _out(repo, "rev-parse", f"origin/{default}")
    assert os.path.isfile(os.path.join(repo, ".vmn", app_layout.app_name, "conf.yml"))
