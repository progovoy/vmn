"""A forked child on macOS builds its S3 client without the system proxy lookup.

botocore resolves proxies through urllib's ``getproxies``/``proxy_bypass``,
which on macOS ask SystemConfiguration (``_scproxy``): not fork-safe, so a
forked child calling it segfaults. The parent resolves the client's proxies
at its first build and the child passes them to botocore explicitly; the
child's other botocore lookups (the credential chain's metadata fetcher) read
the environment only. Elsewhere nothing changes.
"""
import os
import subprocess
import sys
import urllib.request

import pytest
from exp_helpers import _PY, _SRC_PATH

needs_fork = pytest.mark.skipif(
    not hasattr(os, "fork") or sys.platform == "win32", reason="needs fork"
)

_PROXY_VARS = ("http_proxy", "https_proxy", "no_proxy", "all_proxy", "ftp_proxy")
SYSTEM_PROXIES = {"https": "http://system-proxy.example:3128"}


@pytest.fixture
def no_env_proxies(monkeypatch):
    for name in _PROXY_VARS:
        monkeypatch.delenv(name, raising=False)
        monkeypatch.delenv(name.upper(), raising=False)
    monkeypatch.setenv("AWS_ACCESS_KEY_ID", "x")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "x")
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")


@pytest.fixture
def forked(monkeypatch):
    real = os.getpid()
    return lambda: monkeypatch.setattr(os, "getpid", lambda: real + 1)


def _system_lookup_crashes(*_args, **_kwargs):
    raise AssertionError("the forked child asked macOS for its proxies")


def _system_proxies(monkeypatch, found):
    import botocore.utils

    monkeypatch.setattr(botocore.utils, "getproxies", found)
    monkeypatch.setattr(botocore.utils, "proxy_bypass", lambda host: False)


def test_the_darwin_child_uses_the_parents_proxies_and_never_the_system(
        monkeypatch, no_env_proxies, forked):
    from vmn_exp.storage.s3_base import S3Base

    monkeypatch.setattr(sys, "platform", "darwin")
    _system_proxies(monkeypatch, lambda: dict(SYSTEM_PROXIES))
    store = S3Base("bkt", prefix="team/runs")
    parent = store._s3
    forked()
    _system_proxies(monkeypatch, _system_lookup_crashes)
    import botocore.utils

    monkeypatch.setattr(botocore.utils, "proxy_bypass", _system_lookup_crashes)
    child = store._s3
    assert child is not parent
    assert child.meta.config.proxies == SYSTEM_PROXIES


def test_the_darwin_child_reads_only_environment_proxies_elsewhere(
        monkeypatch, no_env_proxies, forked):
    import botocore.utils
    from vmn_exp.storage.s3_base import S3Base

    monkeypatch.setattr(sys, "platform", "darwin")
    _system_proxies(monkeypatch, dict)
    store = S3Base("bkt", prefix="team/runs")
    forked()
    _system_proxies(monkeypatch, _system_lookup_crashes)
    monkeypatch.setattr(botocore.utils, "proxy_bypass", _system_lookup_crashes)
    store._s3
    monkeypatch.setenv("https_proxy", "http://env-proxy.example:8080")
    assert botocore.utils.get_environ_proxies("https://s3.amazonaws.com") == \
        urllib.request.getproxies_environment()


def test_elsewhere_the_child_resolves_its_proxies_as_before(
        monkeypatch, no_env_proxies, forked):
    import botocore.utils
    from vmn_exp.storage.s3_base import S3Base

    monkeypatch.setattr(sys, "platform", "linux")
    _system_proxies(monkeypatch, dict)
    lookup = botocore.utils.getproxies
    store = S3Base("bkt", prefix="team/runs")
    forked()
    child = store._s3
    assert child.meta.config.proxies is None
    assert botocore.utils.getproxies is lookup


_CHILD_WITHOUT_ENV_PROXIES = r"""
import os, sys, time
os.environ.update(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                  AWS_DEFAULT_REGION="us-east-1")
import boto3
from moto import mock_aws

mock = mock_aws()
mock.start()
boto3.client("s3").create_bucket(Bucket="bkt")

from vmn_exp.storage.s3 import S3SnapshotStorage
from vmn_exp.storage.s3_base import sigv4_client

V = "0.0.1-dev.a.b"
store = S3SnapshotStorage("bkt", prefix="exps/runs")
store.save("app", V, {"verstr": V}, {})
sigv4_client()
pid = os.fork()
if pid == 0:
    code = 0
    if store.load("app", V) is None:
        code = 3
    sigv4_client()
    os._exit(code)
deadline = time.monotonic() + 30
while time.monotonic() < deadline:
    done, status = os.waitpid(pid, os.WNOHANG)
    if done:
        code = os.waitstatus_to_exitcode(status)
        print("OK" if code == 0 else f"child failed: {code}")
        sys.exit(1 if code else 0)
    time.sleep(0.05)
os.kill(pid, 9)
print("HUNG")
sys.exit(75)
"""


@needs_fork
def test_a_real_forked_child_builds_a_client_without_env_proxies():
    env = {k: v for k, v in os.environ.items() if k.lower() not in _PROXY_VARS}
    env["PYTHONPATH"] = _SRC_PATH
    proc = subprocess.run([_PY, "-c", _CHILD_WITHOUT_ENV_PROXIES], env=env,
                          capture_output=True, text=True, timeout=120)
    assert proc.returncode == 0 and "OK" in proc.stdout, proc.stdout + proc.stderr


def test_a_botocore_without_the_resolved_proxies_falls_back_to_the_environment(
        monkeypatch, no_env_proxies, forked):
    from vmn_exp.storage import fork_proxies

    monkeypatch.setattr(sys, "platform", "darwin")
    built = []
    factory = fork_proxies.child_factory(
        lambda url, proxies=None: built.append((url, proxies)) or object(),
        "https://s3.example", object())
    forked()
    _system_proxies(monkeypatch, _system_lookup_crashes)
    factory()
    import botocore.utils

    assert built == [("https://s3.example", None)]
    assert botocore.utils.getproxies is urllib.request.getproxies_environment
