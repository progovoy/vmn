"""The ``features`` entry of a git-free run (:mod:`vmn_exp.core.from_snapshot`).

An exported tree has its patches applied and carries none, so the code's facts
(changed files and functions, commit subjects) are copied from the exported
run's own features entry, in the ``vmn_experiment.yml`` that ``vmn-exp
export`` writes next to ``vmn_metadata.yml``, at that entry's
``features_version``. Without one only the author is known: the entry is
written at version 0, below every real version, so ``vmn-exp
similar-backfill`` still derives the rest from the code object.

The author is this host's identity; its email is git config's (in the tree),
else the exporter's (``exported_by``), else ``VMN_EXP_AUTHOR``.
Best-effort: a failure is a warning and no entry.
"""
import os

from vmn_exp._base import VMN_LOGGER, yaml_safe_load
from vmn_exp.core.features import build_features_entry, code_facts
from vmn_exp.core.fold import fold_features, fold_log
from vmn_exp.core.identity import env_author, run_author

EXPERIMENT_FILE = "vmn_experiment.yml"
# The version of an entry naming only the author.
AUTHOR_ONLY_VERSION = 0


def export_features(tree_dir):
    """The ``features`` entry of a run created from the tree at *tree_dir*, or None."""
    try:
        return _entry(tree_dir, _exported_run(tree_dir))
    except Exception as exc:
        VMN_LOGGER.warning(f"Could not record the run's features ({exc}); "
                           "the run is created without them")
        return None


def _entry(tree_dir, exported):
    source = fold_features(fold_log(exported.get("log") or []))
    exporter = exported.get("exported_by")
    exporter_email = exporter.get("git_user_email") if isinstance(exporter, dict) else None
    author = run_author(tree_dir, [("export", exporter_email), env_author()])
    entry = build_features_entry("export", author=author, **code_facts(source))
    entry["features_version"] = source["features_version"] if source else AUTHOR_ONLY_VERSION
    return entry


def _exported_run(tree_dir):
    """``vmn_experiment.yml``'s ``{metadata, log, exported_by}``; {} without one."""
    path = os.path.join(tree_dir, EXPERIMENT_FILE)
    if not os.path.isfile(path):
        return {}
    with open(path) as f:
        exported = yaml_safe_load(f)
    return exported if isinstance(exported, dict) else {}
