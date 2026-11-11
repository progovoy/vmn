"""The ``Run``'s plain records — params, notes, inputs, artifacts, models,
datasets, tags and similar-run search — mixed into ``Run``.

``set_intent`` stays in ``vmn_exp.sdk.run``: it reads ``sync_to_remote``,
which tests patch on that module.
"""
from vmn_exp._base import now_iso
from vmn_exp.core.inputs import create_input_entry
from vmn_exp.core.writer import (
    compute_artifact_info,
    create_log_entry,
    create_tags_entry,
    save_artifact,
)
from vmn_exp.sdk.context import owner_only
from vmn_exp.sdk.run_artifacts import checked_artifact_name
from vmn_exp.storage.files import user_artifact_path


class RunRecords:
    """Needs ``self._storage``, ``app_name``, ``id``, ``_exp_conf``,
    ``_detached``, ``_log_buffer``, ``_in_owner`` and ``_append`` from the
    ``Run`` it is mixed into."""

    def log_params(self, mapping):
        # A `params` entry, not a rewrite of the `create` entry: the log is
        # append-only, so readers fold later params in rather than see them move.
        self._append(create_log_entry("params", params=dict(mapping)))

    def log_note(self, text):
        self._append(create_log_entry("note", text=text))

    def log_input(self, uri, name=None, digest=None, kind=None):
        """Record that this run consumed the artifact at *uri*.

        *name* defaults to the URI basename (without extension). *digest* and
        *kind* are optional provenance hints (e.g. ``"sha256:..."`` and
        ``"dataset"``). Multiple calls are independent log entries; fold logic
        merges them latest-write-wins by name.
        """
        self._append(create_input_entry(uri, name=name, digest=digest, kind=kind, ts=now_iso()))

    @owner_only()
    def log_artifact(self, path, name=None):
        """Store the file at *path* as artifact *name* (a relative ``a/b/c``
        path; default: its basename), at ``artifacts/<name>`` in the run."""
        info = compute_artifact_info(path)
        if name is not None:
            info["path"] = user_artifact_path(checked_artifact_name(name))
        self._save_artifact_file(path, info["path"])
        self._append(create_log_entry("artifact", **info))

    def _save_artifact_file(self, path, name):
        if self._detached:
            return
        save_artifact(self._storage, self.app_name, self.id, path, name=name)

    def register_model(self, name, artifact_path=None, alias=None, description=None, *, storage=None):
        """Register this run as a model version in the registry.

        Convenience wrapper around :func:`~vmn_exp.sdk.models.register_model`
        that pre-fills *run*, *app_name* and *storage* from this run.

        Parameters
        ----------
        name:
            Model name.
        artifact_path:
            Record-relative path of the stored file (``artifacts/<name>``).
        alias:
            If given, immediately point this alias at the new version.
        description:
            Human-readable description of this version.
        storage:
            Override the storage; defaults to this run's storage.
        """
        from vmn_exp.sdk.models import register_model as _register_model

        return _register_model(
            name,
            run=self,
            artifact_path=artifact_path,
            alias=alias,
            description=description,
            storage=storage,
        )

    def use_model(self, ref, *, storage=None):
        """Record that this run used model *ref*; see :mod:`vmn_exp.sdk.usage`."""
        from vmn_exp.sdk.usage import use_model

        return use_model(ref, run=self, storage=storage)

    def use_dataset(self, ref, *, storage=None):
        """Record that this run used dataset *ref*; see :mod:`vmn_exp.sdk.usage`."""
        from vmn_exp.sdk.usage import use_dataset

        return use_dataset(ref, run=self, storage=storage)

    # Tags are mutable, and can be set on a finished run: each call appends a
    # `tags` entry, and readers fold them per key, last write wins.
    def set_tag(self, key, value):
        self.set_tags({key: value})

    def set_tags(self, tags):
        self._append(create_tags_entry(tags))

    def remove_tag(self, key):
        self._append(create_tags_entry(remove=[key]))

    def similar(self, top=10):
        """The past runs most like this one — its code, changes, params,
        inputs and intent so far: :func:`vmn_exp.sdk.reader.similar_runs`
        items, under the checkout's conf."""
        from vmn_exp.core.similar_search import find

        self._log_buffer.flush()
        return find(self._storage, self.app_name, self.id, self._exp_conf, top=top)
