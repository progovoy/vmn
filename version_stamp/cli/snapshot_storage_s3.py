#!/usr/bin/env python3
"""The S3 snapshot/experiment backend.

Keys: ``<prefix>/<app key>/<safe verstr>/<file>``. The app key is the tag form
(``root/svc`` → ``root-svc``), which is injective because ``-`` is illegal in
app names; reads fall back to the legacy ``root_svc`` form, which was not.

A writer's log is ``log.<w>.jsonl`` plus segments ``log.<w>@<seq>.jsonl``: a
local-first host ships each sync's new lines as a new segment (re-uploading a
growing log every sync is quadratic), while a direct append here rewrites
``log.<w>.jsonl`` under an ETag precondition so a concurrent append retries.
"""
import hashlib
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor

import yaml

from version_stamp.cli.snapshot_storage import SnapshotStorage
from version_stamp.cli.snapshot_storage_files import (
    LEGACY_LOG_FILE,
    METADATA_FILE,
    PATCH_FILES,
    checked_app_path,
    flatten_logs,
    group_log_names,
    is_log_file,
    log_object_name,
    log_sizes_of,
    log_writer_and_seq,
    parse_jsonl,
    safe_dep_name,
    safe_verstr,
    unsafe_verstr,
    valid_artifact_name,
)
from version_stamp.core import utils as core_utils
from version_stamp.core.logging import VMN_LOGGER

_LIST_WORKERS = 16
_MISSING_CODES = ("404", "NoSuchKey", "NotFound")
_TAKEN_CODES = ("412", "PreconditionFailed", "409", "ConditionalRequestConflict")
_APPEND_ATTEMPTS = 20


def _error_code(exc):
    return ((getattr(exc, "response", None) or {}).get("Error") or {}).get("Code")


def _is_missing(exc):
    """Whether *exc* says the object does not exist (not an access/transport error)."""
    return _error_code(exc) in _MISSING_CODES or "NoSuchKey" in str(exc)


def _wanted(writer, writers):
    return writers is None or writer in writers


def app_keys(app_name):
    """The app's key segment, then the legacy one when it differs."""
    new, legacy = app_name.replace("/", "-"), app_name.replace("/", "_")
    return [new] if new == legacy else [new, legacy]


class S3SnapshotStorage(SnapshotStorage):
    def __init__(self, bucket, prefix="vmn-snapshots", endpoint_url=None):
        try:
            import boto3
        except ImportError:
            raise ImportError(
                "boto3 is required for S3 snapshot storage. "
                "Install it with: pip install boto3"
            )
        self.bucket = bucket
        self.prefix = prefix
        self.endpoint_url = endpoint_url
        client_kwargs = {}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        self._s3 = boto3.client("s3", **client_kwargs)
        self._record_prefixes = {}
        self._app_prefixes = {}

    # -- key helpers --------------------------------------------------------

    def _key_prefix(self, app_name, verstr=None, app_key=None):
        base = f"{self.prefix}/{app_key or app_keys(checked_app_path(app_name))[0]}"
        return f"{base}/{safe_verstr(verstr)}" if verstr else base

    def _record_prefix(self, app_name, verstr):
        """Where *verstr*'s objects live: the current key, or the legacy one
        for a record written before the encoding changed."""
        keys = app_keys(app_name)
        if len(keys) == 1:
            return self._key_prefix(app_name, verstr)
        cached = self._record_prefixes.get((app_name, verstr))
        if cached:
            return cached
        for key in keys:
            prefix = self._key_prefix(app_name, verstr, app_key=key)
            if self._head(f"{prefix}/{METADATA_FILE}"):
                self._record_prefixes[(app_name, verstr)] = prefix
                return prefix
        return self._key_prefix(app_name, verstr)

    def _app_prefix_with_data(self, app_name):
        keys = app_keys(app_name)
        if len(keys) == 1:
            return self._key_prefix(app_name)
        cached = self._app_prefixes.get(app_name)
        if cached:
            return cached
        for key in keys:
            prefix = self._key_prefix(app_name, app_key=key)
            if self._has_objects(prefix + "/"):
                # Data never moves between encodings, so a hit stays valid.
                self._app_prefixes[app_name] = prefix
                return prefix
        return self._key_prefix(app_name)

    def _has_objects(self, prefix):
        try:
            resp = self._s3.list_objects_v2(Bucket=self.bucket, Prefix=prefix, MaxKeys=1)
        except Exception:
            VMN_LOGGER.debug(f"S3 error probing {prefix}", exc_info=True)
            return False
        return resp.get("KeyCount", 0) > 0

    # -- client helpers -----------------------------------------------------

    def _head(self, key):
        try:
            self._s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as e:
            if not _is_missing(e):
                VMN_LOGGER.warning(f"S3 error checking {key}: {e}")
            return False

    def _get(self, key):
        try:
            return self._s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as e:
            if not _is_missing(e):
                VMN_LOGGER.debug(f"S3 error reading {key}", exc_info=True)
            return None

    def _put(self, key, data, **kwargs):
        body = data.encode("utf-8") if isinstance(data, str) else data
        self._s3.put_object(Bucket=self.bucket, Key=key, Body=body, **kwargs)

    def _objects(self, prefix):
        paginator = self._s3.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            yield from page.get("Contents", [])

    def _common_prefixes(self, prefix):
        paginator = self._s3.get_paginator("list_objects_v2")
        found = []
        for page in paginator.paginate(
            Bucket=self.bucket, Prefix=prefix, Delimiter="/"
        ):
            found.extend(cp["Prefix"] for cp in page.get("CommonPrefixes", []))
        return found

    # -- records ------------------------------------------------------------

    def _put_patches(self, prefix, patches):
        for key, filename, _ in PATCH_FILES:
            if patches.get(key):
                self._put(f"{prefix}/{filename}", patches[key])

    def _put_record_body(self, prefix, patches):
        self._put_patches(prefix, patches)
        for dep_path, dp in patches.get("deps", {}).items():
            self._put_patches(f"{prefix}/deps/{safe_dep_name(dep_path)}", dp)

    def save(self, app_name, verstr, metadata, patches):
        prefix = self._record_prefix(app_name, verstr)
        self._put_record_body(prefix, patches)
        self._put(f"{prefix}/{METADATA_FILE}", yaml.dump(metadata, sort_keys=True))

    def create_exclusive(self, app_name, verstr, metadata, patches):
        legacy = app_keys(app_name)[1:]
        if legacy and self._head(
            f"{self._key_prefix(app_name, verstr, app_key=legacy[0])}/{METADATA_FILE}"
        ):
            return False
        prefix = self._key_prefix(app_name, verstr)
        try:
            # The conditional PUT is the claim: exactly one writer wins it.
            self._put(
                f"{prefix}/{METADATA_FILE}",
                yaml.dump(metadata, sort_keys=True),
                IfNoneMatch="*",
            )
        except Exception as e:
            if _error_code(e) in _TAKEN_CODES:
                return False
            raise
        self._put_record_body(prefix, patches)
        return True

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

    def list_verstrs(self, app_name):
        prefix = self._app_prefix_with_data(app_name) + "/"
        return [
            unsafe_verstr(cp[len(prefix) :].rstrip("/"))
            for cp in self._common_prefixes(prefix)
        ]

    def _load_listed_metadata(self, meta_key):
        meta = core_utils.parse_record_metadata(self._get(meta_key))
        if meta is None:
            VMN_LOGGER.debug(f"Skipping non-snapshot metadata: {meta_key}")
        return meta

    def list_snapshots(self, app_name):
        prefix = self._app_prefix_with_data(app_name) + "/"
        keys = [f"{cp}{METADATA_FILE}" for cp in self._common_prefixes(prefix)]
        with ThreadPoolExecutor(max_workers=_LIST_WORKERS) as pool:
            metas = [m for m in pool.map(self._load_listed_metadata, keys) if m]
        return sorted(metas, key=lambda m: m.get("timestamp", ""))

    def list_files(self, app_name):
        prefix = self._app_prefix_with_data(app_name) + "/"
        files = {}
        for obj in self._objects(prefix):
            rest = obj["Key"][len(prefix) :]
            verstr, _, name = rest.partition("/")
            if name and "/" not in name:
                # LastModified has 1s resolution: the ETag tells apart two
                # same-size writes within one second (a heartbeat, say).
                files.setdefault(unsafe_verstr(verstr), {})[name] = (
                    obj["Size"],
                    obj["LastModified"].timestamp(),
                    obj.get("ETag"),
                )
        return files

    def update_note(self, app_name, verstr, note):
        metadata, _ = self.load(app_name, verstr)
        if metadata is None:
            return False
        metadata["note"] = note
        prefix = self._record_prefix(app_name, verstr)
        self._put(f"{prefix}/{METADATA_FILE}", yaml.dump(metadata, sort_keys=True))
        return True

    def delete(self, app_name, verstr):
        prefix = self._record_prefix(app_name, verstr)
        keys = [{"Key": o["Key"]} for o in self._objects(prefix + "/")]
        for i in range(0, len(keys), 1000):
            self._s3.delete_objects(
                Bucket=self.bucket, Delete={"Objects": keys[i : i + 1000]}
            )

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
            if _error_code(e) in ("416", "InvalidRange"):
                return b""  # nothing past offset
            if not _is_missing(e):
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

    # -- logs ---------------------------------------------------------------

    def log_objects(self, app_name, verstr, writer_id):
        prefix = f"{self._record_prefix(app_name, verstr)}/"
        sizes = {}
        for obj in self._objects(prefix + "log."):
            name = obj["Key"][len(prefix) :]
            if is_log_file(name) and log_writer_and_seq(name)[0] == writer_id:
                sizes[name] = obj["Size"]
        names = group_log_names(sizes).get(writer_id, [])
        return [(name, sizes[name]) for name in names]

    def delete_log_segments(self, app_name, verstr, writer_id):
        prefix = self._record_prefix(app_name, verstr)
        for name, _ in self.log_objects(app_name, verstr, writer_id):
            if log_writer_and_seq(name)[1]:
                self._s3.delete_object(Bucket=self.bucket, Key=f"{prefix}/{name}")

    def append_log_entry(self, app_name, verstr, writer_id, entry):
        """Append to this writer's single log object.

        S3 has no append, so this reads and rewrites the object — under an
        ETag precondition, so an entry another process appended in between
        makes this write retry instead of silently overwriting it.
        """
        key = f"{self._record_prefix(app_name, verstr)}/{log_object_name(writer_id)}"
        line = (json.dumps(entry, default=str) + "\n").encode("utf-8")
        for _ in range(_APPEND_ATTEMPTS):
            body, condition = self._get_with_condition(key)
            try:
                self._put(key, body + line, **condition)
                return True
            except Exception as e:
                if _error_code(e) not in _TAKEN_CODES:
                    raise
        raise RuntimeError(f"Could not append to {key}: too many concurrent writers")

    def _get_with_condition(self, key):
        """``(body, put precondition)`` that fails if *key* changes meanwhile."""
        try:
            resp = self._s3.get_object(Bucket=self.bucket, Key=key)
        except Exception as e:
            if not _is_missing(e):
                raise
            return b"", {"IfNoneMatch": "*"}
        return resp["Body"].read(), {"IfMatch": resp["ETag"]}

    def log_sizes(self, app_name, verstr):
        prefix = f"{self._record_prefix(app_name, verstr)}/"
        return log_sizes_of(
            (o["Key"][len(prefix) :], o["Size"]) for o in self._objects(prefix + "log")
        )

    def load_logs_by_writer(self, app_name, verstr, writers=None):
        """``{writer: entries}``; only *writers* (``""`` = log.yml) when given."""
        prefix = f"{self._record_prefix(app_name, verstr)}/"
        logs = {}
        legacy = self._get(prefix + LEGACY_LOG_FILE) if _wanted("", writers) else None
        if legacy:
            loaded = core_utils.yaml_safe_load(legacy)
            if isinstance(loaded, list):
                logs[""] = loaded
        names = [o["Key"][len(prefix) :] for o in self._objects(prefix + "log.")]
        for writer, group in group_log_names(names).items():
            if not _wanted(writer, writers):
                continue
            entries = logs.setdefault(writer, [])
            for name in group:
                data = self._get(prefix + name)
                if data:
                    entries.extend(parse_jsonl(data.decode("utf-8"), writer))
        return logs

    def load_merged_log(self, app_name, verstr):
        try:
            return flatten_logs(self.load_logs_by_writer(app_name, verstr))
        except Exception:
            VMN_LOGGER.debug("Failed to load S3 experiment log", exc_info=True)
            return []
