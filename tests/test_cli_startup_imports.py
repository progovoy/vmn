"""Every vmn (and vmn-exp) command imports the CLI entry; only `vmn config`
prompts, so the prompt library must not load at startup (~0.13 s)."""
import subprocess
import sys

_CHECK = """
import sys
import version_stamp.cli.entry
print(sorted(m for m in ("questionary", "prompt_toolkit") if m in sys.modules))
"""


def test_the_cli_entry_does_not_load_the_prompt_library():
    out = subprocess.run([sys.executable, "-c", _CHECK], capture_output=True, text=True,
                         check=True, env={"PYTHONPATH": ":".join(sys.path)})
    assert out.stdout.strip() == "[]"


_SNAPSHOT_CHECK = """
import sys
from types import SimpleNamespace
from version_stamp.snapshot.stores import open_snapshot_stores
vcs = SimpleNamespace(vmn_root_path=sys.argv[1], name="app", store={}, experiment={})
open_snapshot_stores(vcs, {}).records.list_snapshots("app")
open_snapshot_stores(vcs, {"store": "file://" + sys.argv[2]}).records.list_snapshots("app")
print(sorted(m for m in sys.modules if m.split(".")[0] in ("boto3", "botocore")
             or m in ["version_stamp.store." + n for n in sys.argv[3:]]))
"""
# store.s3_errors (error codes, no boto3) is the marker's, so it may load.
_S3_STORE_MODULES = ("s3_client", "s3_base", "s3_records", "s3_reads", "s3_store")


def test_a_local_or_directory_snapshot_store_loads_no_s3_modules(tmp_path):
    out = subprocess.run(
        [sys.executable, "-c", _SNAPSHOT_CHECK, str(tmp_path / "repo"), str(tmp_path / "shared"),
         *_S3_STORE_MODULES],
        capture_output=True, text=True, check=True, env={"PYTHONPATH": ":".join(sys.path)})
    assert out.stdout.strip() == "[]"
