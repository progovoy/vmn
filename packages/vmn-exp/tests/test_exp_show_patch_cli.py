"""``vmn-exp show <app> -v <ref> --patch [--max-bytes N]``: a run's own text
patches (working tree, local commits, deps), never its untracked tarball."""
import json
import os

import pytest
from exp_helpers import _bootstrap, _exp, _storage, extract_dev_verstr
from version_stamp.core import logging as vmn_logging
from vmn_exp.core import code_store
from vmn_exp.storage.areas import app_key, local_store_root


@pytest.fixture(autouse=True)
def _logger():
    vmn_logging.ensure_logger()


def _dirty_run(app_layout, capfd):
    """A run with a local commit and an uncommitted tracked change."""
    _bootstrap(app_layout)
    app_layout.write_file_commit_and_push("test_repo_0", "tracked.txt", "initial\n")
    app_layout.write_file_commit_and_push(
        "test_repo_0", "loss.py", "def focal_loss():\n    pass\n",
        push=False, commit_msg="try focal loss",
    )
    with open(os.path.join(app_layout.repo_path, "tracked.txt"), "w") as f:
        f.write("dirty\n")
    capfd.readouterr()
    assert _exp(app_layout.app_name) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)
    assert verstr is not None
    return verstr


def _show(capfd, app_layout, verstr, *extra):
    capfd.readouterr()
    rc = _exp(app_layout.app_name, action="show", version=verstr, extra_args=list(extra))
    return rc, capfd.readouterr()


def _show_json(capfd, app_layout, verstr, *extra):
    rc, out = _show(capfd, app_layout, verstr, "--json", *extra)
    assert rc == 0, out.err
    return json.loads(out.out)


def _seed(app_layout, verstr, metadata):
    storage = _storage(app_layout)
    app = app_layout.app_name
    meta = dict({"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, **metadata)
    storage.save(app, verstr, meta, {})
    storage.append_log_entry(app, verstr, "w", {
        "timestamp": meta["timestamp"], "type": "create", "params": {"lr": 0.1},
    })


def test_patch_prints_the_working_tree_and_local_commit_patches(app_layout, capfd):
    verstr = _dirty_run(app_layout, capfd)
    rc, out = _show(capfd, app_layout, verstr, "--patch")
    assert rc == 0, out.err
    assert f"Experiment: {verstr}" in out.out
    working = out.out.index("=== working_tree ===")
    commits = out.out.index("=== local_commits ===")
    assert working < commits
    assert "diff --git a/tracked.txt b/tracked.txt" in out.out
    assert "+dirty" in out.out
    assert "Subject: [PATCH] try focal loss" in out.out
    assert "+def focal_loss():" in out.out
    assert "truncated" not in out.out


def test_show_without_patch_prints_no_patch_text(app_layout, capfd):
    verstr = _dirty_run(app_layout, capfd)
    rc, out = _show(capfd, app_layout, verstr)
    assert rc == 0, out.err
    assert "working_tree:" in out.out
    assert "===" not in out.out and "diff --git" not in out.out
    assert "patch" not in _show_json(capfd, app_layout, verstr)


def test_json_patch_carries_the_text_and_keeps_line_counts(app_layout, capfd):
    verstr = _dirty_run(app_layout, capfd)
    payload = _show_json(capfd, app_layout, verstr, "--patch")
    assert payload["patch"]["truncated"] is False
    text = payload["patch"]["text"]
    assert text.startswith("=== working_tree ===\n")
    assert "Subject: [PATCH] try focal loss" in text
    assert set(payload["patches"]) == {"working_tree", "local_commits"}
    assert all(isinstance(n, int) for n in payload["patches"].values())


def test_max_bytes_truncates_and_says_so(app_layout, capfd):
    verstr = _dirty_run(app_layout, capfd)
    rc, out = _show(capfd, app_layout, verstr, "--patch", "--max-bytes", "60")
    assert rc == 0, out.err
    assert "=== working_tree ===" in out.out
    assert "Subject: [PATCH]" not in out.out
    assert "truncated" in out.out and "--max-bytes" in out.out

    payload = _show_json(capfd, app_layout, verstr, "--patch", "--max-bytes", "60")
    assert payload["patch"]["truncated"] is True
    assert len(payload["patch"]["text"].encode("utf-8")) <= 60


def test_a_clean_tree_run_notes_it_has_no_patch(app_layout, capfd):
    _bootstrap(app_layout)
    assert _exp(app_layout.app_name) == 0
    verstr = _storage(app_layout).list_snapshots(app_layout.app_name)[-1]["verstr"]
    rc, out = _show(capfd, app_layout, verstr, "--patch")
    assert rc == 0, out.err
    assert f"Experiment: {verstr}" in out.out and "===" not in out.out
    note = [line for line in out.err.splitlines() if verstr in line]
    assert len(note) == 1 and "clean tree" in note[0]

    payload = _show_json(capfd, app_layout, verstr, "--patch")
    assert payload["patch"] == {"text": None, "reason": "no_code"}


def test_an_imported_run_notes_it_has_no_code(app_layout, capfd):
    _bootstrap(app_layout)
    verstr = "0.0.1-dev.r0001"
    _seed(app_layout, verstr, {"imported_from": {"tool": "mlflow", "run_id": "abc"}})
    rc, out = _show(capfd, app_layout, verstr, "--patch")
    assert rc == 0, out.err
    assert f"Experiment: {verstr}" in out.out
    assert "imported from mlflow run abc" in out.err

    payload = _show_json(capfd, app_layout, verstr, "--patch")
    assert payload["patch"] == {"text": None, "reason": "no_code"}
    assert payload["params"] == {"lr": 0.1}


def test_a_run_whose_code_object_is_gone_notes_it(app_layout, capfd):
    verstr = _dirty_run(app_layout, capfd)
    app = app_layout.app_name
    key = _storage(app_layout).load_metadata(app, verstr)["code"]
    marker = os.path.join(
        local_store_root(app_layout.repo_path), "code", app_key(app), key, "metadata.yml"
    )
    os.unlink(marker)
    rc, out = _show(capfd, app_layout, verstr, "--patch")
    assert rc == 0, out.err
    assert "===" not in out.out
    assert "is missing from the store" in out.err

    payload = _show_json(capfd, app_layout, verstr, "--patch")
    assert payload["patch"] == {"text": None, "reason": "code_missing"}


def test_dep_patches_are_labelled_and_the_tarball_is_skipped(app_layout, capfd):
    _bootstrap(app_layout)
    app = app_layout.app_name
    verstr = "0.0.1-dev.abcdef1.1234567"
    key = code_store.code_key(verstr, "1234567" + "0" * 57)
    payload = {
        "working_tree": "diff --git a/f b/f\n+x\n",
        "untracked_files": b"\x1f\x8bTARBYTES",
        "deps": {"../dep": {"local_commits": "From abc\nSubject: [PATCH] dep fix\n"}},
    }
    summary = {"has_working_tree_patch": True, "has_dep_patches": True}
    code_store.store_code(_storage(app_layout), app, key, payload, summary)
    _seed(app_layout, verstr, dict(summary, code=key, base_commit="f" * 40))

    rc, out = _show(capfd, app_layout, verstr, "--patch")
    assert rc == 0, out.err
    assert "=== working_tree ===\ndiff --git a/f b/f\n+x\n" in out.out
    assert "=== deps/.._dep/local_commits ===\nFrom abc\n" in out.out
    assert "TARBYTES" not in out.out

    text = _show_json(capfd, app_layout, verstr, "--patch")["patch"]["text"]
    assert "Subject: [PATCH] dep fix" in text and "TARBYTES" not in text
