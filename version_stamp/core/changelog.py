#!/usr/bin/env python3
"""Group conventional-commit messages into changelog sections (pure, no I/O)."""
from version_stamp.core.version_math import parse_conventional_commit_message

TYPE_LABELS = {
    "feat": "Features",
    "fix": "Bug Fixes",
    "perf": "Performance Improvements",
    "refactor": "Refactoring",
    "docs": "Documentation",
    "style": "Style",
    "test": "Tests",
    "build": "Build",
    "ci": "CI",
    "chore": "Chores",
    "revert": "Reverts",
}

# Section order: Features, Bug Fixes first, remaining types in TYPE_LABELS order,
# then the catch-all last.
_PRIORITY_LABELS = ["Features", "Bug Fixes"]
_OTHER_LABEL = "Other Changes"
_LABEL_ORDER = (
    _PRIORITY_LABELS
    + [lbl for lbl in TYPE_LABELS.values() if lbl not in _PRIORITY_LABELS]
    + [_OTHER_LABEL]
)


def _is_breaking(parsed):
    if parsed.get("bc") == "!":
        return True
    footer = parsed.get("footer") or ""
    return "BREAKING CHANGE" in footer or "BREAKING-CHANGE" in footer


def _entry(parsed, short_hash):
    return {
        "type": (parsed.get("type") or "").strip(),
        "scope": parsed.get("scope") or None,
        "description": parsed["description"].strip(),
        "hash": short_hash,
    }


def group_commits(commits):
    """Group ``(message, short_hash)`` pairs into changelog sections.

    Non-conventional messages are skipped (matching stamp-time behavior). A
    breaking change lands only in ``breaking``, not its type group. Returns
    ``{"breaking": [...], "groups": [{"label", "type", "commits"}, ...]}`` with
    sections ordered Features, Bug Fixes, then the remaining types.
    """
    breaking = []
    by_label = {}
    for message, short_hash in commits:
        try:
            parsed = parse_conventional_commit_message(message)
        except ValueError:
            continue
        entry = _entry(parsed, short_hash)
        if _is_breaking(parsed):
            breaking.append(entry)
            continue
        label = TYPE_LABELS.get(entry["type"], _OTHER_LABEL)
        by_label.setdefault(label, {"type": entry["type"], "commits": []})
        by_label[label]["commits"].append(entry)

    groups = [
        {"label": label, **by_label[label]}
        for label in _LABEL_ORDER if label in by_label
    ]
    return {"breaking": breaking, "groups": groups}
