"""The record stores a store URI names: ``open_record_stores``.

``open_record_stores(uri, options, s3_client_factory, local_store_at_root)
-> (records, code, runs)``, the ``snapshots``/``code``/``runs`` areas of the
store root, records and runs resolving ``code:`` references through *code*:

- ``file:///dir`` or a bare path: ``local_store_at_root(root, area,
  code_store=None)`` stores (vmn's ``LocalRecordStore.at_root``; passed in, as
  this package never imports ``version_stamp.snapshot``);
- ``s3://bucket/root``: :class:`~version_stamp.store.s3_store.S3RecordStore`
  areas sharing one ``s3_client_factory(endpoint_url)`` client, the endpoint
  from the URI's query, else *options* ``{"s3": {"endpoint_url": ...}}``
  (``version_stamp.store.config.resolve_store``). The s3 modules load only here.

Any other scheme raises :class:`UnsupportedScheme`.
"""
from version_stamp.store.areas import CODE, RUNS, SNAPSHOTS, area_prefix
from version_stamp.store.uri import parse_store_uri


class UnsupportedScheme(ValueError):
    def __init__(self, scheme):
        super().__init__(f"{scheme}:// stores are not built into vmn")
        self.scheme = scheme


def open_record_stores(uri, options, s3_client_factory, local_store_at_root):
    parsed = parse_store_uri(uri)
    if parsed.scheme == "file":
        return _directory_stores(parsed.path, local_store_at_root)
    if parsed.scheme == "s3":
        return _s3_stores(parsed, options, s3_client_factory)
    raise UnsupportedScheme(parsed.scheme)


def _directory_stores(root, at_root):
    code = at_root(root, CODE)
    return at_root(root, SNAPSHOTS, code_store=code), code, at_root(root, RUNS, code_store=code)


def _endpoint_url(parsed, options):
    lent = ((options or {}).get("s3") or {}).get("endpoint_url")
    return parsed.options.get("endpoint_url") or lent


def _s3_stores(parsed, options, s3_client_factory):
    from version_stamp.store.s3_store import S3RecordStore

    endpoint_url = _endpoint_url(parsed, options)
    client = s3_client_factory(endpoint_url)

    def area(name):
        return S3RecordStore(parsed.location, area_prefix(parsed.path, name), client,
                             endpoint_url=endpoint_url, options=parsed.options)

    code = area(CODE)
    records, runs = area(SNAPSHOTS), area(RUNS)
    records.code_store = runs.code_store = code
    return records, code, runs
