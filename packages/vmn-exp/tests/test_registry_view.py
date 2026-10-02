"""Tests for vmn_exp/registry/view.py (C4).

Three tests:
- model_state with aliases and statuses
- resolve_ref: alias / number / latest; deleted versions skipped; unknown alias errors
- registered_runs excludes deleted versions
"""
import pytest

from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.registry.store import ensure_model, register_version
from vmn_exp.registry.log import set_alias, set_version_status
from vmn_exp.registry.view import model_state, resolve_ref, registered_runs


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _storage(tmp_path):
    return LocalSnapshotStorage(str(tmp_path), area="runs")


def _run_ref(app="myapp", verstr="1.0.0"):
    return {"app": app, "verstr": verstr}


def _setup_resnet(storage):
    """Create resnet model with 3 versions, prod->v2, staging->v3, v1 deprecated."""
    ensure_model(storage, "resnet", description="Image classifier")
    v1 = register_version(storage, "resnet", _run_ref("myapp", "1.0.0"))
    v2 = register_version(storage, "resnet", _run_ref("myapp", "2.0.0"))
    v3 = register_version(storage, "resnet", _run_ref("myapp", "3.0.0"))
    set_alias(storage, "resnet", "prod", v2)
    set_alias(storage, "resnet", "staging", v3)
    set_version_status(storage, "resnet", v1, "deprecated")
    return v1, v2, v3


# ---------------------------------------------------------------------------
# 1. model_state returns header, versions with status/aliases, aliases, audit
# ---------------------------------------------------------------------------

def test_model_state_with_aliases_and_statuses(tmp_path):
    storage = _storage(tmp_path)
    v1, v2, v3 = _setup_resnet(storage)

    state = model_state(storage, "resnet")

    # Header present
    assert state["header"]["model"] == "resnet"
    assert state["header"]["description"] == "Image classifier"

    # versions list in order
    assert len(state["versions"]) == 3
    by_n = {v["n"]: v for v in state["versions"]}

    assert by_n[1]["status"] == "deprecated"
    assert by_n[1]["aliases"] == []
    assert by_n[1]["run_ref"] == _run_ref("myapp", "1.0.0")

    assert by_n[2]["status"] == "active"
    assert by_n[2]["aliases"] == ["prod"]
    assert by_n[2]["run_ref"] == _run_ref("myapp", "2.0.0")

    assert by_n[3]["status"] == "active"
    assert by_n[3]["aliases"] == ["staging"]
    assert by_n[3]["run_ref"] == _run_ref("myapp", "3.0.0")

    # aliases map
    assert state["aliases"] == {"prod": 2, "staging": 3}

    # audit is non-empty (status + alias entries)
    assert len(state["audit"]) >= 3


# ---------------------------------------------------------------------------
# 2. resolve_ref: alias / number / latest; deleted versions skipped; error cases
# ---------------------------------------------------------------------------

def test_resolve_ref_alias_number_latest_deleted_skipped(tmp_path):
    storage = _storage(tmp_path)
    ensure_model(storage, "resnet")
    v1 = register_version(storage, "resnet", _run_ref("myapp", "1.0.0"))
    v2 = register_version(storage, "resnet", _run_ref("myapp", "2.0.0"))
    v3 = register_version(storage, "resnet", _run_ref("myapp", "3.0.0"))

    set_alias(storage, "resnet", "prod", v2)
    # Delete v3 — must remove alias first (no alias points to v3)
    set_version_status(storage, "resnet", v3, "deleted")

    # Resolve by alias
    result = resolve_ref(storage, "resnet@prod")
    assert result["n"] == v2

    # Resolve by version number
    result = resolve_ref(storage, "resnet@2")
    assert result["n"] == v2

    # Resolve latest: v3 is deleted → v2 is latest non-deleted
    result = resolve_ref(storage, "resnet@latest")
    assert result["n"] == v2

    # Bare ref (no @) = latest
    result = resolve_ref(storage, "resnet")
    assert result["n"] == v2

    # Deleted version → KeyError
    with pytest.raises(KeyError, match="deleted"):
        resolve_ref(storage, "resnet@3")

    # Unknown alias → KeyError listing available aliases
    with pytest.raises(KeyError, match="prod"):
        resolve_ref(storage, "resnet@nosuchalias")


# ---------------------------------------------------------------------------
# 3. registered_runs excludes deleted versions
# ---------------------------------------------------------------------------

def test_registered_runs_excludes_deleted_versions(tmp_path):
    storage = _storage(tmp_path)

    # modelA: v1 (app1/1.0.0) and v2 (app1/2.0.0); v2 will be deleted
    ensure_model(storage, "modelA")
    register_version(storage, "modelA", _run_ref("app1", "1.0.0"))
    register_version(storage, "modelA", _run_ref("app1", "2.0.0"))
    set_version_status(storage, "modelA", 2, "deleted")

    # modelB: v1 (app2/3.0.0); not deleted
    ensure_model(storage, "modelB")
    register_version(storage, "modelB", _run_ref("app2", "3.0.0"))

    runs = registered_runs(storage)

    assert ("app1", "1.0.0") in runs
    assert ("app2", "3.0.0") in runs
    assert ("app1", "2.0.0") not in runs   # deleted version excluded
