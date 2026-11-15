"""The S3 object primitives a record store is built from: key helpers and
head/get/put/create/list calls on an injected client.

Keys: ``<prefix>/<app key>/<safe verstr>/<file>``, *prefix* being an area's
(``<root>/snapshots``, docs/plans/14-store-layout.md). No record-API name is
defined here (``exists``, ``load*``, ``list_*``, ``save``, ``delete``,
``update_*``): vmn-exp-sdk's ``S3Base`` subclasses this, and such a name
would shadow its own format-gated one (plan 45, R3).
"""
import copy
import logging
from concurrent.futures import ThreadPoolExecutor

from version_stamp.store.areas import app_key
from version_stamp.store.names import checked_app_path, safe_verstr
from version_stamp.store.s3_errors import is_missing, is_taken

LOGGER = logging.getLogger("vmn")
# Requests one call keeps in flight.
S3_WORKERS = 10


class S3ObjectBase:
    scheme = "s3"

    def __init__(self, bucket, prefix, client, endpoint_url=None, options=None):
        """*client* speaks the boto3 S3 client subset used here; area copies
        (:meth:`_open_area`) share it. *options*: the store URI's query."""
        self.bucket = bucket
        self.prefix = prefix
        self.endpoint_url = endpoint_url
        self._options = dict(options or {})
        self._s3 = client

    @property
    def area(self):
        return self.prefix.rpartition("/")[2]

    def _open_area(self, area):
        """This store's sibling area ``<root>/<area>``, sharing the client."""
        clone = copy.copy(self)
        clone.prefix = f"{self.prefix.rpartition('/')[0]}/{area}".lstrip("/")
        return clone

    def _map(self, fn, items):
        """``[fn(item)]`` in order, at most :data:`S3_WORKERS` at a time."""
        items = list(items)
        if len(items) < 2:
            return [fn(item) for item in items]
        with ThreadPoolExecutor(max_workers=min(S3_WORKERS, len(items))) as pool:
            return list(pool.map(fn, items))

    # -- keys -----------------------------------------------------------------

    def _key_prefix(self, app_name, verstr=None):
        base = f"{self.prefix}/{app_key(checked_app_path(app_name))}"
        return f"{base}/{safe_verstr(verstr)}" if verstr else base

    def _record_prefix(self, app_name, verstr):
        return self._key_prefix(app_name, verstr)

    # -- client ---------------------------------------------------------------

    def _head(self, key):
        try:
            self._s3.head_object(Bucket=self.bucket, Key=key)
            return True
        except Exception as e:
            if not is_missing(e):
                LOGGER.warning(f"S3 error checking {key}: {e}")
            return False

    def _get(self, key):
        """*key*'s bytes; None when it is missing or cannot be read."""
        try:
            return self._s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        except Exception as e:
            if not is_missing(e):
                LOGGER.debug(f"S3 error reading {key}", exc_info=True)
            return None

    def _get_or_raise(self, key):
        """*key*'s bytes, None when it is missing; any other failure raises."""
        return self._get_with_etag(key)[0]

    def _get_with_etag(self, key):
        """``(bytes, etag)`` of *key*, ``(None, None)`` when it is missing."""
        try:
            resp = self._s3.get_object(Bucket=self.bucket, Key=key)
        except Exception as e:
            if is_missing(e):
                return None, None
            raise
        return resp["Body"].read(), resp["ETag"]

    def _put(self, key, data, **kwargs):
        body = data.encode("utf-8") if isinstance(data, str) else data
        return self._s3.put_object(Bucket=self.bucket, Key=key, Body=body, **kwargs)

    def _create(self, key, data):
        """Create *key* unless it exists (``If-None-Match``); whether it did."""
        try:
            self._put(key, data, IfNoneMatch="*")
        except Exception as e:
            if is_taken(e):
                return False
            raise
        return True

    def _pages(self, **params):
        """Every ``list_objects_v2`` page for *params*, following continuations."""
        params = dict(params, Bucket=self.bucket)
        while True:
            page = self._s3.list_objects_v2(**params)
            yield page
            if not page.get("IsTruncated"):
                return
            params["ContinuationToken"] = page["NextContinuationToken"]

    def _objects(self, prefix):
        for page in self._pages(Prefix=prefix):
            yield from page.get("Contents", [])

    def _common_prefixes(self, prefix):
        found = []
        for page in self._pages(Prefix=prefix, Delimiter="/"):
            found.extend(cp["Prefix"] for cp in page.get("CommonPrefixes", []))
        return found
