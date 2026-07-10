#!/usr/bin/env python3
"""Workspace registry for vmn ui.

A workspace is an isolated source of vmn data: a git checkout (its own working
tree, .vmn/, lock and index) or a read-only S3 experiment store. Several
workspaces may be clones of the same remote — mutations in one never touch
another. The registry persists in ``<data_dir>/workspaces.yml``.
"""
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional

import yaml

REGISTRY_FILENAME = "workspaces.yml"


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

    def attach_path(self, name, path) -> Workspace:
        """Register an existing local checkout as a workspace."""
        if name in self._workspaces:
            raise WorkspaceError(f"Workspace '{name}' already exists")
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
        if name in self._workspaces:
            raise WorkspaceError(f"Workspace '{name}' already exists")
        ws = Workspace(
            name=name, kind="s3", bucket=bucket,
            prefix=prefix, endpoint_url=endpoint_url,
        )
        self._workspaces[name] = ws
        self._save()
        return ws

    def remove(self, name):
        if name not in self._workspaces:
            raise WorkspaceError(f"Workspace '{name}' not found")
        del self._workspaces[name]
        self._save()
