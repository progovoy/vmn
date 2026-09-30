"""Conventional-commit parsing, release-mode mapping and small core fixes."""
from unittest import mock

import pytest
from version_stamp.core import logging as vmn_logging
from version_stamp.core import version_math
from version_stamp.core.changelog import group_commits, release_mode_for_commit
from version_stamp.core.version_math import parse_conventional_commit_message


def _mode(message):
    return release_mode_for_commit(parse_conventional_commit_message(message))


def test_footer_breaking_change_parses_as_footer():
    parsed = parse_conventional_commit_message(
        "feat: x\n\nsome body\n\nBREAKING CHANGE: y"
    )
    assert parsed["description"] == "x"
    assert parsed["body"] == "some body"
    assert "BREAKING CHANGE: y" in parsed["footer"]


@pytest.mark.parametrize(
    "message,expected",
    [
        ("feat: x\n\nsome body\n\nBREAKING CHANGE: y", "major"),
        ("feat: x\n\nBREAKING CHANGE: y", "major"),
        ("fix: x\n\nBREAKING-CHANGE: y", "major"),
        ("feat!: x", "major"),
        ("feat(ui)!: x", "major"),
        ("BREAKING CHANGE: x", "major"),
        ("feat: x", "minor"),
        ("fix: x", "patch"),
        ("micro: x", "hotfix"),
        ("docs: x", None),
        ("unknown: x", None),
    ],
)
def test_release_mode_for_commit(message, expected):
    assert _mode(message) == expected


def test_multiline_body_without_footer():
    message = "fix: x\n\nfirst line\nsecond line\n\nanother paragraph\n"
    parsed = parse_conventional_commit_message(message)
    assert parsed["description"] == "x"
    assert "first line\nsecond line" in parsed["body"]
    assert parsed["footer"] is None
    assert release_mode_for_commit(parsed) == "patch"


def test_changelog_description_excludes_body_and_footer_breaking():
    result = group_commits([("feat: x\n\nbody\n\nBREAKING CHANGE: y", "aaaaaaa")])
    assert [c["description"] for c in result["breaking"]] == ["x"]


def test_buildmetadata_warning_only_when_buildmetadata_is_duplicated(monkeypatch):
    logger = mock.Mock()
    monkeypatch.setattr(version_math, "VMN_LOGGER", logger)

    version_math.serialize_vmn_version("1.0.0-rc.1+build1")
    assert not logger.warning.called

    version_math.serialize_vmn_version("1.0.0+build1", buildmetadata="build2")
    assert logger.warning.call_count == 1
    assert "buildmetadata" in logger.warning.call_args[0][0]


def test_measure_runtime_decorator_pops_frame_on_exception():
    @vmn_logging.measure_runtime_decorator
    def boom():
        raise ValueError("x")

    vmn_logging.reset_runtime_context()
    with pytest.raises(ValueError):
        boom()
    assert vmn_logging.get_call_stack() == []
