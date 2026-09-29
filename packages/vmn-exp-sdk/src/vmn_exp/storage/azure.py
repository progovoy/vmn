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
import os

from vmn_exp.storage.object_client import BAD_RANGE, Body, ObjectClient, ObjectStoreError
from vmn_exp.storage.registry import default_prefix, missing_extra
from vmn_exp.storage.s3 import S3SnapshotStorage


def _obj(props):
    return {"Key": props.name, "Size": props.size, "LastModified": props.last_modified,
            "ETag": props.etag}


class AzureObjectClient(ObjectClient):
    def __init__(self, container, if_not_modified):
        super().__init__()
        self._container = container
        self._if_not_modified = if_not_modified  # azure.core.MatchConditions.IfNotModified

    def _blob(self, key):
        return self._container.get_blob_client(key)

    def _stat(self, key):
        try:
            return _obj(self._blob(key).get_blob_properties())
        except Exception as e:
            if getattr(e, "status_code", None) == 404:
                return None
            raise

    def _get(self, key, offset):
        try:
            stream = self._blob(key).download_blob(offset=offset or None)
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
            blob.upload_blob(body, overwrite=True, etag=if_match,
                             match_condition=self._if_not_modified)
        else:
            blob.upload_blob(body, overwrite=not if_none_match)

    def _iter(self, prefix, delimiter, start_after):
        if delimiter:
            listing = self._container.walk_blobs(name_starts_with=prefix or None,
                                                 delimiter=delimiter)
        else:
            listing = self._container.list_blobs(name_starts_with=prefix or None)
        for item in listing:
            if item.name <= start_after:
                continue
            # walk_blobs yields a BlobPrefix (it has .prefix) per "directory".
            yield item.name if getattr(item, "prefix", None) else _obj(item)

    def _remove(self, key):
        try:
            self._container.delete_blob(key)
        except Exception as e:
            if getattr(e, "status_code", None) != 404:
                raise

    def _upload(self, src, key):
        with open(src, "rb") as f:
            self._blob(key).upload_blob(f, overwrite=True)

    def _download(self, key, dest):
        with open(dest, "wb") as f:
            self._blob(key).download_blob().readinto(f)


class AzureSnapshotStorage(S3SnapshotStorage):
    scheme = "az"

    def __init__(self, container_name, prefix="vmn-snapshots", container=None,
                 if_not_modified=None):
        client = AzureObjectClient(container, if_not_modified)
        super().__init__(container_name, prefix=prefix, client=client)


def _sdk():
    try:
        from azure.core import MatchConditions
        from azure.storage.blob import ContainerClient
    except ImportError:
        raise missing_extra("azure-storage-blob", "azure") from None
    return ContainerClient, MatchConditions


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


def open_azure_store(uri, subdir):
    container_cls, match = _sdk()
    container = _container_client(container_cls, uri.location,
                                  uri.options.get("account_url"))
    return AzureSnapshotStorage(uri.location, prefix=default_prefix(uri, subdir),
                                container=container,
                                if_not_modified=match.IfNotModified)
