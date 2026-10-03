#!/usr/bin/env python3
"""S3 listings that stay cheap at 10k–100k runs.

* :meth:`list_record_names` lists record prefixes by delimiter: one call per
  1000 runs, never a record's files.
* :meth:`list_files` with *keys* lists just those records, delimited, so the
  ``artifacts/``, ``outputs/`` and ``deps/`` subtrees are never paged through.
  The ``log/`` folder is part of a record's files (``log/<name>``): it costs a
  second, prefixed listing.

"""

from vmn_exp import _base
from vmn_exp._base import VMN_LOGGER
from vmn_exp.storage.files import (
    LOG_DIR,
    METADATA_FILE,
    is_log_file,
    safe_verstr,
    unsafe_verstr,
)
from vmn_exp.storage.s3_base import parallel_map


def _signature(obj):
    # LastModified has 1s resolution: the ETag tells apart two same-size
    # writes within one second (a heartbeat, say).
    return (obj["Size"], obj["LastModified"].timestamp(), obj.get("ETag"))


def _is_record_file(name):
    """A record's own file or log — not a subtree's, not a marker like ``.claim``."""
    if not name or name.startswith("."):
        return False
    return "/" not in name or is_log_file(name)


def _record_relpath(base, key):
    """*key*'s ``(verstr, name)`` under *base*, and the ``StartAfter``
    sentinel to skip past its subtree when *name* is nested (inside
    ``artifacts/``, ``deps/``, or any other one) — else None."""
    verstr, _, name = key[len(base) :].partition("/")
    subdir, nested, _ = name.partition("/")
    skip = nested and subdir != LOG_DIR
    return verstr, name, (f"{base}{verstr}/{subdir}0" if skip else None)


class S3Listing:
    def _app_prefix(self, app_name):
        return self._key_prefix(app_name)

    def _app_keys(self):
        base = self.prefix + "/"
        return [cp[len(base) :].rstrip("/") for cp in self._common_prefixes(base)]

    def _app_name_of(self, key):
        # The tag form (``root/svc`` → ``root-svc``) is bijective: ``-`` is
        # illegal in app names.
        return key.replace("-", "/")

    def _names_under(self, prefix):
        base = prefix + "/"
        return {
            unsafe_verstr(cp[len(base) :].rstrip("/")): prefix
            for cp in self._common_prefixes(base)
        }

    def _names_by_prefix(self, app_name):
        """``{verstr: the app prefix it lives under}``."""
        return self._names_under(self._app_prefix(app_name))

    def list_record_names(self, app_name):
        """``{name: None}`` for every record under the app — claims included —
        by delimiter. S3 has no cheap per-record change marker, hence None."""
        return dict.fromkeys(self._names_by_prefix(app_name))

    def list_verstrs(self, app_name):
        return list(self._names_by_prefix(app_name))

    def list_run_verstrs(self, app_name, code_verstr):
        """Verstrs that could collide with a new run of *code_verstr* —
        itself and its ``.<suffix>`` runs (``.rN``, a writer id, ...).

        Listed by a prefix scoped to *code_verstr*, so allocating a run
        never lists every run of every other code version the app has
        stamped. A record actually named *code_verstr* plus "." is a valid
        string prefix match on its own — no other code_verstr can share it
        (``0.0.10`` never matches a listing scoped to ``0.0.1.``) — so this
        needs one HEAD (the bare name) and one listing (its ``.`` suffixes),
        not a listing of the whole app.
        """
        safe_code = safe_verstr(code_verstr)
        base = self._app_prefix(app_name) + "/"
        found = set()
        if self._head(f"{base}{safe_code}/{METADATA_FILE}"):
            found.add(code_verstr)
        for cp in self._common_prefixes(f"{base}{safe_code}."):
            found.add(unsafe_verstr(cp[len(base) :].rstrip("/")))
        return found

    def _load_listed_metadata(self, meta_key):
        meta = _base.parse_record_metadata(self._get_or_raise(meta_key))
        if meta is None:
            VMN_LOGGER.debug(f"Skipping non-snapshot metadata: {meta_key}")
        return meta

    def list_snapshots(self, app_name):
        keys = [
            f"{prefix}/{safe_verstr(name)}/{METADATA_FILE}"
            for name, prefix in self._names_by_prefix(app_name).items()
        ]
        metas = [
            m
            for m in parallel_map(self._load_listed_metadata, keys)
            if m and self.readable(m, app_name, m["verstr"]) is not None
        ]
        return sorted(metas, key=lambda m: m.get("timestamp", ""))

    def list_files(self, app_name, keys=None):
        """``{verstr: {filename: (size, mtime, etag)}}``: every record's, or
        only *keys*' (records that do not exist are left out)."""
        if keys is not None:
            return self._list_files_of(app_name, keys)
        return self._all_record_files(self._app_prefix(app_name) + "/")

    def _all_record_files(self, base):
        """*base*'s record files, keyed by verstr.

        A record's ``artifacts/`` or ``deps/`` subtree can hold far more
        objects than the record itself (checkpoints, per-dep patches, ...).
        Once a page ends inside one, the next request jumps past it with
        ``StartAfter`` instead of paging through the rest of it object by
        object — a record with thousands of them costs one extra call, not
        one per 1000. A subtree that ends within a page (the common, small
        case) costs nothing extra: it pages exactly as a plain walk would.
        """
        files = {}
        params = {"Prefix": base}
        # Without server-side StartAfter a jump re-reads everything before it.
        can_jump = getattr(self._s3, "server_side_start_after", True)
        while True:
            page = self._s3.list_objects_v2(Bucket=self.bucket, **params)
            skip_to = None
            for obj in page.get("Contents", []):
                verstr, name, skip_to = _record_relpath(base, obj["Key"])
                if skip_to:
                    continue
                if _is_record_file(name):
                    files.setdefault(unsafe_verstr(verstr), {})[name] = _signature(obj)
            if not page.get("IsTruncated"):
                return files
            params = (
                {"Prefix": base, "StartAfter": skip_to}
                if skip_to and can_jump
                else {"Prefix": base, "ContinuationToken": page["NextContinuationToken"]}
            )

    def _list_files_of(self, app_name, keys):
        prefix = self._app_prefix(app_name)
        wanted = [key for key in keys if _base.valid_path_component(key)]
        listed = parallel_map(
            lambda key: self._files_at(f"{prefix}/{safe_verstr(key)}/"), wanted
        )
        return {key: files for key, files in zip(wanted, listed) if files}

    def _files_at(self, record_prefix):
        """One record's own files and logs, delimited: its other subtrees
        are never listed."""
        files = {}
        listings = (
            {"Prefix": record_prefix, "Delimiter": "/"},
            {"Prefix": f"{record_prefix}{LOG_DIR}/", "Delimiter": "/"},
        )
        for params in listings:
            for page in self._pages(**params):
                for obj in page.get("Contents", []):
                    name = obj["Key"][len(record_prefix) :]
                    if _is_record_file(name):
                        files[name] = _signature(obj)
        return files

    def record_files(self, app_name, verstr):
        """``{filename: (size, mtime, etag)}`` for one record's files — one LIST."""
        return self._files_at(f"{self._record_prefix(app_name, verstr)}/")
