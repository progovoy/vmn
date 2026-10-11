"""The ``features`` entry of a git-free run (:mod:`vmn_exp.core.from_snapshot`).

An exported tree has its patches applied and carries none, so the code's facts
(changed files and functions, commit subjects) are copied from the exported
run's own features, at their ``features_version``: ``vmn-exp export`` writes
them and ``exported_by`` to ``vmn_features.yml`` next to ``vmn_metadata.yml``
(:func:`write_features_file`). Only that small file is read: the exported
run's whole log, in ``vmn_experiment.yml`` with every metrics entry, is read
for an export from before it alone, and only up to ``LEGACY_READ_MAX_BYTES``.
Without the run's features only the author is known: the entry is written at
version 0, below every real version, so ``vmn-exp similar-backfill`` still
derives the rest from the code object.

The author is this host's identity; its email is git config's (in the tree),
else the exporter's (``exported_by``), else ``VMN_EXP_AUTHOR``.
Best-effort: a failure is a warning and no entry.
"""
import os

import yaml
from vmn_exp._base import VMN_LOGGER, yaml_safe_load
from vmn_exp.core.features import build_features_entry, code_facts
from vmn_exp.core.fold import fold_features, fold_log
from vmn_exp.core.identity import env_author, run_author

EXPERIMENT_FILE = "vmn_experiment.yml"
FEATURES_FILE = "vmn_features.yml"
# An older export's vmn_experiment.yml is parsed for its features up to this size.
LEGACY_READ_MAX_BYTES = 1 << 20
# The version of an entry naming only the author.
AUTHOR_ONLY_VERSION = 0


def write_features_file(dest, log, exported_by):
    """Write the exported run's folded features (from its *log*) and *exported_by*."""
    entries = [e for e in log if isinstance(e, dict) and e.get("type") == "features"]
    with open(os.path.join(dest, FEATURES_FILE), "w") as f:
        yaml.safe_dump({"features": fold_features(fold_log(entries)),
                        "exported_by": exported_by}, f, sort_keys=False)


def export_features(tree_dir):
    """The ``features`` entry of a run created from the tree at *tree_dir*, or None."""
    try:
        return _entry(tree_dir, _exported(tree_dir))
    except Exception as exc:
        VMN_LOGGER.warning(f"Could not record the run's features ({exc}); "
                           "the run is created without them")
        return None


def _entry(tree_dir, exported):
    source = exported.get("features")
    source = source if isinstance(source, dict) else None
    exporter = exported.get("exported_by")
    exporter_email = exporter.get("git_user_email") if isinstance(exporter, dict) else None
    author = run_author(tree_dir, [("export", exporter_email), env_author()])
    entry = build_features_entry("export", author=author, **code_facts(source))
    entry["features_version"] = source["features_version"] if source else AUTHOR_ONLY_VERSION
    return entry


def _exported(tree_dir):
    """``{features, exported_by}`` of the export at *tree_dir*; {} without one."""
    written = _load(os.path.join(tree_dir, FEATURES_FILE))
    return written if written is not None else _older_export(tree_dir)


def _older_export(tree_dir):
    """An export without ``vmn_features.yml``: its run's features folded from
    ``vmn_experiment.yml``'s log, unless that file is too large to parse."""
    path = os.path.join(tree_dir, EXPERIMENT_FILE)
    if os.path.isfile(path) and os.path.getsize(path) > LEGACY_READ_MAX_BYTES:
        VMN_LOGGER.debug(f"Not reading the features of {path}: it is too large")
        return {}
    exported = _load(path) or {}
    return {"features": fold_features(fold_log(exported.get("log") or [])),
            "exported_by": exported.get("exported_by")}


def _load(path):
    """The mapping a YAML file holds, {} for another document, None without the file."""
    if not os.path.isfile(path):
        return None
    with open(path) as f:
        loaded = yaml_safe_load(f)
    return loaded if isinstance(loaded, dict) else {}
