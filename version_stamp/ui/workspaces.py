#!/usr/bin/env python3
"""Workspace registry for vmn ui.

A workspace is an isolated source of vmn data: a git checkout (its own working
tree, .vmn/, lock and index) or a read-only S3 experiment store. Several
workspaces may be clones of the same remote — mutations in one never touch
another. The registry persists in ``<data_dir>/workspaces.yml``.

Clones created by the server live under ``<data_dir>/workspaces/<name>`` and
are server-owned: removing such a workspace also deletes its directory.
Attached checkouts belong to the user and are never touched on remove.
"""
import os
import re
import shutil
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

import yaml

REGISTRY_FILENAME = "workspaces.yml"

# Names become directory names and URL path segments.
_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass
class Workspace:
    name: str
    kind: str = "git"  # "git" | "s3"
    path: Optional[str] = None
    bucket: Optional[str] = None
    prefix: Optional[str] = None
    endpoint_url: Optional[str] = None

    def to_public_dict(self):
        d = {k: v for k, v in asdict(self).items() if v is not None}
        return d


class WorkspaceError(ValueError):
    pass


class WorkspaceManager:
    """Registry of workspaces, persisted under a server data directory."""

    def __init__(self, data_dir):
        self.data_dir = data_dir
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        self._registry_path = os.path.join(data_dir, REGISTRY_FILENAME)
        self._workspaces = self._load()

    # -- persistence --------------------------------------------------------

    def _load(self):
        try:
            with open(self._registry_path) as f:
                data = yaml.safe_load(f) or {}
        except OSError:
            return {}
        result = {}
        for entry in data.get("workspaces", []):
            ws = Workspace(**entry)
            result[ws.name] = ws
        return result

    def _save(self):
        data = {"workspaces": [ws.to_public_dict() for ws in self._workspaces.values()]}
        with open(self._registry_path, "w") as f:
            yaml.safe_dump(data, f, sort_keys=False)

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
        self._save()
        return ws

    def add_s3(self, name, bucket, prefix=None, endpoint_url=None) -> Workspace:
        """Register a read-only S3 experiment source."""
        self._validate_new_name(name)
        ws = Workspace(
            name=name, kind="s3", bucket=bucket,
            prefix=prefix, endpoint_url=endpoint_url,
        )
        self._workspaces[name] = ws
        self._save()
        return ws

    def remove(self, name):
        ws = self._workspaces.get(name)
        if ws is None:
            raise WorkspaceError(f"Workspace '{name}' not found")
        del self._workspaces[name]
        self._save()
        # Server-owned clones are deleted with their registration; attached
        # checkouts belong to the user and are left alone.
        if ws.path and self._is_managed(ws.path):
            shutil.rmtree(ws.path, ignore_errors=True)
