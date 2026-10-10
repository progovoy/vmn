"""An SDK cold start in a CI-style detached checkout commits on the real branch."""
import pytest
from island_helpers import (  # noqa: F401 (_no_ci_env is an autouse fixture)
    _branches,
    _ci_checkout,
    _current,
    _no_ci_env,
    _out,
)

from vmn_exp.sdk import start_run


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME"):
        monkeypatch.delenv(key, raising=False)


def test_cold_start_at_the_remote_tip_commits_on_the_real_branch(app_layout):
    repo = app_layout.repo_path
    default = _current(repo)
    _ci_checkout(repo, default)

    with start_run(app_layout.app_name):
        pass

    assert _current(repo) == default
    assert _branches(repo) == [default]
    assert f"{app_layout.app_name}_0.0.0" in _out(repo, "tag", "--points-at", "HEAD")
