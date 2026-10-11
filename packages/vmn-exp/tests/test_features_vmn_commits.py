"""vmn's own bookkeeping commits (init, stamp: authored as ``vmn``) are not a
run's: an SDK cold start leaves them local and unpushed, so the run's local
commits hold them. Their subjects, author, files and functions stay out of
the features capture, a rerun and the backfill record."""
import os
import subprocess
import types

import pytest
from backfill_helpers import LC, as_backfiller, dirty_run, features_entries, seed_code
from exp_helpers import _bootstrap, _exp, _storage
from version_stamp.api import VMN_USER_NAME
from vmn_exp.core import identity
from vmn_exp.core.features import features_from_patches
from vmn_exp.core.fold import fold_features, fold_log
from vmn_exp.gitmode.features import rerun_features
from vmn_exp.sdk import start_run

SHA = "3d71d1bf894eea3f06c2c57b7bfbf77610a7ea8c"
VMN_COMMIT = f"""From {SHA} Mon Sep 17 00:00:00 2001
From: vmn <vmn>
Date: Sun, 11 Oct 2026 00:29:47 +0300
Subject: [PATCH 1/2] app: Stamped initial version 0.0.0

---
 .vmn/app/conf.yml | 1 +
 1 file changed, 1 insertion(+)

diff --git a/.vmn/app/conf.yml b/.vmn/app/conf.yml
--- a/.vmn/app/conf.yml
+++ b/.vmn/app/conf.yml
@@ -1 +1,2 @@ conf:
 conf:
+  template: x
--
2.50.1

"""
USER_COMMIT = f"""From {SHA} Mon Sep 17 00:00:00 2001
From: Alice <a@x.io>
Date: Sun, 11 Oct 2026 00:29:48 +0300
Subject: [PATCH 2/2] tune lr

---
 train.py | 1 +
 1 file changed, 1 insertion(+)

diff --git a/train.py b/train.py
--- a/train.py
+++ b/train.py
@@ -4,2 +4,3 @@ def train(x):
     lr = 1
+    lr = 2
--
2.50.1

"""


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for key in ("VMN_EXPERIMENT_ID", "VMN_APP_NAME", identity.AUTHOR_ENV):
        monkeypatch.delenv(key, raising=False)


def test_vmn_is_the_author_vmn_commits_as():
    assert VMN_USER_NAME == "vmn"


def test_commits_by_a_skipped_author_add_no_subject_author_file_or_symbol():
    mbox = VMN_COMMIT + USER_COMMIT
    assert features_from_patches([mbox])["commits"] == [
        "app: Stamped initial version 0.0.0", "tune lr"]

    result = features_from_patches([mbox], skip_authors=("vmn",))

    assert result["commits"] == ["tune lr"]
    assert result["commit_authors"] == [{"name": "Alice", "email": "a@x.io"}]
    assert result["changed"] == {"files": ["train.py"], "symbols": ["train.py::train"]}


def _without_git_identity(app_layout, monkeypatch, tmp_path):
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("USER", "carol")
    for key in ("user.email", "user.name"):
        subprocess.run(["git", "config", "--unset", key], cwd=app_layout.repo_path)


def test_an_sdk_cold_start_without_a_git_identity_records_none_of_vmns_commits(
    app_layout, monkeypatch, tmp_path,
):
    app_layout.write_file_commit_and_push("test_repo_0", "train.py", "print(1)\n")
    _without_git_identity(app_layout, monkeypatch, tmp_path)
    with open(os.path.join(app_layout.repo_path, "train.py"), "a") as f:
        f.write("lr = 0.1\n")

    with start_run(app_layout.app_name, system_metrics=False, capture_env=False) as run:
        verstr = run.id

    unpushed = subprocess.run(["git", "log", "--format=%an", "@{u}..HEAD"],
                              cwd=app_layout.repo_path, capture_output=True, text=True)
    assert set(unpushed.stdout.split()) == {"vmn"}
    log = _storage(app_layout).load_merged_log(app_layout.app_name, verstr)
    features = fold_features(fold_log(log))
    assert features["changed"]["files"] == ["train.py"]
    assert "commits" not in features
    assert "git_user_email" not in features["author"]
    assert features["author"]["source"] == "host"
    assert features["author"]["os_user"] == "carol"


def test_a_rerun_from_stored_code_leaves_out_vmns_commits(tmp_path):
    vcs = types.SimpleNamespace(backend=types.SimpleNamespace(repo_path=str(tmp_path)))
    patches = {"local_commits": VMN_COMMIT + USER_COMMIT}

    entry = rerun_features(vcs, [], {}, patches)

    assert entry["commits"] == ["tune lr"]
    assert entry["changed"]["files"] == ["train.py"]


def test_the_backfill_leaves_out_vmns_commits(app_layout, monkeypatch, capfd):
    _bootstrap(app_layout)
    as_backfiller(monkeypatch)
    storage, app = _storage(app_layout), app_layout.app_name
    seed_code(storage, app, payload={"local_commits": VMN_COMMIT + LC})
    verstr = dirty_run(storage, app, "0.0.2-dev.abc1234.1234567")
    capfd.readouterr()

    assert _exp(app, action="similar-backfill") == 0

    [entry] = features_entries(storage, app, verstr)
    assert entry["commits"] == ["try focal loss"]
    assert entry["changed"]["files"] == ["src/train.py"]
    assert entry["author"]["git_user_email"] == "alice@x.io"
