#!/usr/bin/env python3
"""Stamp-tree routes — ``/tree``, ``/tree/root``, ``/deps`` — answered from
:data:`~version_stamp.ui.tree_cache.TREES` while the app's tags are unchanged."""
from fastapi import HTTPException

from version_stamp.ui.readers import tree as tree_reader
from version_stamp.ui.tree_cache import TREES


def register(app, prefix, checkout_for, optional_segment):
    """Add the routes; *checkout_for(ws_name, app_tag)* → ``(root_path, app_name)``."""
    base = f"{prefix}/workspaces/{{ws_name}}/apps/{{app_tag}}"

    @app.get(f"{base}/tree")
    def version_tree(ws_name: str, app_tag: str):
        root, app_name = checkout_for(ws_name, app_tag)
        return TREES.get(root, app_name, "dag", lambda: tree_reader.version_dag(root, app_name))

    @app.get(f"{base}/tree/root")
    def root_tree(ws_name: str, app_tag: str):
        root, app_name = checkout_for(ws_name, app_tag)
        return TREES.get(
            root, app_name, "root", lambda: tree_reader.root_topology(root, app_name)
        )

    @app.get(f"{base}/deps")
    def dep_graph(ws_name: str, app_tag: str, v: str = None, to: str = None):
        root, app_name = checkout_for(ws_name, app_tag)
        verstr, to_verstr = optional_segment(v), optional_segment(to)
        graph, err = TREES.get(
            root,
            app_name,
            "deps",
            lambda: tree_reader.dep_graph(root, app_name, verstr=verstr, to_verstr=to_verstr),
            verstr,
            to_verstr,
        )
        if err:
            raise HTTPException(404, err)
        return graph
