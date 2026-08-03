"""Compatibility for legacy island manifests without source_path.

Older island.json manifests did not store ``source_path`` for dependencies.
We reconstruct it from ``rel_path`` relative to the main repo source.

Safe to remove when: all existing islands have been recreated with vmn >= 0.9.x.
"""
import os


def legacy_dep_source(main_source, dep):
    """Compute dep source path from rel_path when source_path is missing."""
    rel_path = dep.get("rel_path")
    if rel_path:
        return os.path.realpath(os.path.join(main_source, rel_path))
    return None
