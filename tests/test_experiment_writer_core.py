"""The write-side experiment core shared by the CLI and the ``version_stamp.exp`` SDK.

Everything here is exercised against a fake, duck-typed storage: the point of
``core.experiment_writer`` is that it knows how to shape an experiment record
without knowing anything about git, argparse or S3.
"""
import hashlib
import os

import pytest
import yaml

from version_stamp.core.experiment_status import RUN_STATE_FILE
from version_stamp.core.experiment_writer import (
    allocate_run_verstr,
    append_to_log,
    attach_parent,
    compute_artifact_info,
    create_log_entry,
    get_repo_lock,
    get_writer_id,
    merge_conf_into_params,
    save_artifact,
    save_log,
    save_run_state,
)


class _FakeStorage:
    """The duck-typed storage surface the writer core actually uses."""

    def __init__(self, snapshots=None):
        self.files = {}
        self.log_entries = []
        self.artifacts = []
        self._snapshots = snapshots or []

    def save_file(self, app_name, verstr, name, content):
        self.files[(app_name, verstr, name)] = content

    def load_file(self, app_name, verstr, name):
        return self.files.get((app_name, verstr, name))

    def append_log_entry(self, app_name, verstr, writer_id, entry):
        self.log_entries.append((app_name, verstr, writer_id, entry))

    def save_artifact_file(self, app_name, verstr, src_path):
        self.artifacts.append((app_name, verstr, src_path))

    def load_merged_log(self, app_name, verstr):
        return [e[3] for e in self.log_entries]

    def list_snapshots(self, app_name):
        return self._snapshots

    def exists(self, app_name, verstr):
        return any(m["verstr"] == verstr for m in self._snapshots)


@pytest.fixture(autouse=True)
def _clean_writer_id(monkeypatch):
    """The writer id is a process-lifetime cache; no test may inherit it."""
    from version_stamp.core import experiment_writer

    experiment_writer._WRITER_ID = None
    monkeypatch.delenv("VMN_WRITER_ID", raising=False)
    yield
    experiment_writer._WRITER_ID = None


# ---------------------------------------------------------------------------
# log entries
# ---------------------------------------------------------------------------


def test_create_log_entry_stamps_type_and_an_iso_timestamp():
    entry = create_log_entry("metrics", values={"loss": 0.5})

    assert entry["type"] == "metrics"
    assert entry["values"] == {"loss": 0.5}
    assert entry["timestamp"].endswith("Z")


def test_append_to_log_writes_through_the_per_writer_jsonl(monkeypatch):
    monkeypatch.setenv("VMN_WRITER_ID", "pod-7")
    storage = _FakeStorage()

    append_to_log(storage, "app", "0.0.1", {"type": "note", "text": "hi"})

    assert storage.log_entries == [("app", "0.0.1", "pod-7", {"type": "note", "text": "hi"})]


def test_save_log_dumps_the_whole_log_as_yaml():
    storage = _FakeStorage()
    log = [{"type": "create", "note": "first"}]

    save_log(storage, "app", "0.0.1", log)

    assert yaml.safe_load(storage.load_file("app", "0.0.1", "log.yml")) == log


# ---------------------------------------------------------------------------
# run state
# ---------------------------------------------------------------------------


def test_save_run_state_applies_updates_in_place_and_publishes():
    storage = _FakeStorage()
    state = {"state": "running", "exit_code": None}

    save_run_state(storage, "app", "0.0.1", state, state="finished", exit_code=3)

    assert state == {"state": "finished", "exit_code": 3}
    published = yaml.safe_load(storage.load_file("app", "0.0.1", RUN_STATE_FILE))
    assert published == {"state": "finished", "exit_code": 3}


def test_save_run_state_without_updates_republishes_the_current_state():
    storage = _FakeStorage()
    state = {"state": "running"}

    save_run_state(storage, "app", "0.0.1", state)

    assert yaml.safe_load(storage.load_file("app", "0.0.1", RUN_STATE_FILE)) == state


# ---------------------------------------------------------------------------
# artifacts
# ---------------------------------------------------------------------------


def test_compute_artifact_info_reports_basename_size_and_sha256(tmp_path):
    path = tmp_path / "model.bin"
    path.write_bytes(b"weights")

    info = compute_artifact_info(str(path))

    assert info == {
        "path": "model.bin",
        "size": 7,
        "sha256": hashlib.sha256(b"weights").hexdigest(),
    }


def test_save_artifact_delegates_to_the_storage(tmp_path):
    storage = _FakeStorage()
    path = tmp_path / "model.bin"
    path.write_bytes(b"x")

    save_artifact(storage, "app", "0.0.1", str(path))

    assert storage.artifacts == [("app", "0.0.1", str(path))]


# ---------------------------------------------------------------------------
# writer id
# ---------------------------------------------------------------------------


def test_get_writer_id_prefers_the_env_over_the_conf(monkeypatch):
    monkeypatch.setenv("VMN_WRITER_ID", "from-env")

    assert get_writer_id(conf_writer_id="from-conf") == "from-env"


def test_get_writer_id_falls_back_to_conf_then_hostname_env(monkeypatch):
    monkeypatch.setenv("HOSTNAME", "host-env")

    assert get_writer_id(conf_writer_id="from-conf") == "from-conf"


def test_get_writer_id_falls_back_to_the_hostname_env(monkeypatch):
    monkeypatch.setenv("HOSTNAME", "host-env")

    assert get_writer_id() == "host-env"


def test_get_writer_id_falls_back_to_the_real_hostname(monkeypatch):
    import socket

    monkeypatch.delenv("HOSTNAME", raising=False)

    assert get_writer_id() == socket.gethostname()


def test_get_writer_id_is_cached_for_the_process(monkeypatch):
    monkeypatch.setenv("VMN_WRITER_ID", "first")
    assert get_writer_id() == "first"

    monkeypatch.setenv("VMN_WRITER_ID", "second")
    assert get_writer_id() == "first"


# ---------------------------------------------------------------------------
# the repo lock
# ---------------------------------------------------------------------------


def test_get_repo_lock_defaults_to_the_repo_dot_vmn_lock(monkeypatch, tmp_path):
    monkeypatch.delenv("VMN_LOCK_FILE_PATH", raising=False)

    lock = get_repo_lock(str(tmp_path))

    assert lock.lock_file == os.path.join(str(tmp_path), ".vmn", "vmn.lock")


def test_get_repo_lock_honours_the_lock_file_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv("VMN_LOCK_FILE_PATH", str(tmp_path / "shared.lock"))

    assert get_repo_lock("/somewhere/else").lock_file == str(tmp_path / "shared.lock")


# ---------------------------------------------------------------------------
# conf merging
# ---------------------------------------------------------------------------


class _Vcs:
    def __init__(self, experiment=None, snapshot_storage=None):
        self.experiment = experiment
        self.snapshot_storage = snapshot_storage


def test_merge_conf_into_params_fills_unset_and_default_valued_keys():
    vcs = _Vcs(experiment={"storage": {"backend": "s3", "bucket": "b", "prefix": "p"}})
    params = {"backend": "local", "bucket": None, "prefix": "vmn-experiments"}

    merge_conf_into_params(vcs, params)

    assert params == {"backend": "s3", "bucket": "b", "prefix": "p"}


def test_merge_conf_into_params_lets_explicit_cli_values_win():
    vcs = _Vcs(experiment={"storage": {"bucket": "from-conf"}})
    params = {"bucket": "from-cli"}

    merge_conf_into_params(vcs, params)

    assert params["bucket"] == "from-cli"


def test_merge_conf_into_params_falls_back_to_snapshot_storage_conf():
    vcs = _Vcs(snapshot_storage={"backend": "s3", "bucket": "snap-bucket"})
    params = {"backend": "local", "bucket": None}

    merge_conf_into_params(vcs, params)

    assert params == {"backend": "s3", "bucket": "snap-bucket"}


def test_merge_conf_into_params_tolerates_a_vcs_without_conf():
    params = {"backend": "local"}

    merge_conf_into_params(None, params)

    assert params == {"backend": "local"}


# ---------------------------------------------------------------------------
# parents
# ---------------------------------------------------------------------------


def test_attach_parent_records_the_launching_experiment():
    metadata = {"verstr": "0.0.1-dev.aaaaaaa.bbbbbbb"}

    attach_parent(metadata, "0.0.1-dev.ccccccc.ddddddd")

    assert metadata["parent"] == "0.0.1-dev.ccccccc.ddddddd"


def test_attach_parent_never_makes_a_run_its_own_parent():
    metadata = {"verstr": "0.0.1-dev.aaaaaaa.bbbbbbb"}

    attach_parent(metadata, metadata["verstr"])
    attach_parent(metadata, None)

    assert "parent" not in metadata


# ---------------------------------------------------------------------------
# verstr allocation
# ---------------------------------------------------------------------------


def _meta(verstr):
    return {"verstr": verstr}


def test_allocate_run_verstr_uses_the_code_verstr_when_it_is_free():
    storage = _FakeStorage()

    assert allocate_run_verstr(storage, "app", "0.0.1-dev.aaa.bbb") == "0.0.1-dev.aaa.bbb"


def test_allocate_run_verstr_increments_the_run_suffix():
    storage = _FakeStorage(
        [_meta("0.0.1-dev.aaa.bbb"), _meta("0.0.1-dev.aaa.bbb.r2")]
    )

    assert (
        allocate_run_verstr(storage, "app", "0.0.1-dev.aaa.bbb")
        == "0.0.1-dev.aaa.bbb.r3"
    )


def test_allocate_run_verstr_uses_a_writer_unique_suffix_in_k8s_mode(monkeypatch):
    monkeypatch.setenv("VMN_WRITER_ID", "pod-7")
    storage = _FakeStorage()

    assert (
        allocate_run_verstr(storage, "app", "0.0.1-dev.aaa.bbb")
        == "0.0.1-dev.aaa.bbb.pod-7"
    )


def test_allocate_run_verstr_disambiguates_a_taken_writer_suffix(monkeypatch):
    monkeypatch.setenv("VMN_WRITER_ID", "pod-7")
    storage = _FakeStorage([_meta("0.0.1-dev.aaa.bbb.pod-7")])

    assert (
        allocate_run_verstr(storage, "app", "0.0.1-dev.aaa.bbb")
        == "0.0.1-dev.aaa.bbb.pod-7.2"
    )


# ---------------------------------------------------------------------------
# layering
# ---------------------------------------------------------------------------


def test_experiment_writer_does_not_import_upward():
    """The whole point: the write core is liftable without the CLI."""
    import pathlib

    source = (
        pathlib.Path(__file__).resolve().parent.parent
        / "version_stamp"
        / "core"
        / "experiment_writer.py"
    ).read_text()

    offenders = [
        line
        for line in source.splitlines()
        if line.startswith(("import ", "from "))
        and any(
            f"version_stamp.{pkg}" in line for pkg in ("cli", "ui", "exp", "stamping")
        )
    ]
    assert offenders == []


def test_exp_run_takes_only_the_documented_names_from_the_cli():
    """The SDK gets its record-shaping helpers from core, not from cli.

    What is left is the irreducible remainder: creating a record needs the
    storage factory and parent resolution, which still live in
    ``version_stamp/cli/experiment.py``. Checked across the whole ``exp``
    package (run creation lives in ``exp/create.py``). Pin the list so it can
    only shrink.
    """
    import ast
    import pathlib

    exp_dir = pathlib.Path(__file__).resolve().parent.parent / "version_stamp" / "exp"
    from_cli = {
        alias.name
        for path in exp_dir.glob("*.py")
        for node in ast.walk(ast.parse(path.read_text()))
        if isinstance(node, ast.ImportFrom)
        and (node.module or "").startswith("version_stamp.cli.experiment")
        for alias in node.names
    }
    assert from_cli == {
        "_get_experiment_storage",
        "_resolve_parent",
    }
