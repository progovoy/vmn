#!/usr/bin/env python3
"""Artifact helpers of an SDK run: log objects, text, figures and whole trees.

Each writes what it was given to a temporary file and hands it to
``log_artifact(path, name)`` — so the stored artifact, its log entry (path, size,
sha256) and the storage backends are exactly those of a plain file artifact.
*name* is the artifact's path inside the run: a relative ``a/b/c.txt``, never
absolute, never with ``..``.
"""
import json
import os
import tempfile

import yaml

from version_stamp.cli.snapshot_storage_files import (
    artifact_file_path,
    list_artifact_tree,
    valid_artifact_path,
)

_DICT_WRITERS = {
    ".json": lambda obj, f: json.dump(obj, f, indent=2, default=str),
    ".yaml": lambda obj, f: yaml.safe_dump(obj, f, sort_keys=False),
    ".yml": lambda obj, f: yaml.safe_dump(obj, f, sort_keys=False),
}


def checked_artifact_name(name):
    if not valid_artifact_path(name):
        raise ValueError(f"Invalid artifact name {name!r}: use a relative a/b/c path")
    return name


def _tree_names(local_dir, prefix):
    """``[(file path, artifact name)]`` of every file under *local_dir*."""
    return [
        (
            artifact_file_path(local_dir, a["name"]),
            checked_artifact_name(f"{prefix}/{a['name']}" if prefix else a["name"]),
        )
        for a in list_artifact_tree(local_dir)
    ]


def _write_text(path, write):
    with open(path, "w", encoding="utf-8") as f:
        write(f)


class RunArtifacts:
    """Mixed into :class:`~version_stamp.exp.run.Run`; needs ``log_artifact``."""

    def _log_produced(self, name, produce):
        """Log the file *produce(path)* writes, stored as artifact *name*."""
        checked_artifact_name(name)
        with tempfile.TemporaryDirectory(prefix="vmn-artifact-") as tmp:
            path = os.path.join(tmp, os.path.basename(name))
            produce(path)
            self.log_artifact(path, name=name)

    def log_dict(self, obj, name):
        """*obj* as JSON (``.json``) or YAML (``.yaml``/``.yml``), by *name*'s extension."""
        writer = _DICT_WRITERS.get(os.path.splitext(name)[1].lower())
        if writer is None:
            raise ValueError(f"log_dict needs a .json, .yaml or .yml name, got {name!r}")
        self._log_produced(name, lambda path: _write_text(path, lambda f: writer(obj, f)))

    def log_text(self, text, name):
        self._log_produced(name, lambda path: _write_text(path, lambda f: f.write(text)))

    def log_figure(self, figure, name, **savefig_kwargs):
        """A matplotlib-style figure, through its ``savefig`` (format from *name*).

        Duck-typed: nothing here imports matplotlib.
        """
        self._log_produced(name, lambda path: figure.savefig(path, **savefig_kwargs))

    def log_artifacts(self, local_dir, prefix=None):
        """Every file under *local_dir*, named by its path below it (under *prefix*).

        All names are checked before the first upload, so a bad one uploads nothing.
        """
        if not os.path.isdir(local_dir):
            raise FileNotFoundError(f"Not a directory: {local_dir}")
        prefix = checked_artifact_name(prefix.strip("/")) if prefix else None
        for path, name in _tree_names(local_dir, prefix):
            self.log_artifact(path, name=name)
