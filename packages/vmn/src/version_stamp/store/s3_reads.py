"""S3 record reads.

:func:`read_record` / :func:`read_patches` work on any
:class:`~version_stamp.store.s3_base.S3ObjectBase` (vmn-exp-sdk's S3 store
delegates its record loads to them); :class:`S3RecordReads` is core's record
read API over them. It applies no format gate: core reads format 1 and 2.
"""
from version_stamp.core.utils import (
    parse_record_metadata,
    redact_record_remotes,
    yaml_safe_load,
)
from version_stamp.store.code import resolve_code
from version_stamp.store.names import METADATA_FILE, PATCH_FILES, safe_verstr, unsafe_verstr
from version_stamp.store.s3_base import LOGGER
from version_stamp.store.s3_errors import is_missing


def _patch_files(store, prefix):
    patches = {}
    for key, filename, binary in PATCH_FILES:
        data = store._get_or_raise(f"{prefix}/{filename}")
        if data:
            patches[key] = data if binary else data.decode("utf-8")
    return patches


def _dep_patches(store, prefix):
    base = f"{prefix}/deps/"
    found = {}
    for dep_prefix in store._common_prefixes(base):
        patches = _patch_files(store, dep_prefix.rstrip("/"))
        if patches:
            found[dep_prefix[len(base):].rstrip("/")] = patches
    return found


def read_patches(store, prefix):
    """The patches of the record at key *prefix*, its deps' included. Only a
    missing patch object is left out; a failed read or listing raises."""
    patches = _patch_files(store, prefix)
    deps = _dep_patches(store, prefix)
    if deps:
        patches["deps"] = deps
    return patches


def read_record(store, prefix):
    """``(metadata, patches)`` of the record at key *prefix*, ``(None, None)``
    when it does not exist. A record referring to a code object (``code:``)
    gets ``{}``: its patches live in that object."""
    raw = store._get(f"{prefix}/{METADATA_FILE}")
    if raw is None:
        return None, None
    metadata = redact_record_remotes(yaml_safe_load(raw))
    if metadata.get("code"):
        return metadata, {}
    return metadata, read_patches(store, prefix)


class S3RecordReads:
    """Reads that tell a missing object from a failed read: only a missing
    one is None/False; credentials, network and access errors raise."""

    def _get(self, key):
        return self._get_or_raise(key)

    def _head(self, key):
        try:
            self._s3.head_object(Bucket=self.bucket, Key=key)
        except Exception as e:
            if is_missing(e):
                return False
            raise
        return True

    def exists(self, app_name, verstr):
        try:
            prefix = self._record_prefix(app_name, verstr)
        except ValueError:
            return False  # not a record name, so certainly no record
        return self._head(f"{prefix}/{METADATA_FILE}")

    def load_record(self, app_name, verstr):
        return read_record(self, self._record_prefix(app_name, verstr))

    def load(self, app_name, verstr):
        """:meth:`load_record` with a ``code:`` reference resolved through
        ``self.code_store``."""
        metadata, patches = self.load_record(app_name, verstr)
        return resolve_code(self.code_store, app_name, metadata, patches)

    def load_file(self, app_name, verstr, filename):
        return self._get(f"{self._record_prefix(app_name, verstr)}/{filename}")

    def load_metadata(self, app_name, verstr):
        return parse_record_metadata(self.load_file(app_name, verstr, METADATA_FILE))

    def list_verstrs(self, app_name):
        """Every record name under the app (claims included), by delimiter:
        one call per 1000 names, never a record's files."""
        base = self._key_prefix(app_name) + "/"
        return [unsafe_verstr(cp[len(base):].rstrip("/")) for cp in self._common_prefixes(base)]

    list_record_names = list_verstrs

    def _listed_metadata(self, key):
        metadata = parse_record_metadata(self._get_or_raise(key))
        if metadata is None:
            LOGGER.debug(f"Skipping non-snapshot metadata: {key}")
        return metadata

    def list_snapshots(self, app_name):
        """The app's records' metadata, oldest ``timestamp`` first."""
        base = self._key_prefix(app_name)
        keys = [f"{base}/{safe_verstr(v)}/{METADATA_FILE}" for v in self.list_verstrs(app_name)]
        found = [m for m in self._map(self._listed_metadata, keys) if m is not None]
        return sorted(found, key=lambda m: m.get("timestamp", ""))
