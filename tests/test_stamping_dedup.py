"""Stamping de-duplication: root tag names and CHANGELOG.md rendering."""
import datetime
import os
import types
from unittest import mock

import pytest
from version_stamp.core.version_math import deserialize_tag_name
from version_stamp.stamping import publisher
from version_stamp.stamping.publisher import VersionControlStamper


def test_root_tag_deserializes_to_slashed_app_name():
    props = deserialize_tag_name("a-b_3")
    assert props.app_name == "a/b"
    assert "root" in props.types
    assert props.root_version == "3"
    assert props.verstr == "3"


def test_plain_root_tag_keeps_app_name():
    assert deserialize_tag_name("root_app_7").app_name == "root_app"


def test_service_tag_deserializes_to_slashed_app_name():
    props = deserialize_tag_name("root_app-svc_1.2.3")
    assert props.app_name == "root_app/svc"
    assert props.verstr == "1.2.3"


# --- CHANGELOG.md golden output -------------------------------------------

_COMMITS = [
    ("feat(ui): add dashboard", "a1"),
    ("fix: crash on start", "b2"),
    ("Merge branch 'x' into master", "c3"),
    ("docs: explain things", "d4"),
    ("feat!: drop python 2", "e5"),
    ("unknown: odd type", "f6"),
    ("chore(deps): bump", "a7"),
    ("fix(core): off by one\n\nBREAKING CHANGE: api changed", "b8"),
    ("perf: faster", "c9"),
    ("ci: pipeline", "d0"),
    ("just a plain commit", "e1"),
    ("build: wheel", "f2"),
    ("test: more tests", "a3"),
    ("feat: second feature", "b4"),
]


@pytest.fixture(autouse=True)
def _quiet_logger(monkeypatch):
    monkeypatch.setattr(publisher, "VMN_LOGGER", mock.Mock())


def _fake_stamper(tmp_path, commits):
    path = str(tmp_path / "CHANGELOG.md")
    backend = types.SimpleNamespace(get_commits_info_iter=lambda tag: iter(commits))
    fake = types.SimpleNamespace(
        changelog={"path": "CHANGELOG.md"},
        selected_tag="app_0.0.1",
        dry_run=False,
        backend=backend,
        _changelog_path=lambda: path,
    )
    return fake, path


def _golden_entry(version):
    today = datetime.date.today().isoformat()
    return (
        f"## [{version}] - {today}\n"
        "\n"
        "### Breaking Changes\n"
        "- drop python 2 (e5)\n"
        "- **core:** off by one (b8)\n"
        "\n"
        "### Features\n"
        "- **ui:** add dashboard (a1)\n"
        "- second feature (b4)\n"
        "\n"
        "### Bug Fixes\n"
        "- crash on start (b2)\n"
        "\n"
        "### Build\n"
        "- wheel (f2)\n"
        "\n"
        "### CI\n"
        "- pipeline (d0)\n"
        "\n"
        "### Chores\n"
        "- **deps:** bump (a7)\n"
        "\n"
        "### Documentation\n"
        "- explain things (d4)\n"
        "\n"
        "### Other Changes\n"
        "- odd type (f6)\n"
        "\n"
        "### Performance Improvements\n"
        "- faster (c9)\n"
        "\n"
        "### Tests\n"
        "- more tests (a3)\n"
    )


def test_changelog_golden_new_file(tmp_path):
    fake, path = _fake_stamper(tmp_path, _COMMITS)
    added = []
    VersionControlStamper._generate_changelog(fake, "1.0.0", added)
    with open(path) as f:
        content = f.read()
    assert content == "# Changelog\n\n" + _golden_entry("1.0.0") + "\n"
    assert added == [path]


def test_changelog_golden_prepends_after_header(tmp_path):
    fake, path = _fake_stamper(tmp_path, _COMMITS)
    with open(path, "w") as f:
        f.write("# Changelog\n\n## [0.0.1] - 2020-01-01\n\n- old\n")
    VersionControlStamper._generate_changelog(fake, "1.0.0", [])
    with open(path) as f:
        content = f.read()
    assert content == (
        "# Changelog\n\n\n"
        + _golden_entry("1.0.0")
        + "\n## [0.0.1] - 2020-01-01\n\n- old\n"
    )


def test_changelog_skips_non_conventional_commits(tmp_path):
    commits = [("plain one", "a1"), ("Merge x", "b2")]
    fake, path = _fake_stamper(tmp_path, commits)
    added = []
    VersionControlStamper._generate_changelog(fake, "1.0.0", added)
    assert not os.path.exists(path)
    assert added == []


def test_changelog_commit_iteration_failure_writes_nothing(tmp_path):
    def failing_iter(tag):
        yield ("feat: x", "a1")
        raise RuntimeError("git failed")

    fake, path = _fake_stamper(tmp_path, [])
    fake.backend.get_commits_info_iter = failing_iter
    VersionControlStamper._generate_changelog(fake, "1.0.0", [])
    assert not os.path.exists(path)
