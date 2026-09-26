"""On-disk state and naming for worktree islands."""
import json
import os

from version_stamp.core.constants import ISLAND_BRANCH_PREFIX

ISLAND_MANIFEST_FILENAME = "island.json"


def write_manifest(manifest):
    path = os.path.join(manifest["base_path"], ISLAND_MANIFEST_FILENAME)
    with open(path, "w") as stream:
        json.dump(manifest, stream, indent=2)


def island_branch_name(island_name, source_branch):
    return f"{ISLAND_BRANCH_PREFIX}{island_name}/{source_branch}"


def is_island_branch(branch):
    return bool(branch) and branch.startswith(ISLAND_BRANCH_PREFIX)


def island_source_branch(branch):
    """'main' for 'island/<name>/main'; None for any other branch."""
    if not is_island_branch(branch):
        return None
    parts = branch.split("/", 2)
    return parts[2] if len(parts) == 3 else None
