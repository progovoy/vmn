"""Storage contract (local side): names-only listing, atomic claims, cheap
fingerprints, artifacts, atomic writes, no zombie resurrection, self-ignoring
storage dirs, fast YAML and patch dedupe."""

import os
import subprocess

import pytest
import yaml

from version_stamp.cli.snapshot import CachedSnapshotStorage, LocalSnapshotStorage
from version_stamp.core.logging import init_stamp_logger


@pytest.fixture(autouse=True)
def _init_logger():
    try:
        init_stamp_logger()
    except Exception:
        pass


@pytest.fixture
def st(tmp_path):
    return LocalSnapshotStorage(str(tmp_path), subdir="experiments")


def _meta(verstr, **kw):
    return dict({"verstr": verstr, "timestamp": "2026-01-01T00:00:00Z"}, **kw)


def test_list_verstrs_returns_names_without_parsing_metadata(st, monkeypatch):
    st.save("app", "1.0.0-dev.a+b", _meta("1.0.0-dev.a+b"), {})
    st.save("app", "1.0.0-dev.c", _meta("1.0.0-dev.c"), {})
    os.makedirs(os.path.join(st._snapshot_base_dir("app"), "no_metadata_dir"))

    def _boom(*a, **k):
        raise AssertionError("list_verstrs must not parse YAML")

    monkeypatch.setattr(yaml, "safe_load", _boom)
    monkeypatch.setattr(yaml, "load", _boom)
    assert sorted(st.list_verstrs("app")) == ["1.0.0-dev.a+b", "1.0.0-dev.c"]
    assert st.list_verstrs("missing") == []


def test_create_exclusive_claims_once(st):
    assert st.create_exclusive("app", "v1", _meta("v1"), {"working_tree": "x\n"})
    assert not st.create_exclusive("app", "v1", _meta("v1", note="second"), {})
    meta, patches = st.load("app", "v1")
    assert meta.get("note") is None
    assert patches["working_tree"] == "x\n"


def test_list_files_reports_top_level_files_with_size_and_mtime(st):
    st.save("app", "v1", _meta("v1"), {})
    st.append_log_entry("app", "v1", "w", {"timestamp": "t", "type": "note"})
    files = st.list_files("app")
    assert set(files) == {"v1"}
    assert {"metadata.yml", "log.w.jsonl"} <= set(files["v1"])
    size, mtime = files["v1"]["log.w.jsonl"]
    assert size > 0 and mtime > 0


def test_list_artifacts_and_local_path(st, tmp_path):
    st.save("app", "v1", _meta("v1"), {})
    src = tmp_path / "model.bin"
    src.write_bytes(b"12345")
    st.save_artifact_file("app", "v1", str(src))
    assert st.list_artifacts("app", "v1") == [{"name": "model.bin", "size": 5}]
    path = st.artifact_local_path("app", "v1", "model.bin")
    assert open(path, "rb").read() == b"12345"
    assert st.artifact_local_path("app", "v1", "missing.bin") is None
    for bad in ("../metadata.yml", "a/b", "..", ""):
        assert st.artifact_local_path("app", "v1", bad) is None
    assert st.list_artifacts("app", "nope") == []


def test_save_file_is_atomic_via_replace(st, monkeypatch):
    st.save("app", "v1", _meta("v1"), {})
    replaced = []
    real_replace = os.replace

    def spy(src, dst):
        replaced.append(os.path.basename(dst))
        return real_replace(src, dst)

    monkeypatch.setattr(os, "replace", spy)
    st.save_file("app", "v1", "run_state.yml", "state: running\n")
    st.save("app", "v2", _meta("v2"), {})
    assert "run_state.yml" in replaced
    assert "metadata.yml" in replaced
    assert st.load_file("app", "v1", "run_state.yml") == b"state: running\n"


def test_writes_to_a_deleted_experiment_do_not_resurrect_it(st):
    st.save("app", "v1", _meta("v1"), {})
    st.delete("app", "v1")
    assert st.save_file("app", "v1", "run_state.yml", "state: running\n") is False
    assert (
        st.append_log_entry("app", "v1", "w", {"timestamp": "t", "type": "note"})
        is False
    )
    assert not os.path.exists(st._snapshot_dir("app", "v1"))


def test_cached_writes_to_a_deleted_experiment_skip_remote(tmp_path):
    from unittest.mock import MagicMock

    local = LocalSnapshotStorage(str(tmp_path), subdir="experiments")
    remote = MagicMock()
    remote.exists.return_value = False  # pruned everywhere
    cached = CachedSnapshotStorage(local, remote)
    assert cached.save_file("app", "gone", "run_state.yml", "x") is False
    remote.save_file.assert_not_called()


def _git(cwd, *args):
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True, check=True
    ).stdout


def test_storage_dirs_ignore_themselves_at_any_depth(tmp_path):
    _git(tmp_path, "init", "-q")
    # the repo-level rule vmn writes at init only matches one level deep
    os.makedirs(tmp_path / ".vmn")
    (tmp_path / ".vmn" / ".gitignore").write_text("*/experiments/\n*/snapshots/\n")
    for subdir in ("experiments", "snapshots"):
        s = LocalSnapshotStorage(str(tmp_path), subdir=subdir)
        s.save("root/svc", "v1", _meta("v1"), {"working_tree": "p\n"})
        s.save("app", "v1", _meta("v1"), {})
    status = _git(tmp_path, "status", "--porcelain", "-uall")
    assert "experiments" not in status and "snapshots" not in status, status


def test_yaml_safe_load_uses_the_c_loader_when_available(monkeypatch):
    from version_stamp.core import utils

    seen = []
    real_load = yaml.load

    def spy(stream, Loader):
        seen.append(Loader)
        return real_load(stream, Loader=Loader)

    monkeypatch.setattr(yaml, "load", spy)
    assert utils.yaml_safe_load("a: 1\n") == {"a": 1}
    assert utils.yaml_safe_load(b"") is None
    expected = getattr(yaml, "CSafeLoader", yaml.SafeLoader)
    assert seen and all(loader is expected for loader in seen)


def test_listing_and_run_state_use_the_fast_loader(st, monkeypatch):
    from version_stamp.core import utils
    from version_stamp.core.experiment_status import load_run_state

    st.save("app", "v1", _meta("v1"), {})
    st.save_file("app", "v1", "run_state.yml", "state: running\n")
    calls = []
    real = utils.yaml_safe_load

    def spy(data):
        calls.append(1)
        return real(data)

    monkeypatch.setattr(utils, "yaml_safe_load", spy)
    monkeypatch.setattr(yaml, "safe_load", lambda *a, **k: 1 / 0)
    assert [m["verstr"] for m in st.list_snapshots("app")] == ["v1"]
    assert st.load("app", "v1")[0]["verstr"] == "v1"
    assert load_run_state(st, "app", "v1") == {"state": "running"}
    assert len(calls) >= 3


def test_identical_patches_of_same_code_runs_are_hard_linked(st):
    patches = {"working_tree": "diff\n" * 100, "untracked_files": b"\x00tar" * 50}
    st.save(
        "app",
        "1.0.0-dev.a.b",
        _meta("1.0.0-dev.a.b", code_verstr="1.0.0-dev.a.b"),
        patches,
    )
    st.save(
        "app",
        "1.0.0-dev.a.b.r2",
        _meta("1.0.0-dev.a.b.r2", code_verstr="1.0.0-dev.a.b"),
        dict(patches),
    )
    for name in ("working_tree.patch", "untracked_files.tar.gz"):
        a = os.stat(os.path.join(st._snapshot_dir("app", "1.0.0-dev.a.b"), name))
        b = os.stat(os.path.join(st._snapshot_dir("app", "1.0.0-dev.a.b.r2"), name))
        assert a.st_ino == b.st_ino, name
    assert st.load("app", "1.0.0-dev.a.b.r2")[1]["working_tree"] == "diff\n" * 100


def test_different_patches_are_not_linked(st):
    st.save("app", "c", _meta("c", code_verstr="c"), {"working_tree": "one\n"})
    st.save("app", "c.r2", _meta("c.r2", code_verstr="c"), {"working_tree": "two\n"})
    assert st.load("app", "c.r2")[1]["working_tree"] == "two\n"
    assert st.load("app", "c")[1]["working_tree"] == "one\n"


def test_resave_drops_patch_files_the_new_state_lacks(st):
    st.save("app", "v1", _meta("v1"), {"working_tree": "w\n", "untracked_files": b"t"})
    st.save("app", "v1", _meta("v1"), {"working_tree": "w2\n"})
    _, patches = st.load("app", "v1")
    assert patches == {"working_tree": "w2\n"}


def test_cached_storage_without_a_remote_lists_names_and_some_records(st):
    st.save("app", "v1", _meta("v1"), {})
    st.save("app", "v2", _meta("v2"), {})
    cached = CachedSnapshotStorage(st)
    assert cached.list_record_names("app") == st.list_record_names("app")
    assert cached.list_files("app", keys=["v1"]) == st.list_files("app", keys=["v1"])


def test_cached_storage_with_a_remote_merges_names(st):
    class Remote:
        def list_record_names(self, app_name):
            return {"v9": None}

        def list_files(self, app_name, keys=None):
            files = {"v9": {"metadata.yml": (1, 1, "etag")}}
            return {k: v for k, v in files.items() if keys is None or k in keys}

    st.save("app", "v1", _meta("v1"), {})
    cached = CachedSnapshotStorage(st, Remote())
    names = cached.list_record_names("app")
    assert names["v9"] is None and names["v1"] == st.list_record_names("app")["v1"]
    assert set(cached.list_files("app", keys=["v1", "v9", "v5"])) == {"v1", "v9"}
