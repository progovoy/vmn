"""On-disk state and naming for worktree islands."""
import json
import os

from version_stamp.core.constants import ISLAND_BRANCH_PREFIX

ISLAND_MANIFEST_FILENAME = "island.json"


def write_manifest(manifest):
    path = os.path.join(manifest["base_path"], ISLAND_MANIFEST_FILENAME)
    with open(path, "w") as stream:
        json.dump(manifest, stream, indent=2)


def island_dir(vmn_ctx, name):
    """Directory of island *name* under the --base-path of the current repo."""
    base = os.path.join(vmn_ctx.vcs.vmn_root_path, vmn_ctx.args.base_path)
    return os.path.join(os.path.abspath(base), name)


def island_branch_name(island_name, source_branch):
    return f"{ISLAND_BRANCH_PREFIX}{island_name}/{source_branch}"
