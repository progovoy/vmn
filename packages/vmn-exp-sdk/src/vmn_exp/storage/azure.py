"""The Azure Blob Storage backend (``az://container/prefix``,
``pip install 'vmn-exp-sdk[azure]'``).

The S3 backend's logic over an azure-storage-blob container:
``upload_blob(overwrite=False)`` is the atomic ``If-None-Match: *`` create and
``etag=`` + ``MatchConditions.IfNotModified`` the ``If-Match`` overwrite.

The account: ``AZURE_STORAGE_CONNECTION_STRING``, else an account URL
(``?account_url=`` on the URI or ``AZURE_STORAGE_ACCOUNT_URL``) with
``DefaultAzureCredential`` when azure-identity is installed (or a SAS token
in the URL).
"""
import functools
import inspect
import logging
import os

from vmn_exp.storage.object_client import BAD_RANGE, Body, ObjectClient, ObjectStoreError
from vmn_exp.storage.registry import default_prefix, missing_extra
from vmn_exp.storage.s3 import S3SnapshotStorage

_DELETE_BATCH = 256  # the most blobs one blob batch request takes
_LOGGER = logging.getLogger(__name__)


def _obj(props):
    return {"Key": props.name, "Size": props.size, "LastModified": props.last_modified,
            "ETag": props.etag}


class AzureObjectClient(ObjectClient):
    def __init__(self, container, if_not_modified, supports_start_from=False):
        """*supports_start_from*: the SDK sends ``list_blobs(start_from=)``
        (:func:`sdk_sends_start_from`), so a flat listing starts at a key."""
        super().__init__()
        self._container = container
        self._if_not_modified = if_not_modified  # azure.core.MatchConditions.IfNotModified
        self.server_side_start_after = supports_start_from

    def _blob(self, key):
        return self._container.get_blob_client(key)

    def _stat(self, key):
        try:
            return _obj(self._blob(key).get_blob_properties())
        except Exception as e:
            if getattr(e, "status_code", None) == 404:
                return None
            raise

    def _get(self, key, offset, length=None):
        try:
            # The SDK refuses a length without an offset.
            start = offset if length is not None else offset or None
            stream = self._blob(key).download_blob(offset=start, length=length)
        except Exception as e:
            if getattr(e, "status_code", None) == 416:
                raise ObjectStoreError(BAD_RANGE, key) from e
            raise
        return {
            "Body": Body(stream.readall, lambda size: stream.chunks()),
            "ETag": stream.properties.etag,
            "ContentLength": stream.size,
        }

    def _put(self, key, body, if_none_match, if_match):
        blob = self._blob(key)
        if if_match:
            props = blob.upload_blob(body, overwrite=True, etag=if_match,
                                     match_condition=self._if_not_modified)
        else:
            props = blob.upload_blob(body, overwrite=not if_none_match)
        return (props or {}).get("etag")

    def _iter(self, prefix, delimiter, start_after):
        if delimiter:
            listing = self._container.walk_blobs(name_starts_with=prefix or None,
                                                 delimiter=delimiter)
        else:
            listing = self._container.list_blobs(name_starts_with=prefix or None,
                                                 **self._start_from(start_after))
        for item in listing:
            if item.name <= start_after:  # the service's start key is inclusive
                continue
            # walk_blobs yields a BlobPrefix (it has .prefix) per "directory".
            yield item.name if getattr(item, "prefix", None) else _obj(item)

    def _start_from(self, start_after):
        """walk_blobs gets none: a delimited listing takes a one-level key only."""
        if start_after and self.server_side_start_after:
            return {"start_from": start_after}
        return {}

    def _remove(self, key):
        try:
            self._container.delete_blob(key)
        except Exception as e:
            if getattr(e, "status_code", None) != 404:
                raise

    def _remove_many(self, keys):
        chunks = [keys[i:i + _DELETE_BATCH] for i in range(0, len(keys), _DELETE_BATCH)]
        return [failure for chunk in chunks for failure in self._remove_batch(chunk)]

    def _remove_batch(self, keys):
        try:
            responses = list(self._container.delete_blobs(*keys, raise_on_any_failure=False))
        except Exception as e:
            if getattr(e, "status_code", None) is None:
                raise
            # Some account types refuse blob batch: slower, never silent.
            _LOGGER.warning("Azure refused a batch delete (%s); deleting %d blobs one by one",
                            e, len(keys))
            return super()._remove_many(keys)
        return _failed_deletes(keys, responses)

    def _upload(self, src, key):
        with open(src, "rb") as f:
            self._blob(key).upload_blob(f, overwrite=True)

    def _download(self, key, dest):
        with open(dest, "wb") as f:
            self._blob(key).download_blob().readinto(f)


def _failed_deletes(keys, responses):
    """``[(key, error text)]`` from a blob batch's sub-responses, in request
    order; a 404 (already gone) is a success."""
    return [(key, f"HTTP {r.status_code}") for key, r in zip(keys, responses)
            if r.status_code != 404 and not 200 <= r.status_code < 300]


class AzureSnapshotStorage(S3SnapshotStorage):
    scheme = "az"

    def __init__(self, container_name, prefix="vmn/snapshots", container=None,
                 if_not_modified=None, client_factory=None, options=None,
                 supports_start_from=False):
        """*client_factory* (an :class:`AzureObjectClient` builder, used
        instead of *container*) builds the client again in a forked child."""
        client = None if client_factory else AzureObjectClient(
            container, if_not_modified, supports_start_from=supports_start_from)
        super().__init__(container_name, prefix=prefix, client=client,
                         client_factory=client_factory, options=options)


def _sdk():
    try:
        from azure.core import MatchConditions
        from azure.storage.blob import ContainerClient
    except ImportError:
        raise missing_extra("azure-storage-blob", "azure") from None
    return ContainerClient, MatchConditions


def sdk_sends_start_from():
    """Whether the installed azure-storage-blob sends ``list_blobs``'
    ``start_from``: its generated List Blobs operation names it. An older SDK
    hands the unknown keyword to the HTTP transport, so it is not passed."""
    try:
        from azure.storage.blob._generated.operations import ContainerOperations
    except ImportError:
        return False  # laid out otherwise: list from the start, filter client-side
    return takes_start_from(ContainerOperations.list_blob_flat_segment)


def takes_start_from(list_operation):
    return "start_from" in inspect.signature(list_operation).parameters


def _container_client(container_cls, name, account_url):
    conn = os.environ.get("AZURE_STORAGE_CONNECTION_STRING")
    if conn:
        return container_cls.from_connection_string(conn, name)
    account_url = account_url or os.environ.get("AZURE_STORAGE_ACCOUNT_URL")
    if not account_url:
        raise ValueError(
            "Azure storage needs an account: set AZURE_STORAGE_CONNECTION_STRING, "
            "or AZURE_STORAGE_ACCOUNT_URL (or ?account_url= on the az:// URI)."
        )
    return container_cls(account_url, name, credential=_default_credential())


def _default_credential():
    try:
        from azure.identity import DefaultAzureCredential
    except ImportError:
        return None  # a SAS token in the account URL, or anonymous access
    return DefaultAzureCredential()


def _default_adapter(name, account_url):
    """A client of its own: container client, credential and token cache."""
    container_cls, match = _sdk()
    return AzureObjectClient(_container_client(container_cls, name, account_url),
                             match.IfNotModified, supports_start_from=sdk_sends_start_from())


def open_azure_store(uri, area):
    factory = functools.partial(_default_adapter, uri.location,
                                uri.options.get("account_url"))
    return AzureSnapshotStorage(uri.location, prefix=default_prefix(uri, area),
                                client_factory=factory, options=uri.options)
