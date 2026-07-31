"""On-disk state for worktree islands."""
import json
import os

from version_stamp.cli.worktree_git import run_git

ISLAND_MANIFEST_FILENAME = "island.json"
WORKTREE_ISLAND_MARKER = ".worktree-island"
WORKTREE_READONLY_MARKER = ".worktree-readonly"


def write_manifest(manifest):
    path = os.path.join(manifest["base_path"], ISLAND_MANIFEST_FILENAME)
    with open(path, "w") as stream:
        json.dump(manifest, stream, indent=2)


def write_island_markers(checkouts, readonly=False):
    for checkout in checkouts:
        vmn_dir = os.path.join(str(checkout), ".vmn")
        os.makedirs(vmn_dir, exist_ok=True)
        open(os.path.join(vmn_dir, WORKTREE_ISLAND_MARKER), "a").close()
        if readonly:
            open(os.path.join(vmn_dir, WORKTREE_READONLY_MARKER), "a").close()
        _ignore_island_markers(checkout)


def _ignore_island_markers(checkout):
    result = run_git(checkout, ["rev-parse", "--git-path", "info/exclude"])
    if result is None or result.returncode != 0:
        return
    exclude_path = result.stdout.strip()
    if not os.path.isabs(exclude_path):
        exclude_path = os.path.join(str(checkout), exclude_path)
    os.makedirs(os.path.dirname(exclude_path), exist_ok=True)
    patterns = {".vmn/.worktree-island", ".vmn/.worktree-readonly"}
    existing = set()
    if os.path.isfile(exclude_path):
        with open(exclude_path) as stream:
            existing = {line.strip() for line in stream}
    with open(exclude_path, "a") as stream:
        for pattern in sorted(patterns - existing):
            stream.write(f"{pattern}\n")


def is_local_only_island(root_path):
    marker = os.path.join(str(root_path), ".vmn", WORKTREE_ISLAND_MARKER)
    return os.path.isfile(marker)
