"""The storage conformance kit against emulators of the real services:
fake-gcs-server for GCS and Azurite for Azure Blob, each a container started
once per session through the real SDK clients (plan 41 D15 stage 2).

Docker tests by nature: the ``emulator`` marker keeps them out of the regular
passes; CI runs them in the ``tests_storage_emulators`` stage. The millisecond
layer stays the fakes in object_store_fakes.py. A failing check here is
triaged against the real service first: the emulators' conditional writes are
imperfect copies too.
"""
import contextlib
import itertools
import shutil
import socket
import subprocess
import time
import urllib.error
import urllib.request

import pytest
from vmn_exp.storage import conformance

pytestmark = pytest.mark.emulator

GCS_IMAGE = "fsouza/fake-gcs-server:1.52.2"
AZURITE_IMAGE = "mcr.microsoft.com/azure-storage/azurite:3.34.0"
# Azurite's published development account (the same for every install).
AZURITE_ACCOUNT = "devstoreaccount1"
AZURITE_KEY = (
    "Eby8vdM02xNOcqFlqUwJPLlmEtlCDXJ1OUzFT50uSRZ6IFsuFq2UVErCz4I6tq/K1SZFPTOtr/KBHBeksoGMGw=="
)
BUCKET = "bkt"


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_until_answering(url, timeout=60):
    deadline = time.monotonic() + timeout
    while True:
        try:
            urllib.request.urlopen(url, timeout=2).close()
            return
        except urllib.error.HTTPError:
            return  # it answered, if only with an error status
        except OSError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


@contextlib.contextmanager
def _container(port, container_port, image, *args):
    """Start *image* with *container_port* published on *port*; yields, then removes it."""
    if shutil.which("docker") is None:
        pytest.skip("docker unavailable")
    cid = subprocess.run(
        ["docker", "run", "-d", "--rm", "-p", f"127.0.0.1:{port}:{container_port}", image, *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()
    try:
        yield
    finally:
        subprocess.run(["docker", "rm", "-f", cid], capture_output=True)


@pytest.fixture(scope="session")
def gcs_endpoint():
    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    with _container(port, 4443, GCS_IMAGE,
                        "-scheme", "http", "-port", "4443", "-external-url", url):
        _wait_until_answering(f"{url}/storage/v1/b")
        yield url


@pytest.fixture(scope="session")
def azurite_connection_string():
    port = _free_port()
    with _container(port, 10000, AZURITE_IMAGE, "azurite-blob", "--blobHost", "0.0.0.0",
                        "--skipApiVersionCheck", "--loose"):
        _wait_until_answering(f"http://127.0.0.1:{port}/{AZURITE_ACCOUNT}")
        yield (
            "DefaultEndpointsProtocol=http;"
            f"AccountName={AZURITE_ACCOUNT};AccountKey={AZURITE_KEY};"
            f"BlobEndpoint=http://127.0.0.1:{port}/{AZURITE_ACCOUNT};"
        )


def _failures(make_store):
    return [(name, error) for name, error in conformance.check_store(make_store)
            if error is not None]


def test_conformance_checks_pass_on_fake_gcs_server(gcs_endpoint):
    from google.auth.credentials import AnonymousCredentials
    from google.cloud import storage
    from vmn_exp.storage.gcs import GCSSnapshotStorage

    client = storage.Client(project="test", credentials=AnonymousCredentials(),
                            client_options={"api_endpoint": gcs_endpoint})
    client.create_bucket(BUCKET)
    fresh = itertools.count()

    def make_store():
        return GCSSnapshotStorage(BUCKET, prefix=f"p{next(fresh)}", client=client)

    assert _failures(make_store) == []


def test_conformance_checks_pass_on_azurite(azurite_connection_string):
    from azure.core import MatchConditions
    from azure.storage.blob import ContainerClient
    from vmn_exp.storage.azure import AzureSnapshotStorage

    container = ContainerClient.from_connection_string(azurite_connection_string, BUCKET)
    container.create_container()
    fresh = itertools.count()

    def make_store():
        return AzureSnapshotStorage(BUCKET, prefix=f"p{next(fresh)}", container=container,
                                    if_not_modified=MatchConditions.IfNotModified)

    assert _failures(make_store) == []
