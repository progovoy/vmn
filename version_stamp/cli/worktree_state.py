"""On-disk state for worktree islands."""
import json
import os

from version_stamp.cli.worktree_git import run_git

ISLAND_MANIFEST_FILENAME = "island.json"
WORKTREE_READONLY_MARKER = ".worktree-readonly"


def write_manifest(manifest):
    path = os.path.join(manifest["base_path"], ISLAND_MANIFEST_FILENAME)
    with open(path, "w") as stream:
        json.dump(manifest, stream, indent=2)


def write_island_markers(checkouts):
    for checkout in checkouts:
        vmn_dir = os.path.join(str(checkout), ".vmn")
        os.makedirs(vmn_dir, exist_ok=True)
        open(os.path.join(vmn_dir, WORKTREE_READONLY_MARKER), "a").close()
        _ignore_island_marker(checkout)


def _ignore_island_marker(checkout):
    result = run_git(checkout, ["rev-parse", "--git-path", "info/exclude"])
    if result is None or result.returncode != 0:
        return
    exclude_path = result.stdout.strip()
    if not os.path.isabs(exclude_path):
        exclude_path = os.path.join(str(checkout), exclude_path)
    os.makedirs(os.path.dirname(exclude_path), exist_ok=True)
    pattern = f".vmn/{WORKTREE_READONLY_MARKER}"
    if os.path.isfile(exclude_path):
        with open(exclude_path) as stream:
            if pattern in {line.strip() for line in stream}:
                return
    with open(exclude_path, "a") as stream:
        stream.write(f"{pattern}\n")
