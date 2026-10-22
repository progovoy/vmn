"""Snapshot records never carry a remote URL's credentials: stripped when a
record is built, and redacted when an older record that has them is read."""
import os

import pytest
import yaml

from helpers import _bootstrap, _snapshot, extract_dev_verstr
from version_stamp.core.utils import redact_record_remotes, strip_url_credentials
from version_stamp.snapshot.local_store import LocalRecordStore
from version_stamp.snapshot.record import build_record_metadata

TOKEN = "glpat-SECRET"
TOKEN_URL = f"https://oauth2:{TOKEN}@gitlab.example.com/group/repo.git"
CLEAN_URL = "https://gitlab.example.com/group/repo.git"


@pytest.mark.parametrize(
    "url, expected",
    [
        (TOKEN_URL, CLEAN_URL),
        ("https://user@host/x.git", "https://host/x.git"),
        ("https://ghp_tok@github.com/o/r", "https://github.com/o/r"),
        ("http://u:p@host:8080/x", "http://host:8080/x"),
        ("https://u:p@ss@host/x", "https://host/x"),
        ("HTTPS://u:p@host/x", "HTTPS://host/x"),
        ("https://host/x.git", "https://host/x.git"),
        ("https://host/path@v1", "https://host/path@v1"),
        ("ssh://git@host/x.git", "ssh://git@host/x.git"),
        ("ssh://git:pw@host:22/x.git", "ssh://git@host:22/x.git"),
        ("git+ssh://me:pw@host/x", "git+ssh://me@host/x"),
        ("ssh://:pw@host/x", "ssh://host/x"),
        ("git@github.com:o/r.git", "git@github.com:o/r.git"),
        ("file:///srv/repo.git", "file:///srv/repo.git"),
        ("../relative/repo", "../relative/repo"),
        ("/abs/repo", "/abs/repo"),
        ("", ""),
        (None, None),
        (42, 42),
    ],
)
def test_strip_url_credentials(url, expected):
    assert strip_url_credentials(url) == expected


def test_redact_record_remotes_cleans_the_app_and_every_changeset():
    metadata = {
        "verstr": "v",
        "remote": TOKEN_URL,
        "changesets": {
            ".": {"hash": "a", "remote": TOKEN_URL},
            "../dep": {"hash": "b", "remote": "ssh://git:pw@host/dep"},
            "../plain": {"hash": "c"},
        },
    }
    redacted = redact_record_remotes(metadata)
    assert redacted["remote"] == CLEAN_URL
    assert redacted["changesets"]["."] == {"hash": "a", "remote": CLEAN_URL}
    assert redacted["changesets"]["../dep"]["remote"] == "ssh://git@host/dep"
    assert redacted["changesets"]["../plain"] == {"hash": "c"}
    assert metadata["remote"] == TOKEN_URL  # the input is not mutated
    assert metadata["changesets"]["."]["remote"] == TOKEN_URL


@pytest.mark.parametrize("value", [None, [], "x", {"verstr": "v"}, {"changesets": None}])
def test_redact_record_remotes_leaves_other_shapes_alone(value):
    assert redact_record_remotes(value) == value


class _Backend:
    active_branch = "main"

    def remote(self):
        return TOKEN_URL


class _Vcs:
    name = "app"
    backend = _Backend()


def test_build_record_metadata_strips_credentials():
    ver_info = {"stamping": {"app": {"changesets": {".": {"hash": "h", "remote": TOKEN_URL}}}}}
    metadata = build_record_metadata(
        _Vcs(), "0.0.1-dev.h.d", "0.0.1", "h", [], {}, ver_info,
    )
    assert metadata["remote"] == CLEAN_URL
    assert metadata["changesets"]["."]["remote"] == CLEAN_URL
    assert ver_info["stamping"]["app"]["changesets"]["."]["remote"] == TOKEN_URL


def _write_raw_record(store, verstr):
    store.save("app", verstr, {"verstr": verstr, "remote": "x", "timestamp": "t"}, {})
    path = os.path.join(store._record_dir("app", verstr), "metadata.yml")
    with open(path, "w") as f:
        yaml.dump(
            {
                "verstr": verstr,
                "timestamp": "t",
                "remote": TOKEN_URL,
                "changesets": {".": {"hash": "h", "remote": TOKEN_URL}},
            },
            f,
        )


def test_local_store_redacts_an_older_record_when_read(tmp_path):
    store = LocalRecordStore(str(tmp_path))
    _write_raw_record(store, "0.0.1-dev.a.b")

    loaded = [
        store.load_metadata("app", "0.0.1-dev.a.b"),
        store.load_record("app", "0.0.1-dev.a.b")[0],
        store.list_snapshots("app")[0],
    ]
    for metadata in loaded:
        assert TOKEN not in str(metadata)
        assert metadata["remote"] == CLEAN_URL


def test_snapshot_create_records_the_remote_without_credentials(app_layout, capfd, monkeypatch):
    from version_stamp.backends import git_history

    _bootstrap(app_layout)
    monkeypatch.setattr(git_history.GitHistoryMixin, "remote", lambda self: TOKEN_URL)
    app_layout.write_file_commit_and_push("test_repo_0", "work.txt", "committed\n")
    with open(os.path.join(app_layout.repo_path, "work.txt"), "w") as f:
        f.write("dirty\n")
    capfd.readouterr()

    assert _snapshot(app_layout.app_name) == 0
    verstr = extract_dev_verstr(capfd.readouterr().out)

    store = LocalRecordStore(app_layout.repo_path)
    path = os.path.join(store._record_dir(app_layout.app_name, verstr), "metadata.yml")
    with open(path) as f:
        raw = f.read()
    assert TOKEN not in raw
    assert yaml.safe_load(raw)["remote"] == CLEAN_URL
