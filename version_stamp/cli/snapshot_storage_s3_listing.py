#!/usr/bin/env python3
"""S3 listings that stay cheap at 10k–100k runs.

* :meth:`list_record_names` lists record prefixes by delimiter: one call per
  1000 runs, never a record's files.
* :meth:`list_files` with *keys* lists just those records, delimited, so the
  ``artifacts/`` and ``deps/`` subtrees are never paged through.

A root app's records may live under the legacy ``root_svc`` key as well as the
current ``root-svc`` one; every listing merges both, the current key winning.
Whether the legacy key holds anything is probed once (and re-probed after
:data:`_PROBE_TTL_SEC` while it holds nothing), so a steady poll stays one
listing. The legacy key is ambiguous — ``root_svc`` is also a valid app name —
so a record found there counts as the app's only when its metadata says so
(or, for a record older than the ``app_name`` field, when the app has nothing
under its current key: the rule reads used to follow).
"""

import time

from version_stamp.cli.snapshot_storage_files import (
    METADATA_FILE,
    checked_app_path,
    safe_verstr,
    unsafe_verstr,
)
from version_stamp.cli.snapshot_storage_s3_base import app_keys, parallel_map
from version_stamp.core import utils as core_utils
from version_stamp.core.logging import VMN_LOGGER

_PROBE_TTL_SEC = 300


def _signature(obj):
    # LastModified has 1s resolution: the ETag tells apart two same-size
    # writes within one second (a heartbeat, say).
    return (obj["Size"], obj["LastModified"].timestamp(), obj.get("ETag"))


def _is_record_file(name):
    """A record's own file — not a subtree's, not a marker like ``.claim``."""
    return bool(name) and "/" not in name and not name.startswith(".")


class S3Listing:
    def _app_prefixes(self, app_name):
        """The app's key prefix, then the legacy one when it holds any data."""
        keys = app_keys(checked_app_path(app_name))
        prefixes = [self._key_prefix(app_name, app_key=key) for key in keys]
        if len(prefixes) > 1 and not self._has_data(prefixes[1]):
            del prefixes[1:]
        return prefixes

    def _has_data(self, prefix):
        """Whether anything lives under *prefix*/ — a hit is cached for good
        (data never moves between encodings), a miss for a while."""
        found, probed_at = self._probes.get(prefix, (False, None))
        now = time.monotonic()
        if found or (probed_at is not None and now - probed_at < _PROBE_TTL_SEC):
            return found
        page = self._s3.list_objects_v2(
            Bucket=self.bucket, Prefix=prefix + "/", MaxKeys=1
        )
        found = page.get("KeyCount", 0) > 0
        self._probes[prefix] = (found, now)
        return found

    # -- the legacy key is shared: ``root_svc`` is also a valid app name -------

    def _legacy_owner(self, prefix, name):
        """The ``app_name`` recorded in a legacy record ("" when it predates
        the field), or None while it has no metadata. Owners never change."""
        cached = self._legacy_owners.get((prefix, name))
        if cached is not None:
            return cached
        raw = self._get_or_raise(f"{prefix}/{safe_verstr(name)}/{METADATA_FILE}")
        if raw is None:
            return None
        owner = (core_utils.parse_record_metadata(raw) or {}).get("app_name") or ""
        self._legacy_owners[(prefix, name)] = owner
        return owner

    def _owned_legacy(self, app_name, prefix, names):
        """The legacy-key *names* that are *app_name*'s: those recorded as its,
        and unlabeled ones while the app has nothing under its current key."""
        names = list(names)
        owners = parallel_map(lambda name: self._legacy_owner(prefix, name), names)
        unlabeled_ok = None
        owned = set()
        for name, owner in zip(names, owners):
            if owner == "" and unlabeled_ok is None:
                unlabeled_ok = not self._has_data(self._key_prefix(app_name))
            if owner == app_name or (owner == "" and unlabeled_ok):
                owned.add(name)
        return owned

    def _merge_legacy(self, app_name, by_key):
        """*by_key* ``[(prefix, {verstr: value})]`` (current key first) merged:
        the current key wins, the legacy one adds only the app's own records."""
        (_, merged), *legacy = by_key
        merged = dict(merged)
        for prefix, found in legacy:
            extra = {k: v for k, v in found.items() if k not in merged}
            for key in self._owned_legacy(app_name, prefix, extra):
                merged[key] = extra[key]
        return merged

    def _names_under(self, prefix):
        base = prefix + "/"
        return {
            unsafe_verstr(cp[len(base) :].rstrip("/")): prefix
            for cp in self._common_prefixes(base)
        }

    def _names_by_prefix(self, app_name):
        """``{verstr: the app prefix it lives under}``."""
        return self._merge_legacy(
            app_name, [(p, self._names_under(p)) for p in self._app_prefixes(app_name)]
        )

    def list_record_names(self, app_name):
        """``{name: None}`` for every record under the app — claims included —
        by delimiter. S3 has no cheap per-record change marker, hence None."""
        return dict.fromkeys(self._names_by_prefix(app_name))

    def list_verstrs(self, app_name):
        return list(self._names_by_prefix(app_name))

    def _load_listed_metadata(self, meta_key):
        meta = core_utils.parse_record_metadata(self._get_or_raise(meta_key))
        if meta is None:
            VMN_LOGGER.debug(f"Skipping non-snapshot metadata: {meta_key}")
        return meta

    def list_snapshots(self, app_name):
        keys = [
            f"{prefix}/{safe_verstr(name)}/{METADATA_FILE}"
            for name, prefix in self._names_by_prefix(app_name).items()
        ]
        metas = [m for m in parallel_map(self._load_listed_metadata, keys) if m]
        return sorted(metas, key=lambda m: m.get("timestamp", ""))

    def list_files(self, app_name, keys=None):
        """``{verstr: {filename: (size, mtime, etag)}}``: every record's, or
        only *keys*' (records that do not exist are left out)."""
        if keys is not None:
            return self._list_files_of(app_name, keys)
        return self._merge_legacy(
            app_name,
            [
                (p, self._all_record_files(p + "/"))
                for p in self._app_prefixes(app_name)
            ],
        )

    def _all_record_files(self, base):
        files = {}
        for obj in self._objects(base):
            verstr, _, name = obj["Key"][len(base) :].partition("/")
            if _is_record_file(name):
                files.setdefault(unsafe_verstr(verstr), {})[name] = _signature(obj)
        return files

    def _list_files_of(self, app_name, keys):
        prefixes = self._app_prefixes(app_name)
        wanted = [key for key in keys if core_utils.valid_path_component(key)]
        jobs = [(key, prefix) for key in wanted for prefix in prefixes]
        listed = parallel_map(
            lambda job: self._files_at(f"{job[1]}/{safe_verstr(job[0])}/"), jobs
        )
        by_key = [
            (prefix, {k: f for (k, p), f in zip(jobs, listed) if p == prefix and f})
            for prefix in prefixes
        ]
        return self._merge_legacy(app_name, by_key)

    def _files_at(self, record_prefix):
        """One record's own files, delimited: its subtrees are never listed."""
        files = {}
        for page in self._pages(Prefix=record_prefix, Delimiter="/"):
            for obj in page.get("Contents", []):
                name = obj["Key"][len(record_prefix) :]
                if _is_record_file(name):
                    files[name] = _signature(obj)
        return files

    def record_files(self, app_name, verstr):
        """``{filename: (size, mtime, etag)}`` for one record's files — one LIST."""
        return self._files_at(f"{self._record_prefix(app_name, verstr)}/")
