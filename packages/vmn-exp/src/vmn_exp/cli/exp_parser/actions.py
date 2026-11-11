"""Which flag groups (see :mod:`.build`) each experiment action owns.

Audited from what each action's handler reads off its args (plan 39 B5a),
not from the help prefixes. A flag added later adds its entry here too.
"""

# Every action opens a store.
_STORE = ("storage", "from_snapshot")

ACTION_FLAGS = {
    "create": ("name", "new_app", "note", "file", "metrics", "inputs", "capture_env",
               "parent", "fork", "intent", "similar_hint") + _STORE,
    "run": ("name", "new_app", "note", "file", "inputs", "capture_env", "parent", "fork",
            "intent", "similar_hint", "supervision") + _STORE,
    "add": ("version", "latest", "note", "file", "metrics", "attach", "inputs", "force",
            "define_metric", "finish", "intent") + _STORE,
    "list": ("archived", "last", "query", "json", "sort", "top") + _STORE,
    "show": ("version", "latest", "json", "show") + _STORE,
    "compare": ("version", "last", "top", "json") + _STORE,
    "diff": ("version", "diff") + _STORE,
    "restore": ("version", "latest", "force") + _STORE,
    "export": ("version", "latest", "output") + _STORE,
    "prune": ("version", "query", "prune", "dry_run", "force") + _STORE,
    "tag": ("version", "latest", "tag") + _STORE,
    "archive": ("version", "latest", "query", "dry_run") + _STORE,
    "unarchive": ("version", "latest", "query", "dry_run") + _STORE,
    "import-mlflow": ("mlflow", "dry_run") + _STORE,
    "watch": ("watch",) + _STORE,
    "lineage": ("version", "json", "lineage") + _STORE,
    "importance": ("archived", "query", "json", "importance") + _STORE,
    "rewind": ("version", "latest", "rewind") + _STORE,
    "rerun": ("version", "latest", "dry_run", "json", "rerun", "fork", "name", "note",
              "file", "inputs", "capture_env", "parent", "supervision") + _STORE,
    "push": ("version", "dry_run", "json", "push") + _STORE,
    "compact": ("version", "compact") + _STORE,
    "export-metrics": ("version", "output", "export_metrics") + _STORE,
    "similar": ("version", "latest", "archived", "query", "json", "top", "all_apps",
                "similar") + _STORE,
    "similar-backfill": ("all_apps", "dry_run") + _STORE,
    "backfill-children": ("dry_run",) + _STORE,
}

EXPERIMENT_ACTIONS = list(ACTION_FLAGS)
