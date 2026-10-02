"""What the server may do with a store workspace (plan 11 §6.3).

The server only uses the permissions it can probe: ``read`` (list the runs
area) and ``edit`` (a conditional write of a probe key under its own
``server`` area). A role that can also delete is flagged in multi-tenant
deployments; for now that is a warning, not a refusal.
"""
import uuid
from dataclasses import dataclass, field
from typing import List

from vmn_exp.storage.areas import RUNS
from vmn_exp.storage.registry import open_store

READ = "read"
EDIT = "edit"
SERVER_AREA = "server"
PROBE_SCOPE = "probe"


@dataclass
class Probe:
    capabilities: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)


def _can_read(uri, opener):
    try:
        opener(uri, RUNS).list_apps()
        return True
    except Exception:
        return False


def _claim_probe_key(store):
    key = f"probe-{uuid.uuid4().hex}"
    if not store.create_exclusive(PROBE_SCOPE, key, {"probe": True}, {}):
        raise RuntimeError("probe key already taken")
    return key


def _deleted(store, key):
    try:
        store.delete(PROBE_SCOPE, key)
        return True
    except Exception:
        return False


def probe_store(uri, tenancy="single", opener=open_store):
    """The capabilities the server has on the store *uri*."""
    probe = Probe()
    if not _can_read(uri, opener):
        probe.warnings.append(f"cannot read {uri}")
        return probe
    probe.capabilities.append(READ)
    store = opener(uri, SERVER_AREA)
    try:
        key = _claim_probe_key(store)
    except Exception as exc:
        probe.warnings.append(f"no edit access (probe write failed: {exc})")
        return probe
    probe.capabilities.append(EDIT)
    if _deleted(store, key) and tenancy == "multi":
        probe.warnings.append("the server's role can delete objects; grant it no delete")
    return probe
