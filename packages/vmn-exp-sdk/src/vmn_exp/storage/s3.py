#!/usr/bin/env python3
"""The S3 snapshot/experiment backend.

Keys: ``<prefix>/<app key>/<safe verstr>/<file>``. The app key is the tag form
(``root/svc`` → ``root-svc``), which is injective because ``-`` is illegal in
app names. Legacy ``root_svc`` keys are rewritten by ``vmn-exp migrate``.

The backend is assembled from halves that each own one concern: client and key
helpers (:mod:`snapshot_storage_s3_base`), listings
(:mod:`snapshot_storage_s3_listing`), record writes
(:mod:`snapshot_storage_s3_records`) and logs (:mod:`snapshot_storage_s3_logs`).
"""
import hashlib
import os
import tempfile

from vmn_exp import _base
from vmn_exp._base import VMN_LOGGER
from vmn_exp.storage.base import SnapshotStorage
from vmn_exp.storage.files import (
    METADATA_FILE,
    PATCH_FILES,
    artifact_file_path,
    FILE_TREES,
    artifact_name_for,
    valid_artifact_path,
)
from vmn_exp.storage import host_dirs
from vmn_exp.storage.s3_base import sigv4_client
from vmn_exp.storage.s3_base import (  # noqa: F401  (re-exported)
    S3Base,
    app_key,
    error_code,
    is_missing,
)
from vmn_exp.storage.s3_listing import S3Listing
from vmn_exp.storage.s3_logs import S3Logs
from vmn_exp.storage.s3_records import S3Records

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

    def load_record(self, app_name, verstr):
        prefix = self._record_prefix(app_name, verstr)
        raw = self._get(f"{prefix}/{METADATA_FILE}")
        if raw is None:
            return None, None
        metadata = _base.yaml_safe_load(raw)
        if metadata.get("code"):
            return metadata, {}  # a run's code lives in its code object
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
        return (self.scheme, self.endpoint_url, self.bucket, self.prefix)

    def index_cache_path(self, app_name):
        return host_dirs.index_cache_path(self.cache_identity(), app_name)

    def save_file(self, app_name, verstr, filename, data):
        self._put(f"{self._record_prefix(app_name, verstr)}/{filename}", data)
        return True

    # -- artifacts ----------------------------------------------------------

    def save_artifact_file(self, app_name, verstr, src_path, name=None):
        name = artifact_name_for(src_path, name)
        key = f"{self._record_prefix(app_name, verstr)}/{name}"
        # Multipart and streamed: checkpoints can be many GB.
        self._s3.upload_file(src_path, self.bucket, key)
        return True

    def local_record_dir(self, app_name, verstr):
        return None

    def list_artifacts(self, app_name, verstr):
        base = f"{self._record_prefix(app_name, verstr)}/"
        found = [
            {"name": o["Key"][len(base) :], "size": o["Size"]}
            for tree in FILE_TREES
            for o in self._objects(f"{base}{tree}/")
            if valid_artifact_path(o["Key"][len(base) :])
        ]
        return sorted(found, key=lambda a: a["name"])

    def artifact_local_path(self, app_name, verstr, name):
        if not valid_artifact_path(name):
            return None
        key = f"{self._record_prefix(app_name, verstr)}/{name}"
        try:
            size = self._s3.head_object(Bucket=self.bucket, Key=key)["ContentLength"]
        except Exception:
            return None
        digest = hashlib.sha256(f"{self.bucket}/{key}".encode()).hexdigest()[:32]
        cache_dir = os.path.join(tempfile.gettempdir(), "vmn-artifact-cache", digest)
        path = artifact_file_path(cache_dir, name)
        if os.path.isfile(path) and os.path.getsize(path) == size:
            return path
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".part"
        self._s3.download_file(self.bucket, key, tmp)
        os.replace(tmp, path)
        return path

    def open_artifact(self, app_name, verstr, name):
        """``(chunks, size)`` streaming artifact *name* from S3, or None.

        Nothing is buffered to disk, so a multi-GB checkpoint starts arriving
        at once and leaves no cache behind.
        """
        if not valid_artifact_path(name):
            return None
        key = f"{self._record_prefix(app_name, verstr)}/{name}"
        try:
            resp = self._s3.get_object(Bucket=self.bucket, Key=key)
        except Exception as e:
            if is_missing(e):
                return None
            raise
        return resp["Body"].iter_chunks(_ARTIFACT_CHUNK), resp["ContentLength"]

    def presign_artifact(self, app_name, verstr, name, expires, disposition=None):
        """A presigned GET URL for artifact *name* (valid *expires* seconds),
        or None when it does not exist."""
        if not valid_artifact_path(name):
            return None
        key = f"{self._record_prefix(app_name, verstr)}/{name}"
        try:
            self._s3.head_object(Bucket=self.bucket, Key=key)
        except Exception as e:
            if is_missing(e):
                return None
            raise
        params = {"Bucket": self.bucket, "Key": key}
        if disposition:
            params["ResponseContentDisposition"] = disposition
        return sigv4_client(self.endpoint_url).generate_presigned_url(
            "get_object", Params=params, ExpiresIn=expires, HttpMethod="GET"
        )

    def artifact_uri(self, app_name, verstr, path):
        """Stable ``<scheme>://`` URI referencing artifact *path* for this record."""
        key = f"{self._record_prefix(app_name, verstr)}/{path}"
        return f"{self.scheme}://{self.bucket}/{key}"
