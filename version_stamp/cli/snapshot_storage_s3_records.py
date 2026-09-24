#!/usr/bin/env python3
"""S3 record writes: ``metadata.yml`` is what makes a record visible, so it is
written last and deleted first.

A name is claimed with a separate ``.claim`` object under ``If-None-Match``;
only the winner uploads the body and then the metadata. A crash mid-create
leaves an invisible, still-claimed name; a crash mid-delete leaves invisible
leftovers — never a listed record with half its files.
"""

import yaml

from version_stamp.cli.snapshot_storage_files import (
    METADATA_FILE,
    PATCH_FILES,
    safe_dep_name,
)
from version_stamp.cli.snapshot_storage_s3_base import (
    app_keys,
    is_taken,
    parallel_map,
)
from version_stamp.core import utils as core_utils

CLAIM_FILE = ".claim"
_DELETE_BATCH = 1000  # the most keys one DeleteObjects takes
_NOTE_ATTEMPTS = 20


class S3Records:
    def _put_patches(self, prefix, patches):
        for key, filename, _ in PATCH_FILES:
            if patches.get(key):
                self._put(f"{prefix}/{filename}", patches[key])

    def _put_record_body(self, prefix, patches):
        self._put_patches(prefix, patches)
        for dep_path, dp in patches.get("deps", {}).items():
            self._put_patches(f"{prefix}/deps/{safe_dep_name(dep_path)}", dp)

    def _put_metadata(self, prefix, metadata, **condition):
        self._put(
            f"{prefix}/{METADATA_FILE}",
            yaml.dump(metadata, sort_keys=True),
            **condition,
        )

    def save(self, app_name, verstr, metadata, patches):
        prefix = self._record_prefix(app_name, verstr)
        self._put_record_body(prefix, patches)
        self._put_metadata(prefix, metadata)

    def _has_metadata_anywhere(self, app_name, verstr):
        return any(
            self._head(
                f"{self._key_prefix(app_name, verstr, app_key=key)}/{METADATA_FILE}"
            )
            for key in app_keys(app_name)
        )

    def create_exclusive(self, app_name, verstr, metadata, patches):
        # A record written before claims existed has metadata but no claim.
        if self._has_metadata_anywhere(app_name, verstr):
            return False
        prefix = self._key_prefix(app_name, verstr)
        try:
            # The conditional PUT is the claim: exactly one writer wins it.
            self._put(f"{prefix}/{CLAIM_FILE}", b"", IfNoneMatch="*")
        except Exception as e:
            if is_taken(e):
                return False
            raise
        self._put_record_body(prefix, patches)
        self._put_metadata(prefix, metadata)
        return True

    def delete(self, app_name, verstr):
        prefix = self._record_prefix(app_name, verstr)
        # First: from here on the record is invisible, whatever else fails.
        self._s3.delete_object(Bucket=self.bucket, Key=f"{prefix}/{METADATA_FILE}")
        self._record_prefixes.pop((app_name, verstr), None)
        self._delete_keys([o["Key"] for o in self._objects(prefix + "/")])

    def _delete_keys(self, keys):
        """Delete *keys*: batches of :data:`_DELETE_BATCH`, sent concurrently."""
        batches = [
            keys[i : i + _DELETE_BATCH] for i in range(0, len(keys), _DELETE_BATCH)
        ]
        parallel_map(self._delete_batch, batches)

    def _delete_batch(self, keys):
        resp = self._s3.delete_objects(
            Bucket=self.bucket,
            Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
        )
        errors = resp.get("Errors") or []
        if errors:
            raise RuntimeError(
                f"S3 refused to delete {len(errors)} objects: {errors[0]}"
            )

    def update_note(self, app_name, verstr, note):
        """Rewrite only ``metadata.yml``, under its ETag: a concurrent edit
        makes this retry on the new content instead of being overwritten."""
        prefix = self._record_prefix(app_name, verstr)
        for _ in range(_NOTE_ATTEMPTS):
            raw, etag = self._get_with_etag(f"{prefix}/{METADATA_FILE}")
            if raw is None:
                return False
            metadata = core_utils.yaml_safe_load(raw)
            metadata["note"] = note
            try:
                self._put_metadata(prefix, metadata, IfMatch=etag)
                return True
            except Exception as e:
                if not is_taken(e):
                    raise
        raise RuntimeError(f"Could not update the note of {verstr}: too many writers")
