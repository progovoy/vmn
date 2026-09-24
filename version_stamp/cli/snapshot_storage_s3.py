#!/usr/bin/env python3
"""The S3 snapshot/experiment backend.

Keys: ``<prefix>/<app key>/<safe verstr>/<file>``. The app key is the tag form
(``root/svc`` → ``root-svc``), which is injective because ``-`` is illegal in
app names; reads fall back to the legacy ``root_svc`` form, which was not.

The backend is assembled from halves that each own one concern: client and key
helpers (:mod:`snapshot_storage_s3_base`), listings
(:mod:`snapshot_storage_s3_listing`), record writes
(:mod:`snapshot_storage_s3_records`) and logs (:mod:`snapshot_storage_s3_logs`).
"""
import hashlib
import os
import tempfile

from version_stamp.cli.snapshot_storage import SnapshotStorage
from version_stamp.cli.snapshot_storage_files import (
    METADATA_FILE,
    PATCH_FILES,
    valid_artifact_name,
)
from version_stamp.cli.snapshot_storage_s3_base import (  # noqa: F401  (re-exported)
    S3Base,
    app_keys,
    error_code,
    is_missing,
)
from version_stamp.cli.snapshot_storage_s3_listing import S3Listing
from version_stamp.cli.snapshot_storage_s3_logs import S3Logs
from version_stamp.cli.snapshot_storage_s3_records import S3Records
from version_stamp.core import utils as core_utils
from version_stamp.core.logging import VMN_LOGGER

_ARTIFACT_CHUNK = 1 << 20


class S3SnapshotStorage(S3Listing, S3Records, S3Logs, S3Base, SnapshotStorage):
    def exists(self, app_name, verstr):
        try:
            prefix = self._record_prefix(app_name, verstr)
        except ValueError:
            return False  # not a record name, so certainly no record
        return self._head(f"{prefix}/{METADATA_FILE}")

    def _get_patches(self, prefix):
        patches = {}
        for key, filename, binary in PATCH_FILES:
            data = self._get(f"{prefix}/{filename}")
            if data:
                patches[key] = data if binary else data.decode("utf-8")
        return patches

    def load(self, app_name, verstr):
        prefix = self._record_prefix(app_name, verstr)
        raw = self._get(f"{prefix}/{METADATA_FILE}")
        if raw is None:
            return None, None
        metadata = core_utils.yaml_safe_load(raw)
        patches = self._get_patches(prefix)

        dep_prefix = f"{prefix}/deps/"
        dep_patches = {}
        try:
            for cp in self._common_prefixes(dep_prefix):
                dp = self._get_patches(cp.rstrip("/"))
                if dp:
                    dep_patches[cp[len(dep_prefix) :].rstrip("/")] = dp
        except Exception:
            VMN_LOGGER.debug("Failed to list S3 dep patches", exc_info=True)
        if dep_patches:
            patches["deps"] = dep_patches
        return metadata, patches

    def load_file(self, app_name, verstr, filename):
        return self._get(f"{self._record_prefix(app_name, verstr)}/{filename}")

    def direct_files(self):
        return self

    def read_file_from(self, app_name, verstr, filename, offset):
        """A ranged GET: a grown log costs its new bytes, not the whole object."""
        if not offset:
            return self.load_file(app_name, verstr, filename)
        key = f"{self._record_prefix(app_name, verstr)}/{filename}"
        try:
            resp = self._s3.get_object(
                Bucket=self.bucket, Key=key, Range=f"bytes={offset}-"
            )
            return resp["Body"].read()
        except Exception as e:
            if error_code(e) in ("416", "InvalidRange"):
                return b""  # nothing past offset
            if not is_missing(e):
                VMN_LOGGER.debug(f"S3 error reading {key}", exc_info=True)
            return None

    def is_remote(self):
        return True

    def cache_identity(self):
        return ("s3", self.endpoint_url, self.bucket, self.prefix)

    def save_file(self, app_name, verstr, filename, data):
        self._put(f"{self._record_prefix(app_name, verstr)}/{filename}", data)
        return True

    # -- artifacts ----------------------------------------------------------

    def save_artifact_file(self, app_name, verstr, src_path):
        key = (
            f"{self._record_prefix(app_name, verstr)}/artifacts/"
            f"{os.path.basename(src_path)}"
        )
        # Multipart and streamed: checkpoints can be many GB.
        self._s3.upload_file(src_path, self.bucket, key)
        return True

    def list_artifact_files(self, app_name, verstr):
        return None

    def list_artifacts(self, app_name, verstr):
        prefix = f"{self._record_prefix(app_name, verstr)}/artifacts/"
        found = [
            {"name": o["Key"][len(prefix) :], "size": o["Size"]}
            for o in self._objects(prefix)
            if "/" not in o["Key"][len(prefix) :]
        ]
        return sorted(found, key=lambda a: a["name"])

    def artifact_local_path(self, app_name, verstr, name):
        if not valid_artifact_name(name):
            return None
        key = f"{self._record_prefix(app_name, verstr)}/artifacts/{name}"
        try:
            size = self._s3.head_object(Bucket=self.bucket, Key=key)["ContentLength"]
        except Exception:
            return None
        digest = hashlib.sha256(f"{self.bucket}/{key}".encode()).hexdigest()[:32]
        cache_dir = os.path.join(tempfile.gettempdir(), "vmn-artifact-cache", digest)
        path = os.path.join(cache_dir, name)
        if os.path.isfile(path) and os.path.getsize(path) == size:
            return path
        os.makedirs(cache_dir, exist_ok=True)
        tmp = path + ".part"
        self._s3.download_file(self.bucket, key, tmp)
        os.replace(tmp, path)
        return path

    def open_artifact(self, app_name, verstr, name):
        """``(chunks, size)`` streaming artifact *name* from S3, or None.

        Nothing is buffered to disk, so a multi-GB checkpoint starts arriving
        at once and leaves no cache behind.
        """
        if not valid_artifact_name(name):
            return None
        key = f"{self._record_prefix(app_name, verstr)}/artifacts/{name}"
        try:
            resp = self._s3.get_object(Bucket=self.bucket, Key=key)
        except Exception as e:
            if is_missing(e):
                return None
            raise
        return resp["Body"].iter_chunks(_ARTIFACT_CHUNK), resp["ContentLength"]
