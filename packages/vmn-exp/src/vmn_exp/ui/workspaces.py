#!/usr/bin/env python3
"""Workspace registry for vmn-exp ui.

A workspace is an isolated source of vmn data: a git checkout (its own working
tree, .vmn/, lock and index) or a read-only experiment ``store`` named by a
storage URI (``s3://``, ``gs://``, ``az://``, ``file://``, a plugin scheme). Several
workspaces may be clones of the same remote — mutations in one never touch
another. The registry persists through a :class:`WorkspaceRegistry`: by default
``<data_dir>/workspaces.yml``; a server with a DB keeps it in the control plane.

Clones created by the server live under ``<data_dir>/workspaces/<name>`` and
are server-owned: removing such a workspace also deletes its directory.
Attached checkouts belong to the user and are never touched on remove.
"""
import os
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import List, Optional

import yaml

REGISTRY_FILENAME = "workspaces.yml"

# Names become directory names and URL path segments.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass
class Workspace:
    name: str
    kind: str = "git"  # "git" | "store"
    path: Optional[str] = None
    store: Optional[str] = None  # a storage URI, for kind "store"
    downloads: Optional[str] = None  # "stream" | "redirect" (server config)
    reconcile_sec: Optional[int] = None

    def to_public_dict(self):
        d = {k: v for k, v in asdict(self).items() if v is not None}
        return d


class WorkspaceError(ValueError):
    pass


class WorkspaceRegistry:
    """Where the workspace list persists: ``load()`` all, ``save(ws)`` one,
    ``delete(name)`` one."""

    def load(self) -> List[Workspace]:
        raise NotImplementedError

    def save(self, ws, all_workspaces):
        raise NotImplementedError

    def delete(self, name, all_workspaces):
        raise NotImplementedError


class YamlWorkspaceRegistry(WorkspaceRegistry):
    """``<data_dir>/workspaces.yml`` — the standalone server's registry."""

    def __init__(self, path):
        self.path = path

    def load(self):
        try:
            with open(self.path) as f:
                data = yaml.safe_load(f) or {}
        except OSError:
            return []
        return [Workspace(**entry) for entry in data.get("workspaces", [])]

    def save(self, ws, all_workspaces):
        self._write(all_workspaces)

    def delete(self, name, all_workspaces):
        self._write(all_workspaces)

    def _write(self, all_workspaces):
        data = {"workspaces": [w.to_public_dict() for w in all_workspaces]}
        with open(self.path, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False)


class DbWorkspaceRegistry(WorkspaceRegistry):
    """The registry in a :class:`ControlPlaneStore` (kind ``workspace``)."""

    def __init__(self, control_plane):
        self.control_plane = control_plane

    def load(self):
        return [Workspace(**doc) for doc in self.control_plane.list("workspace")]

    def save(self, ws, all_workspaces):
        self.control_plane.put("workspace", ws.name, ws.to_public_dict())

    def delete(self, name, all_workspaces):
        self.control_plane.delete("workspace", name)


class WorkspaceManager:
    """Registry of workspaces, persisted under a server data directory."""

    def __init__(self, data_dir, registry=None):
        self.data_dir = data_dir
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self.registry = registry or YamlWorkspaceRegistry(
            os.path.join(data_dir, REGISTRY_FILENAME)
        )
        self._workspaces = {ws.name: ws for ws in self.registry.load()}

    def _save(self, ws):
        self.registry.save(ws, self.list())

    # -- registry operations ------------------------------------------------

    def list(self) -> List[Workspace]:
        return list(self._workspaces.values())

    def get(self, name) -> Optional[Workspace]:
        return self._workspaces.get(name)

    def _validate_new_name(self, name):
        if name in self._workspaces:
            raise WorkspaceError(f"Workspace '{name}' already exists")
        if not _NAME_RE.match(name or ""):
            raise WorkspaceError(
                f"Invalid workspace name {name!r} — use letters, digits, "
                "'.', '_' or '-' (no leading '.')"
            )

    def _managed_root(self):
        return os.path.join(self.data_dir, "workspaces")

    def _is_managed(self, path):
        return os.path.dirname(os.path.abspath(path)) == os.path.abspath(
            self._managed_root()
        )

    def clone_remote(self, name, remote, path=None) -> Workspace:
        """Clone a remote and register the checkout as a workspace.

        Without an explicit ``path`` the clone lands in the managed directory
        ``<data_dir>/workspaces/<name>``.
        """
        self._validate_new_name(name)
        if path is None:
            path = os.path.join(self._managed_root(), name)
        path = os.path.abspath(path)
        if os.path.isdir(path) and os.listdir(path):
            raise WorkspaceError(f"{path} already exists and is not empty")

        import git

        created_here = not os.path.exists(path)
        try:
            git.Repo.clone_from(remote, path)
        except Exception as e:
            # A partial clone would wedge every retry on the non-empty check.
            if created_here:
                shutil.rmtree(path, ignore_errors=True)
            raise WorkspaceError(f"Failed to clone {remote}: {e}")
        return self.attach_path(name, path)

    def attach_path(self, name, path) -> Workspace:
        """Register an existing local checkout as a workspace."""
        self._validate_new_name(name)
        path = os.path.abspath(path)
        if not os.path.isdir(path):
            raise WorkspaceError(f"Not a directory: {path}")
        if not (
            os.path.isdir(os.path.join(path, ".git"))
            or os.path.isdir(os.path.join(path, ".vmn"))
        ):
            raise WorkspaceError(
                f"{path} is not a vmn-managed checkout (no .git or .vmn)"
            )
        ws = Workspace(name=name, kind="git", path=path)
        self._workspaces[name] = ws
        self._save(ws)
        return ws

    def add_store(self, name, uri, downloads=None, reconcile_sec=None) -> Workspace:
        """Register a read-only experiment store named by a storage URI."""
        self._validate_new_name(name)
        ws = Workspace(name=name, kind="store", store=uri, downloads=downloads,
                       reconcile_sec=reconcile_sec)
        self._workspaces[name] = ws
        self._save(ws)
        return ws

    def remove(self, name):
        ws = self._workspaces.get(name)
        if ws is None:
            raise WorkspaceError(f"Workspace '{name}' not found")
        del self._workspaces[name]
        self.registry.delete(name, self.list())
        # Server-owned clones are deleted with their registration; attached
        # checkouts belong to the user and are left alone.
        if ws.path and self._is_managed(ws.path):
            shutil.rmtree(ws.path, ignore_errors=True)


def workspace_storage(ws):
    """A ``store`` workspace's experiment storage, else None."""
    if ws.kind != "store":
        return None
    from vmn_exp.storage.areas import RUNS
    from vmn_exp.storage.open import open_storage

    return open_storage(ws.store, area=RUNS)
