"""S3 record writes: ``metadata.yml`` is what makes a record visible, so it is
written last and deleted first.

A name is claimed with a separate ``.claim`` object under ``If-None-Match``;
only the winner uploads the body and then the metadata. A crash mid-create
leaves an invisible, still-claimed name; a crash mid-delete leaves invisible
leftovers — never a listed record with half its files.

A mixin over :class:`~version_stamp.store.s3_base.S3ObjectBase`.
"""
import yaml

from version_stamp.core.utils import redact_record_remotes, yaml_safe_load
from version_stamp.store.names import (
    METADATA_FILE,
    PATCH_FILES,
    apply_metadata_updates,
    safe_dep_name,
)
from version_stamp.store.s3_errors import S3DeleteRefused, is_taken

CLAIM_FILE = ".claim"
# The record format core writes (vmn-exp-sdk's S3 store writes its own).
RECORD_FORMAT_VERSION = 1
FORMAT_VERSION_KEY = "format_version"
DELETE_BATCH = 1000  # the most keys one DeleteObjects takes
UPDATE_ATTEMPTS = 20


class S3RecordWrites:
    def _stamped(self, metadata):
        """*metadata* with this store's format version unless it has one."""
        if FORMAT_VERSION_KEY in metadata:
            return metadata
        return dict(metadata, **{FORMAT_VERSION_KEY: RECORD_FORMAT_VERSION})

    def _put_patches(self, prefix, patches):
        for key, filename, _ in PATCH_FILES:
            if patches.get(key):
                self._put(f"{prefix}/{filename}", patches[key])

    def _put_record_body(self, prefix, patches):
        self._put_patches(prefix, patches)
        for dep_path, dep_patches in patches.get("deps", {}).items():
            self._put_patches(f"{prefix}/deps/{safe_dep_name(dep_path)}", dep_patches)

    def _put_metadata(self, prefix, metadata, **condition):
        body = yaml.dump(redact_record_remotes(self._stamped(metadata)), sort_keys=True)
        self._put(f"{prefix}/{METADATA_FILE}", body, **condition)

    def save(self, app_name, verstr, metadata, patches):
        prefix = self._record_prefix(app_name, verstr)
        self._put_record_body(prefix, patches)
        self._put_metadata(prefix, metadata)

    def create_exclusive(self, app_name, verstr, metadata, patches, claim_token=None):
        """Create the record only if *verstr* is free; True when created.

        The ``.claim`` object's body is *claim_token* (empty without one). A
        claim that carries the same non-empty token but has no metadata yet
        is this claimer's own crashed attempt, and is resumed; any other
        claim, and any existing metadata, means taken.
        """
        prefix = self._record_prefix(app_name, verstr)
        # A record written before claims existed has metadata but no claim.
        if self._head(f"{prefix}/{METADATA_FILE}"):
            return False
        if not self._claim(prefix, claim_token):
            return False
        self._put_record_body(prefix, patches)
        self._put_metadata(prefix, metadata)
        return True

    def _claim(self, prefix, claim_token):
        key = f"{prefix}/{CLAIM_FILE}"
        token = (claim_token or "").encode("utf-8")
        # The conditional PUT is the claim: exactly one writer wins it.
        if self._create(key, token):
            return True
        return bool(token) and self._get_or_raise(key) == token

    def delete(self, app_name, verstr):
        prefix = self._record_prefix(app_name, verstr)
        # First: from here on the record is invisible, whatever else fails.
        self._s3.delete_object(Bucket=self.bucket, Key=f"{prefix}/{METADATA_FILE}")
        self._delete_keys([o["Key"] for o in self._objects(prefix + "/")])

    def _delete_keys(self, keys):
        """Delete *keys*: batches of :data:`DELETE_BATCH`, sent concurrently."""
        batches = [keys[i : i + DELETE_BATCH] for i in range(0, len(keys), DELETE_BATCH)]
        self._map(self._delete_batch, batches)

    def _delete_batch(self, keys):
        resp = self._s3.delete_objects(
            Bucket=self.bucket,
            Delete={"Objects": [{"Key": key} for key in keys], "Quiet": True},
        )
        errors = resp.get("Errors") or []
        if errors:
            raise S3DeleteRefused(errors)

    def update_note(self, app_name, verstr, note):
        return self.update_metadata(app_name, verstr, {"note": note})

    def update_metadata(self, app_name, verstr, updates):
        """Rewrite only ``metadata.yml``, under its ETag: a concurrent edit
        makes this retry on the new content instead of being overwritten.
        False when the record does not exist."""
        prefix = self._record_prefix(app_name, verstr)
        for _ in range(UPDATE_ATTEMPTS):
            raw, etag = self._get_with_etag(f"{prefix}/{METADATA_FILE}")
            if raw is None:
                return False
            metadata = apply_metadata_updates(yaml_safe_load(raw), updates)
            try:
                self._put_metadata(prefix, metadata, IfMatch=etag)
                return True
            except Exception as e:
                if not is_taken(e):
                    raise
        raise RuntimeError(f"Could not update the metadata of {verstr}: too many writers")
