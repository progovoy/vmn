"""On-disk state and naming for worktree islands."""
import json
import os

ISLAND_MANIFEST_FILENAME = "island.json"
ISLAND_BRANCH_PREFIX = "island/"


def write_manifest(manifest):
    path = os.path.join(manifest["base_path"], ISLAND_MANIFEST_FILENAME)
    with open(path, "w") as stream:
        json.dump(manifest, stream, indent=2)


def island_branch_name(island_name, source_branch):
    return f"{ISLAND_BRANCH_PREFIX}{island_name}/{source_branch}"


def is_island_branch(branch):
    return bool(branch) and branch.startswith(ISLAND_BRANCH_PREFIX)
