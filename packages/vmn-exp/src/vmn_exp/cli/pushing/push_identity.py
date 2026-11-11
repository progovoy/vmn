"""What makes a local run and a remote record the same run, and a cheap
fingerprint of a local run's current files (for ``vmn exp push``).

A run's identity survives a rename and edits of its mutable fields
(``archived``, ``note``, ``code``), so an online-mirrored or previously pushed
run compares equal to its local copy, and a different run that merely shares
the name does not.
"""
import hashlib
import json

from vmn_exp.storage.remote_presence import record_identity


def run_identity(app_name, metadata):
    """``sha256(app_name|timestamp|base_commit|diff_hash|code_verstr|imported
    run id)`` of *metadata*, hex."""
    parts = (app_name,) + record_identity(metadata)
    joined = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(joined.encode("utf-8")).hexdigest()


def record_fingerprint(local, app_name, verstr):
    """A hash of the local record's files (name, size, mtime) and artifacts
    (name, size): unchanged means there is nothing new to push. Local only."""
    files = sorted(
        (name, list(sig)) for name, sig in local.record_files(app_name, verstr).items()
    )
    artifacts = sorted(
        (a["name"], a["size"]) for a in local.list_artifacts(app_name, verstr)
    )
    blob = json.dumps([files, artifacts], sort_keys=True)
    return hashlib.sha256(blob.encode("utf-8")).hexdigest()
