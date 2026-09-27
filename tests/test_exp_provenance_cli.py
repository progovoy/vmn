"""Provenance: env one-liner, inputs block, env/packages diff, no-code refusals.

All pure-unit or fake-storage tests; no Docker required.
"""
import types
import pytest
from version_stamp.core.logging import init_stamp_logger


@pytest.fixture(autouse=True)
def _init_logger():
    """Initialize VMN_LOGGER so CLI helpers can log errors."""
    init_stamp_logger()


# ---------------------------------------------------------------------------
# Helpers / fake objects
# ---------------------------------------------------------------------------

def _summary(python="3.11.2", platform="Linux/x86_64", key_packages=None, cuda=None):
    s = {"python": python, "platform": platform}
    if key_packages:
        s["key_packages"] = key_packages
    if cuda:
        s["cuda"] = cuda
    return s


def _full_env(packages=None, hostname="some-host"):
    e = {
        "python": {"version": "3.11.2"},
        "platform": {"system": "Linux", "machine": "x86_64"},
        "hostname": hostname,
        "packages": packages or {},
    }
    return e


def _imported_meta(source_commit="abc1234"):
    return {
        "verstr": "0.0.0-mlflow.abc123def456",
        "code_verstr": "0.0.0-mlflow.abc123def456",
        "imported_from": {
            "tool": "mlflow",
            "run_id": "abc123def456",
            "experiment_id": "1",
            "experiment_name": "my-exp",
            "source_commit": source_commit,
            "artifact_uri": "s3://bucket/artifacts",
        },
        "name": "imported-run",
    }


class _FakeStorage:
    """Minimal duck-typed storage for provenance CLI tests."""

    def __init__(self, metadata, patches=None, log=None):
        self._meta = metadata
        self._patches = patches or {}
        self._log = log or []

    def load(self, app_name, verstr):
        return self._meta, self._patches

    def load_metadata(self, app_name, verstr):
        return self._meta

    def load_file(self, app_name, verstr, name):
        return None

    def list_snapshots(self, app_name):
        return [self._meta]

    def load_log_tail(self, app_name, verstr, tail=None):
        return self._log, len(self._log)


def _args(**kwargs):
    ns = types.SimpleNamespace(
        name="myapp",
        version=None,
        latest=False,
        json=False,
        full_log=False,
        output=None,
        tool=None,
        **kwargs,
    )
    return ns


# ===========================================================================
# 1. format_env_oneliner shows python, platform, key packages
# ===========================================================================

def test_show_prints_env_line():
    from vmn_exp.cli.provenance import format_env_oneliner

    summary = _summary(
        key_packages={"torch": "2.2.1"},
        cuda={"torch_cuda": "12.1"},
    )
    result = format_env_oneliner(summary)
    assert "3.11.2" in result
    assert "Linux/x86_64" in result
    assert "torch=2.2.1" in result


# ===========================================================================
# 2. format_inputs_lines renders each input name + uri
# ===========================================================================

def test_show_prints_inputs():
    from vmn_exp.cli.provenance import format_inputs_lines

    inputs = {
        "train": {
            "uri": "s3://bucket/train.csv",
            "digest": "sha256:abc",
            "kind": "dataset",
        }
    }
    lines = format_inputs_lines(inputs)
    combined = "\n".join(lines)
    assert "train" in combined
    assert "s3://bucket/train.csv" in combined


# ===========================================================================
# 3. experiment_row (used by show --json) already includes env + inputs
# ===========================================================================

def test_show_json_has_env_and_inputs():
    from vmn_exp.core.log import experiment_row

    env_summary = {"python": "3.11.2", "platform": "Linux/x86_64"}
    meta = {
        "verstr": "0.0.1-dev.abc.def",
        "env": env_summary,
        "imported_from": None,
    }
    log = [
        {
            "type": "input",
            "uri": "s3://x/y.csv",
            "name": "train",
            "digest": None,
            "kind": None,
            "ts": "2026-01-01T00:00:00Z",
        }
    ]
    row = experiment_row(None, meta, log)
    assert row["env"] == env_summary
    assert "train" in row["inputs"]
    assert row["inputs"]["train"]["uri"] == "s3://x/y.csv"


# ===========================================================================
# 4. env_diff detects a package version change
# ===========================================================================

def test_diff_shows_package_change():
    from vmn_exp.core.provenance import env_diff

    env_a = _full_env(packages={"torch": "2.2.1", "numpy": "1.26.0"})
    env_b = _full_env(packages={"torch": "2.3.1", "numpy": "1.26.0"})
    lines = env_diff(env_a, env_b)
    combined = "\n".join(lines)
    assert "torch" in combined
    assert "2.2.1" in combined
    assert "2.3.1" in combined
    # numpy unchanged — must NOT appear
    assert "numpy" not in combined


# ===========================================================================
# 5. env_diff caps output at 30 lines
# ===========================================================================

def test_diff_caps_at_30():
    from vmn_exp.core.provenance import env_diff

    pkgs_a = {f"pkg{i}": "1.0" for i in range(50)}
    pkgs_b = {f"pkg{i}": "2.0" for i in range(50)}
    lines = env_diff(_full_env(packages=pkgs_a), _full_env(packages=pkgs_b), cap=30)
    # At most 30 change lines + 1 "... N more" trailer
    assert len(lines) <= 31


# ===========================================================================
# 6. env_diff ignores hostname differences
# ===========================================================================

def test_diff_ignores_host():
    from vmn_exp.core.provenance import env_diff

    env_a = _full_env(hostname="machine-alpha")
    env_b = _full_env(hostname="machine-beta")
    lines = env_diff(env_a, env_b)
    combined = "\n".join(lines)
    assert "machine-alpha" not in combined
    assert "machine-beta" not in combined


# ===========================================================================
# 7. inputs_diff shows added / changed / removed inputs
# ===========================================================================

def test_diff_inputs_change():
    from vmn_exp.core.provenance import inputs_diff

    inputs_a = {
        "train": {"uri": "s3://bucket/v1.csv", "digest": None, "kind": None},
        "removed": {"uri": "s3://bucket/old.csv", "digest": None, "kind": None},
    }
    inputs_b = {
        "train": {"uri": "s3://bucket/v2.csv", "digest": None, "kind": None},
        "added": {"uri": "s3://bucket/new.csv", "digest": None, "kind": None},
    }
    lines = inputs_diff(inputs_a, inputs_b)
    combined = "\n".join(lines)
    assert "train" in combined
    # changed uri visible
    assert "v1" in combined or "v2" in combined
    # added key visible
    assert "added" in combined or "new.csv" in combined
    # removed key visible
    assert "removed" in combined or "old.csv" in combined


# ===========================================================================
# 8. experiment_diff: imported runs refuse code diff, show provenance message
# ===========================================================================

def test_diff_imported_no_code(monkeypatch, caplog):
    import logging
    from vmn_exp.cli import experiment as exp_mod

    meta = _imported_meta(source_commit="deadbeef123")
    storage = _FakeStorage(meta)

    bundles = [(meta, {}, []), (meta, {}, [])]
    monkeypatch.setattr(
        exp_mod, "_resolve_experiment_bundles", lambda *a, **kw: bundles
    )

    with caplog.at_level(logging.DEBUG, logger="vmn"):
        ret = exp_mod.experiment_diff(None, {}, storage, _args())

    assert ret != 0
    # Should mention the import source and/or no-code reason
    combined = caplog.text
    assert "mlflow" in combined.lower() or "imported" in combined.lower() or "no code" in combined.lower()


# ===========================================================================
# 9. experiment_restore: imported run refuses with commit hint
# ===========================================================================

def test_restore_imported_refuses_with_commit_hint(monkeypatch, caplog):
    import logging
    from vmn_exp.cli import experiment as exp_mod

    meta = _imported_meta(source_commit="deadbeef123")
    storage = _FakeStorage(meta)

    monkeypatch.setattr(
        exp_mod,
        "_resolve_experiment_version",
        lambda *a, **kw: ("0.0.0-mlflow.abc123def456", None),
    )

    with caplog.at_level(logging.DEBUG, logger="vmn"):
        ret = exp_mod.experiment_restore(None, {}, storage, _args())

    assert ret == 1
    # Should mention source commit as a hint or the tool name
    combined = caplog.text
    assert "deadbeef123" in combined or "mlflow" in combined.lower() or "no code" in combined.lower()


# ===========================================================================
# 10. experiment_export: imported run refuses (exit 1, no crash)
# ===========================================================================

def test_export_imported_refuses(monkeypatch, caplog):
    import logging
    from vmn_exp.cli import experiment as exp_mod

    meta = _imported_meta()
    storage = _FakeStorage(meta)

    monkeypatch.setattr(
        exp_mod,
        "_resolve_experiment_version",
        lambda *a, **kw: ("0.0.0-mlflow.abc123def456", None),
    )

    with caplog.at_level(logging.DEBUG, logger="vmn"):
        ret = exp_mod.experiment_export(None, {}, storage, _args())

    assert ret == 1
    combined = caplog.text
    assert "mlflow" in combined.lower() or "imported" in combined.lower() or "no code" in combined.lower()
