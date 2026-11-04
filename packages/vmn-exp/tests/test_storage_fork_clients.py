"""A forked child never reuses its parent's S3 client or connection pool.

Two processes writing on one pooled keep-alive TLS connection corrupt it for
both (plan 30, G1a), so an S3 store builds its client once per process: the
child's first call builds a fresh one, which every area clone of the store
shares, and the parent keeps its own. Each scenario runs in its own
interpreter, so forking never touches pytest's.
"""
import os
import subprocess
import sys

import pytest
from exp_helpers import _PY, _SRC_PATH

pytestmark = pytest.mark.skipif(
    not hasattr(os, "fork") or sys.platform == "win32", reason="needs fork"
)

_PRELUDE = r"""
import os, sys, time
os.environ.update(AWS_ACCESS_KEY_ID="x", AWS_SECRET_ACCESS_KEY="x",
                  AWS_DEFAULT_REGION="us-east-1")
import boto3
from moto import mock_aws

mock = mock_aws()
mock.start()
boto3.client("s3").create_bucket(Bucket="bkt")

from vmn_exp.storage.s3 import S3SnapshotStorage

V = "0.0.1-dev.a.b"
store = S3SnapshotStorage("bkt", prefix="exps/runs")
clone = store._open_area("models")
store.save("app", V, {"verstr": V}, {})
parent_client = store._s3
parent_pool = parent_client._endpoint.http_session


def wait_child(pid, timeout=30):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        done, status = os.waitpid(pid, os.WNOHANG)
        if done:
            return os.waitstatus_to_exitcode(status)  # a signal: negative
        time.sleep(0.05)
    os.kill(pid, 9)
    os.waitpid(pid, 0)
    print("HUNG: the forked child deadlocked")
    sys.exit(75)
"""

_CHILD_BUILDS_ITS_OWN_CLIENT = _PRELUDE + r"""
pid = os.fork()
if pid == 0:
    code = 0
    child_client = store._s3
    if child_client is parent_client:
        code = 3
    elif child_client._endpoint.http_session is parent_pool:
        code = 4
    elif clone._s3 is not child_client:        # area clones share the child's
        code = 5
    elif store.load("app", V) is None:         # and it works
        code = 6
    elif store._s3 is not child_client:        # built once per process
        code = 7
    os._exit(code)
code = wait_child(pid)
if code:
    print(f"child failed: {code}")
    sys.exit(code)
if store._s3 is not parent_client or clone._s3 is not parent_client:
    print("the parent's client changed")
    sys.exit(8)
if store.load("app", V) is None:
    print("the parent's store stopped working")
    sys.exit(9)
print("OK")
"""

_INJECTED_CLIENT_REFUSES_IN_CHILD = _PRELUDE + r"""
injected = S3SnapshotStorage("bkt", prefix="exps/runs", client=boto3.client("s3"))
pid = os.fork()
if pid == 0:
    try:
        injected._s3
    except RuntimeError as e:
        os._exit(0 if "fork" in str(e) else 3)
    os._exit(4)
code = wait_child(pid)
if code:
    print(f"child failed: {code}")
    sys.exit(code)
if injected.load("app", V) is None:
    print("the parent's injected client stopped working")
    sys.exit(5)
print("OK")
"""

_DEFAULT_SESSION_IS_RESET_IN_CHILD = _PRELUDE + r"""
from vmn_exp.storage.s3_base import sigv4_client

sigv4_client()
parent_session = boto3.DEFAULT_SESSION
assert parent_session is not None
pid = os.fork()
if pid == 0:
    sigv4_client()
    os._exit(0 if boto3.DEFAULT_SESSION is not parent_session else 3)
code = wait_child(pid)
if code:
    print(f"child failed: {code}")
    sys.exit(code)
sigv4_client()
if boto3.DEFAULT_SESSION is not parent_session:
    print("the parent's default session was reset")
    sys.exit(4)
print("OK")
"""


def _run_script(script):
    # Env proxies keep botocore off macOS's system proxy lookup, which crashes
    # a forked child (Apple's frameworks are not fork-safe).
    env = dict(os.environ, PYTHONPATH=_SRC_PATH, no_proxy="*")
    return subprocess.run([_PY, "-c", script], env=env, capture_output=True,
                          text=True, timeout=120)


def test_the_child_builds_its_own_client_and_the_parent_keeps_its_own():
    proc = _run_script(_CHILD_BUILDS_ITS_OWN_CLIENT)
    assert proc.returncode == 0 and "OK" in proc.stdout, proc.stdout + proc.stderr


def test_a_bare_injected_client_refuses_reuse_in_the_child():
    proc = _run_script(_INJECTED_CLIENT_REFUSES_IN_CHILD)
    assert proc.returncode == 0 and "OK" in proc.stdout, proc.stdout + proc.stderr


def test_the_child_never_shares_the_parents_default_boto3_session():
    proc = _run_script(_DEFAULT_SESSION_IS_RESET_IN_CHILD)
    assert proc.returncode == 0 and "OK" in proc.stdout, proc.stdout + proc.stderr
