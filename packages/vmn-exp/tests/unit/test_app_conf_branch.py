"""The SDK reader picks the conf file the writer (core vmn) loads for the
checkout's branch: canonical > flat > legacy branch conf, else conf.yml
(plan 45)."""
import os

import yaml

from vmn_exp.core.app_conf import app_conf_from, current_branch

ROOT = os.path.join(os.sep, "repo")
APP_DIR = os.path.join(ROOT, ".vmn", "app")


def _reader(files):
    def read_text(path):
        try:
            return files[path]
        except KeyError:
            raise FileNotFoundError(path) from None
    return read_text


def _conf(uri):
    return yaml.safe_dump({"conf": {"store": {"uri": uri}}})


def _head(branch):
    return {os.path.join(ROOT, ".git", "HEAD"): f"ref: refs/heads/{branch}\n"}


def _store(files, app="app"):
    return app_conf_from(ROOT, app, _reader(files)).get("store", {}).get("uri")


def test_without_a_branch_conf_the_app_conf_names_the_store():
    files = {**_head("main"), os.path.join(APP_DIR, "conf.yml"): _conf("file:///a")}
    assert _store(files) == "file:///a"


def test_the_canonical_branch_conf_beats_the_app_conf():
    files = {**_head("feat/x"),
             os.path.join(APP_DIR, "conf.yml"): _conf("file:///a"),
             os.path.join(APP_DIR, "branch_conf", "feat", "x", "conf.yml"): _conf("file:///b")}
    assert _store(files) == "file:///b"


def test_the_flat_branch_conf_beats_the_legacy_one():
    files = {**_head("feat/x"),
             os.path.join(APP_DIR, "feat-x_conf.yml"): _conf("file:///flat"),
             os.path.join(APP_DIR, "feat", "x_conf.yml"): _conf("file:///legacy")}
    assert _store(files) == "file:///flat"


def test_a_branch_conf_without_store_hides_the_app_conf_store():
    files = {**_head("dev"),
             os.path.join(APP_DIR, "conf.yml"): _conf("file:///a"),
             os.path.join(APP_DIR, "branch_conf", "dev", "conf.yml"): "conf: {}\n"}
    assert _store(files) is None


def test_a_service_reads_its_own_dir():
    service_dir = os.path.join(ROOT, ".vmn", "root", "svc")
    files = {**_head("dev"),
             os.path.join(service_dir, "branch_conf", "dev", "conf.yml"): _conf("file:///s")}
    assert _store(files, "root/svc") == "file:///s"


def test_no_conf_at_all_is_empty():
    assert app_conf_from(ROOT, "app", _reader(_head("dev"))) == {}


def test_current_branch_reads_head():
    assert current_branch(ROOT, _reader(_head("feat/x"))) == "feat/x"


def test_current_branch_of_a_detached_head_is_none():
    files = {os.path.join(ROOT, ".git", "HEAD"): "0123abcd" * 5 + "\n"}
    assert current_branch(ROOT, _reader(files)) is None


def test_current_branch_follows_a_worktree_gitdir_file():
    gitdir = os.path.join(os.sep, "main", ".git", "worktrees", "wt")
    files = {os.path.join(ROOT, ".git"): f"gitdir: {gitdir}\n",
             os.path.join(gitdir, "HEAD"): "ref: refs/heads/wt-branch\n"}
    assert current_branch(ROOT, _reader(files)) == "wt-branch"


def test_current_branch_follows_a_relative_gitdir_file():
    head = os.path.normpath(os.path.join(ROOT, "..", "main", ".git", "worktrees", "wt", "HEAD"))
    files = {os.path.join(ROOT, ".git"): "gitdir: ../main/.git/worktrees/wt\n",
             head: "ref: refs/heads/rel\n"}
    assert current_branch(ROOT, _reader(files)) == "rel"


def test_no_git_dir_means_no_branch():
    assert current_branch(ROOT, _reader({})) is None
