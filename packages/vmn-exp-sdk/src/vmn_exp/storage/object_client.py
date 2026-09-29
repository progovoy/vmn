"""An S3-shaped client over another object store's SDK.

The S3 backend's halves (:mod:`vmn_exp.storage.s3`) speak a small subset of
the boto3 S3 client. Any store with a conditional create (``If-None-Match``)
and a conditional overwrite (``If-Match`` on a version token) can reuse all of
them — atomic claims, CAS metadata edits, log segments — by adapting its SDK
to that subset. Subclasses implement the ``_``-prefixed primitives; errors are
raised as :class:`ObjectStoreError` carrying the S3 error code the halves test.
"""
import contextlib
import itertools
import threading

MISSING, TAKEN, BAD_RANGE = "404", "412", "416"
_ERROR_CODES = {404: MISSING, 409: TAKEN, 412: TAKEN, 416: BAD_RANGE}
_PAGE_SIZE = 1000
_MAX_CURSORS = 64


class ObjectStoreError(Exception):
    def __init__(self, code, message=""):
        super().__init__(message or code)
        self.response = {"Error": {"Code": code}}


@contextlib.contextmanager
def translated_errors():
    """Re-raise an SDK error whose HTTP status matters as ObjectStoreError
    (google.api_core has ``code``, azure.core ``status_code``)."""
    try:
        yield
    except ObjectStoreError:
        raise
    except Exception as e:
        status = getattr(e, "status_code", None) or getattr(e, "code", None)
        code = _ERROR_CODES.get(status) if isinstance(status, int) else None
        if code is None:
            raise
        raise ObjectStoreError(code, str(e)) from e


class Body:
    """A ``get_object`` ``Body``: ``read()`` it or ``iter_chunks()`` it."""

    def __init__(self, read, chunks=None):
        self._read, self._chunks = read, chunks

    def read(self):
        with translated_errors():
            return self._read()

    def iter_chunks(self, chunk_size):
        if self._chunks is not None:
            return self._chunks(chunk_size)
        data = self._read()
        return (data[i:i + chunk_size] for i in range(0, len(data), chunk_size))


def _range_start(header):
    return int(header[len("bytes="):].rstrip("-")) if header else 0


class ObjectClient:
    """Subclasses implement:

    - ``_stat(key)`` -> ``{"Key","Size","LastModified","ETag"}`` or None
    - ``_get(key, offset)`` -> ``get_object``-shaped dict (raises MISSING/BAD_RANGE)
    - ``_put(key, body, if_none_match, if_match)`` (raises TAKEN on a failed condition)
    - ``_iter(prefix, delimiter, start_after)`` -> object dicts and, with a
      delimiter, common-prefix strings; only names after *start_after*
    - ``_remove(key)`` (missing is fine), ``_upload(src, key)``, ``_download(key, dest)``

    A store whose SDK cannot start a listing after a key sets
    ``server_side_start_after = False``: its ``_iter`` then skips client-side,
    so a listing pages on rather than jumping with ``StartAfter``.
    """

    server_side_start_after = True

    def __init__(self):
        self._cursors = {}
        self._cursor_ids = itertools.count()
        self._lock = threading.Lock()

    def head_object(self, Bucket, Key):
        with translated_errors():
            stat = self._stat(Key)
        if stat is None:
            raise ObjectStoreError(MISSING, Key)
        return dict(stat, ContentLength=stat["Size"])

    def get_object(self, Bucket, Key, Range=None):
        with translated_errors():
            return self._get(Key, _range_start(Range))

    def put_object(self, Bucket, Key, Body, IfNoneMatch=None, IfMatch=None):
        with translated_errors():
            self._put(Key, Body, if_none_match=IfNoneMatch == "*", if_match=IfMatch)
        return {}

    def delete_object(self, Bucket, Key):
        with translated_errors():
            self._remove(Key)
        return {}

    def delete_objects(self, Bucket, Delete):
        for obj in Delete["Objects"]:
            self.delete_object(Bucket, obj["Key"])
        return {"Errors": []}

    def upload_file(self, Filename, Bucket, Key):
        with translated_errors():
            self._upload(Filename, Key)

    def download_file(self, Bucket, Key, Filename):
        with translated_errors():
            self._download(Key, Filename)

    def list_objects_v2(self, Bucket, Prefix="", Delimiter=None, MaxKeys=None,
                        StartAfter=None, ContinuationToken=None):
        """One page. The continuation token names a paused listing held here,
        so paging costs one pass whatever the SDK's own paging looks like."""
        items = self._cursor(ContinuationToken)
        if items is None:
            items = iter(self._iter(Prefix, Delimiter, StartAfter or ""))
        limit = min(MaxKeys or _PAGE_SIZE, _PAGE_SIZE)
        with translated_errors():
            page = list(itertools.islice(items, limit + 1))
        contents = [i for i in page[:limit] if isinstance(i, dict)]
        prefixes = [{"Prefix": i} for i in page[:limit] if isinstance(i, str)]
        result = {"Contents": contents, "CommonPrefixes": prefixes,
                  "KeyCount": len(contents) + len(prefixes),
                  "IsTruncated": len(page) > limit}
        if result["IsTruncated"]:
            result["NextContinuationToken"] = self._park(
                itertools.chain(page[limit:], items)
            )
        return result

    def _park(self, items):
        with self._lock:
            token = str(next(self._cursor_ids))
            self._cursors[token] = items
            while len(self._cursors) > _MAX_CURSORS:
                self._cursors.pop(next(iter(self._cursors)))
        return token

    def _cursor(self, token):
        if token is None:
            return None
        with self._lock:
            items = self._cursors.pop(token, None)
        if items is None:
            raise ObjectStoreError("InvalidToken", f"listing cursor {token} expired")
        return items
