import os

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient

from helpers import (
    _init_app,
    _run_vmn_init,
    _stamp_app,
)


def _client(app_layout):
    from version_stamp.ui.server import create_app
    from version_stamp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(os.path.join(app_layout.base_dir, "ui_data"))
    manager.attach_path("main", app_layout.repo_path)
    return TestClient(create_app(manager))


def test_group_commits_sections_and_breaking():
    """Conventional commits group by type; breaking changes split out; order fixed."""
    from version_stamp.core.changelog import group_commits

    commits = [
        ("feat(ui): stamp tree", "aaaaaaa"),
        ("fix: off-by-one", "bbbbbbb"),
        ("docs: readme", "ccccccc"),
        ("feat!: drop py2", "ddddddd"),
        ("just a plain message\n\nwith a body", "fffffff"),
    ]

    result = group_commits(commits)

    labels = [g["label"] for g in result["groups"]]
    assert labels[:2] == ["Features", "Bug Fixes"]  # priority sections first
    assert "Documentation" in labels
    assert labels[-1] == "Other Changes"  # catch-all sorts last

    feats = next(g for g in result["groups"] if g["label"] == "Features")
    assert feats["commits"][0]["scope"] == "ui"
    assert feats["commits"][0]["description"] == "stamp tree"
    assert feats["commits"][0]["hash"] == "aaaaaaa"

    # A `!` subject marker lands in breaking (mirrors stamp-time detection).
    breaking_hashes = {c["hash"] for c in result["breaking"]}
    assert breaking_hashes == {"ddddddd"}
    # A breaking feat is not double-counted in Features.
    assert "ddddddd" not in {c["hash"] for c in feats["commits"]}

    # A non-conventional message is kept under Other Changes by its subject line.
    other = next(g for g in result["groups"] if g["label"] == "Other Changes")
    plain = next(c for c in other["commits"] if c["hash"] == "fffffff")
    assert plain["description"] == "just a plain message"


def test_ui_version_changelog(app_layout, capfd):
    """The /changelog endpoint groups commits between a version and its previous."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")  # 0.0.1

    app_layout.write_file_commit_and_push(
        "test_repo_0", "a.txt", "a", commit_msg="feat: add widget"
    )
    app_layout.write_file_commit_and_push(
        "test_repo_0", "b.txt", "b", commit_msg="fix: patch leak"
    )
    _stamp_app(app_layout.app_name, "minor")  # 0.1.0

    client = _client(app_layout)
    r = client.get(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/changelog?v=0.1.0"
    )
    assert r.status_code == 200
    cl = r.json()

    assert cl["to_verstr"] == "0.1.0"
    assert cl["from_verstr"] == "0.0.1"
    labels = {g["label"] for g in cl["groups"]}
    assert {"Features", "Bug Fixes"} <= labels
    descriptions = {
        c["description"] for g in cl["groups"] for c in g["commits"]
    }
    assert {"add widget", "patch leak"} <= descriptions
    # vmn's own stamp commits ("<app>: Stamped version ...") must not leak in —
    # the range runs between the version tags, which point at those commits.
    assert not any("Stamped" in d for d in descriptions)


def test_ui_version_changelog_non_adjacent_skips_interior_stamps(app_layout, capfd):
    """A range spanning an intermediate version excludes that version's stamp
    commit — vmn's own commits never appear, even mid-range."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")  # 0.0.1

    app_layout.write_file_commit_and_push(
        "test_repo_0", "a.txt", "a", commit_msg="feat: one"
    )
    _stamp_app(app_layout.app_name, "patch")  # 0.0.2 (interior stamp commit)
    app_layout.write_file_commit_and_push(
        "test_repo_0", "b.txt", "b", commit_msg="fix: two"
    )
    _stamp_app(app_layout.app_name, "minor")  # 0.1.0

    client = _client(app_layout)
    r = client.get(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/changelog?v=0.1.0&from=0.0.1"
    )
    assert r.status_code == 200
    cl = r.json()
    assert cl["from_verstr"] == "0.0.1"
    descriptions = {c["description"] for g in cl["groups"] for c in g["commits"]}
    assert {"one", "two"} <= descriptions
    assert not any("Stamped" in d for d in descriptions)


def test_ui_version_changelog_baseline_is_empty(app_layout, capfd):
    """The init baseline (0.0.0) has no distinct previous, so its changelog is
    empty rather than an error (its previous_version points at itself)."""
    _run_vmn_init()
    _init_app(app_layout.app_name)
    _stamp_app(app_layout.app_name, "patch")  # 0.0.1

    client = _client(app_layout)
    r = client.get(
        f"/api/v1/workspaces/main/apps/{app_layout.app_name}/changelog?v=0.0.0"
    )
    assert r.status_code == 200
    cl = r.json()
    assert cl["from_verstr"] is None
    assert cl["groups"] == []
    assert cl["breaking"] == []
