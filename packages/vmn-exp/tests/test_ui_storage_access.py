"""Capability probe of a store workspace (plan 11 §6.3)."""
import os

from vmn_exp.storage.registry import open_store
from vmn_exp.ui.storage_access import EDIT, READ, SERVER_AREA, probe_store


def _uri(tmp_path):
    return f"file://{tmp_path}/store"


def test_writable_store_reads_and_edits(tmp_path):
    probe = probe_store(_uri(tmp_path))
    assert probe.capabilities == [READ, EDIT]
    assert probe.warnings == []


def test_probe_key_lands_under_the_server_area_and_is_cleaned_up(tmp_path):
    probe_store(_uri(tmp_path))
    area_dir = tmp_path / "store" / SERVER_AREA
    leftovers = [p for _, _, files in os.walk(area_dir) for p in files]
    assert leftovers == []


class _NoWrites:
    def __init__(self, inner):
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def create_exclusive(self, *args):
        raise PermissionError("AccessDenied")


class _NoReads(_NoWrites):
    def list_apps(self):
        raise PermissionError("AccessDenied")


def test_failed_conditional_write_leaves_read_only(tmp_path):
    probe = probe_store(_uri(tmp_path), opener=lambda u, area: _NoWrites(open_store(u, area)))
    assert probe.capabilities == [READ]
    assert any("edit" in w for w in probe.warnings)


def test_unreadable_store_has_no_capabilities(tmp_path):
    probe = probe_store(_uri(tmp_path), opener=lambda u, area: _NoReads(open_store(u, area)))
    assert probe.capabilities == []


def test_delete_capable_role_warns_only_in_multi_tenancy(tmp_path):
    assert probe_store(_uri(tmp_path), tenancy="single").warnings == []
    multi = probe_store(_uri(tmp_path), tenancy="multi")
    assert multi.capabilities == [READ, EDIT]
    assert any("delete" in w for w in multi.warnings)


def test_capabilities_persist_with_the_workspace(tmp_path):
    from vmn_exp.ui.workspaces import WorkspaceManager

    manager = WorkspaceManager(str(tmp_path / "data"))
    manager.add_store("ws", _uri(tmp_path))
    manager.set_capabilities("ws", [READ, EDIT])
    again = WorkspaceManager(str(tmp_path / "data"))
    assert again.get("ws").capabilities == [READ, EDIT]
