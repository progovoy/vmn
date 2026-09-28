"""Helpers the job SDK needs from vmn, copied so vmn-exp-sdk does not depend on
vmn. tests/test_exp_base.py keeps each copy in step with version_stamp.core."""
import datetime
import hashlib
import logging
import os

import yaml
from filelock import FileLock

# The same logger the vmn CLI configures, so both sides share its handlers.
VMN_LOGGER = logging.getLogger("vmn")

# libyaml's loader is ~10x faster than the pure-Python one, and experiment
# listings parse one metadata.yml (and one run_state.yml) per run.
_FAST_SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)

_UNSAFE_IN_COMPONENT = ("/", "\\", os.sep, "\0", "..")


def ensure_logger():
    return VMN_LOGGER


def yaml_safe_load(stream_or_text):
    """``yaml.safe_load`` semantics, on the C loader when libyaml is present."""
    return yaml.load(stream_or_text, Loader=_FAST_SAFE_LOADER)


def parse_record_metadata(raw):
    """A snapshot/experiment record's ``metadata.yml`` dict, or None.

    None for a missing or unparsable file and for legacy ``create_snapshots``
    verinfo files, which share the tree but carry no ``verstr``.
    """
    if not raw:
        return None
    try:
        meta = yaml_safe_load(raw)
    except yaml.YAMLError:
        return None
    return meta if isinstance(meta, dict) and "verstr" in meta else None


def valid_path_component(name):
    """Whether *name* (a verstr, artifact name, ...) stays one path component."""
    return (
        bool(name)
        and name != "."
        and not any(bad in name for bad in _UNSAFE_IN_COMPONENT)
    )


def valid_app_path(app_name):
    """Whether *app_name* is a relative path of real components (``root/svc``)."""
    return bool(app_name) and all(
        valid_path_component(part) for part in app_name.split("/")
    )


def now_iso():
    """UTC now as the ``...Z`` ISO string every vmn record is timestamped with."""
    return (
        datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    )


def sha256_file(abs_path):
    h = hashlib.sha256()
    with open(abs_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _is_root(path):
    return os.path.exists(os.path.join(path, ".git")) or os.path.exists(
        os.path.join(path, ".vmn")
    )


def resolve_root_path():
    """The nearest directory at or above the working dir holding .git or .vmn."""
    path = os.path.realpath(
        os.path.expanduser(os.environ.get("VMN_WORKING_DIR", os.getcwd()))
    )
    while not _is_root(path):
        parent = os.path.realpath(os.path.join(path, ".."))
        if parent == path:
            raise RuntimeError("Running from an unmanaged directory")
        path = parent
    return path


def get_repo_lock(vmn_root_path):
    """The per-repo FileLock every vmn command takes; ``$VMN_LOCK_FILE_PATH``
    overrides its path for the whole process."""
    return FileLock(
        os.environ.get("VMN_LOCK_FILE_PATH")
        or os.path.join(vmn_root_path, ".vmn", "vmn.lock")
    )
