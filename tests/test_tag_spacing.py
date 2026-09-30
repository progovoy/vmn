"""GitOpsMixin.tag waits for a new tagger second only when a same-app tag
already carries the current one (taggerdate has second resolution)."""
import pytest

from island_helpers import _commit, _git, _out
from version_stamp.backends import git_ops
from version_stamp.backends.git import GitBackend


@pytest.fixture
def backend(tmp_path):
    _git(tmp_path, "init", "-q")
    _commit(tmp_path, "a.txt")
    return GitBackend(str(tmp_path))


@pytest.fixture
def sleeps(monkeypatch):
    calls = []
    monkeypatch.setattr(git_ops.time, "sleep", calls.append)
    return calls


def _taggerdate(repo, tag):
    return int(_out(repo, "for-each-ref", "--format=%(taggerdate:unix)", f"refs/tags/{tag}"))


def _freeze_clock_in_tagger_second_of(monkeypatch, backend, tag, fraction=0.25):
    now = _taggerdate(backend.repo_path, tag) + fraction
    monkeypatch.setattr(git_ops.time, "time", lambda: now)


def test_first_tag_of_an_app_does_not_sleep(backend, sleeps):
    backend.tag(["app_0.0.1"], ["msg"])

    assert sleeps == []


def test_same_app_tag_in_same_second_waits_for_next_second(backend, sleeps, monkeypatch):
    backend.tag(["app_0.0.1"], ["msg"])
    _freeze_clock_in_tagger_second_of(monkeypatch, backend, "app_0.0.1")

    backend.tag(["app_0.0.2"], ["msg"])

    assert sleeps == [pytest.approx(0.75)]


def test_root_app_tag_in_same_second_waits(backend, sleeps, monkeypatch):
    backend.tag(["root_app_1"], ["msg"])
    _freeze_clock_in_tagger_second_of(monkeypatch, backend, "root_app_1")

    backend.tag(["root_app_2"], ["msg"])

    assert len(sleeps) == 1


def test_other_app_tag_in_same_second_does_not_wait(backend, sleeps, monkeypatch):
    backend.tag(["app_0.0.1"], ["msg"])
    _freeze_clock_in_tagger_second_of(monkeypatch, backend, "app_0.0.1")

    backend.tag(["other_0.0.1", "root_app-svc_0.0.1"], ["msg", "msg"])

    assert sleeps == []


def test_back_to_back_tags_list_in_chronological_order(backend):
    tags = ["app_0.0.1", "app_0.0.2", "app_0.0.3"]
    for tag in tags:
        backend.tag([tag], ["msg"])

    dates = [_taggerdate(backend.repo_path, t) for t in tags]
    assert dates == sorted(set(dates))
    assert backend._list_tags("app_*") == tags
