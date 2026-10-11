"""``vmn-exp rerun`` records a ``features`` entry (``source: rerun``): the
original's code facts — copied from its features entry, or derived from its
code object when it has none — with the rerunner as the author."""
import pytest
from rerun_helpers import log, original_run, rerun
from version_stamp.core import logging as vmn_logging
from vmn_exp.core import identity
from vmn_exp.core.features import FEATURES_VERSION
from vmn_exp.core.fold import fold_features, fold_log


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    vmn_logging.ensure_logger()
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", "VMN_SNAPSHOT_METADATA",
                "VMN_EXPERIMENT_DIR", identity.AUTHOR_ENV):
        monkeypatch.delenv(key, raising=False)


def _features(app_layout, verstr):
    return fold_features(fold_log(log(app_layout, verstr)))


def _as_rerunner(monkeypatch):
    monkeypatch.setattr(identity, "_git_user_email", lambda cwd=None: "")
    monkeypatch.setenv("VMN_EXP_AUTHOR", "rerunner@x.io")


def test_a_rerun_copies_the_originals_features_with_the_rerunner_as_author(
    app_layout, monkeypatch,
):
    original = original_run(app_layout)
    _as_rerunner(monkeypatch)
    rc, new = rerun(app_layout, original)
    assert rc == 0

    features, source = _features(app_layout, new), _features(app_layout, original)
    assert features["source"] == "rerun"
    assert features["features_version"] == FEATURES_VERSION
    assert features["changed"] == source["changed"]
    assert source["author"]["git_user_email"] == "test@test.com"
    assert features["author"]["git_user_email"] == "rerunner@x.io"
    assert features["author"]["source"] == "env"


def test_a_rerun_of_a_run_without_features_derives_them_from_its_code(
    app_layout, monkeypatch,
):
    import vmn_exp.gitmode.features as gitmode_features

    def _boom(texts):
        raise RuntimeError("no features for the original")

    with monkeypatch.context() as patched:
        patched.setattr(gitmode_features, "features_from_patches", _boom)
        original = original_run(app_layout)
    assert _features(app_layout, original) is None

    rc, new = rerun(app_layout, original)
    assert rc == 0
    features = _features(app_layout, new)
    assert features["source"] == "rerun"
    assert features["changed"]["files"] == ["value.txt"]
    assert features["changed"]["untracked"] == ["train.py"]
    assert features["author"]["git_user_email"] == "test@test.com"
