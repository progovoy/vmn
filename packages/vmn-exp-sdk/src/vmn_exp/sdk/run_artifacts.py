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
import posixpath
import tempfile

import yaml

from vmn_exp.core.fold import fold_log, fold_outputs_dict
from vmn_exp.core.inputs import default_input_name
from vmn_exp.core.lineage import artifact_ref_uri
from vmn_exp.core.log import load_log
from vmn_exp.core.refs import resolve_experiment
from vmn_exp.storage.files import (
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


def store_produced(name, produce, save, inspect=None):
    """Write a file with *produce(tmp path)* and hand it to *save(path, name)*
    as artifact *name* — renamed to the basename of the path *produce* returns,
    when it returns one (a file that kept its own extension). Returns
    ``(artifact name, inspect(written file) or None)``."""
    checked_artifact_name(name)
    with tempfile.TemporaryDirectory(prefix="vmn-artifact-") as tmp:
        path = os.path.join(tmp, posixpath.basename(name))
        written = produce(path) or path
        stored = checked_artifact_name(
            posixpath.join(posixpath.dirname(name), os.path.basename(written))
        )
        save(written, stored)
        return stored, inspect(written) if inspect else None


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


def fetch_artifact(storage, app_name, ref, path):
    """``(verstr, output, local path)`` of artifact *path* logged by run *ref*;
    ValueError when *ref* resolves to nothing or logged no such artifact."""
    verstr, err = resolve_experiment(storage, app_name, ref)
    if err:
        raise ValueError(err)
    output = fold_outputs_dict(fold_log(load_log(storage, app_name, verstr))).get(path)
    if output is None:
        raise ValueError(f"Run {verstr} of {app_name} logged no artifact {path!r}")
    return verstr, output, storage.artifact_local_path(app_name, verstr, path)


class RunArtifacts:
    """Mixed into :class:`~vmn_exp.sdk.run.Run`; needs ``log_artifact``."""

    def use_artifact(self, ref, path, name=None, app_name=None):
        """Consume artifact *path* of run *ref* (verstr, prefix, ``@N``) and
        return a local path to it.

        Records an input named *name* (default: the path's basename) whose URI
        is ``vmn://<app>/<verstr>/<path>`` and whose digest is the artifact's
        sha256, so lineage links this run to its producer. *app_name*
        defaults to this run's app.
        """
        app_name = app_name or self.app_name
        verstr, output, local = fetch_artifact(self._storage, app_name, ref, path)
        self.log_input(
            artifact_ref_uri(app_name, verstr, path),
            name=name or default_input_name(path),
            digest=output["digest"],
            kind="artifact",
        )
        return local

    def log_dict(self, obj, name):
        """*obj* as JSON (``.json``) or YAML (``.yaml``/``.yml``), by *name*'s extension."""
        writer = _DICT_WRITERS.get(os.path.splitext(name)[1].lower())
        if writer is None:
            raise ValueError(f"log_dict needs a .json, .yaml or .yml name, got {name!r}")
        store_produced(
            name, lambda path: _write_text(path, lambda f: writer(obj, f)), self.log_artifact
        )

    def log_text(self, text, name):
        store_produced(
            name, lambda path: _write_text(path, lambda f: f.write(text)), self.log_artifact
        )

    def log_figure(self, figure, name, **savefig_kwargs):
        """A matplotlib-style figure, through its ``savefig`` (format from *name*).

        Duck-typed: nothing here imports matplotlib.
        """
        store_produced(
            name, lambda path: figure.savefig(path, **savefig_kwargs), self.log_artifact
        )

    def log_artifacts(self, local_dir, prefix=None):
        """Every file under *local_dir*, named by its path below it (under *prefix*).

        All names are checked before the first upload, so a bad one uploads nothing.
        """
        if not os.path.isdir(local_dir):
            raise FileNotFoundError(f"Not a directory: {local_dir}")
        prefix = checked_artifact_name(prefix.strip("/")) if prefix else None
        for path, name in _tree_names(local_dir, prefix):
            self.log_artifact(path, name=name)
