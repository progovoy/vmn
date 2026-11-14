"""Core's S3 record store: ``S3RecordStore`` and ``open_s3_store``.

``open_s3_store("s3://bucket/root?endpoint_url=...", "snapshots",
client_factory)`` opens the area ``<root>/snapshots`` (``vmn/snapshots``
without a root) with one ``client_factory(endpoint_url)`` client, its code
references resolved through the ``code`` area on the same client.
"""
from version_stamp.store.areas import CODE, area_prefix
from version_stamp.store.s3_base import S3ObjectBase
from version_stamp.store.s3_reads import S3RecordReads
from version_stamp.store.s3_records import S3RecordWrites
from version_stamp.store.uri import parse_store_uri


class S3RecordStore(S3RecordReads, S3RecordWrites, S3ObjectBase):
    def __init__(self, bucket, prefix, client, endpoint_url=None, options=None, code_store=None):
        """*code_store*: where ``load`` resolves ``code:`` references
        (default: this store)."""
        super().__init__(bucket, prefix, client, endpoint_url=endpoint_url, options=options)
        self._code_store = code_store

    @property
    def code_store(self):
        return self if self._code_store is None else self._code_store

    @code_store.setter
    def code_store(self, store):
        self._code_store = store


def open_s3_store(uri, area, client_factory):
    parsed = parse_store_uri(uri)
    if parsed.scheme != "s3":
        raise ValueError(f"Not an s3:// store URI: {uri!r}")
    endpoint_url = parsed.options.get("endpoint_url")
    store = S3RecordStore(
        parsed.location,
        area_prefix(parsed.path, area),
        client_factory(endpoint_url),
        endpoint_url=endpoint_url,
        options=parsed.options,
    )
    if area != CODE:
        store.code_store = store._open_area(CODE)
    return store
