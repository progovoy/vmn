"""Run features: facts a run's own code says about it, for finding similar runs.

``features_from_patches(patch_texts)`` reads the run's patches (working tree
diff, local-commit format-patch, deps; parsing in core/features_patch.py) into
changed files, ``path::name`` symbols and commit subjects plus the commits'
authors; ``author_from_commits`` picks the first local commit's email;
``build_features_entry`` makes the ``features`` log entry (caps, no empty values).
Pure: no IO, no git.
"""
from __future__ import annotations

from vmn_exp.core.features_patch import parse_patch

FEATURES_VERSION = 1
CAPS = {"files": 200, "symbols": 500, "commits": 50, "untracked": 200}
# Who captured a features value, how and by which version: not facts of the code.
_PROVENANCE = ("author", "source", "features_version")


def features_from_patches(patch_texts) -> dict:
    """``{"changed": {"files", "symbols"}, "commits", "commit_authors"}`` of every
    text (deduplicated, capped; ``"truncated": True`` when a cap cut a list).

    An item may be a ``(prefix, text)`` pair, putting its paths under *prefix*
    (a dep's patches); empty items are skipped.
    """
    found = {"files": [], "symbols": [], "commits": [], "authors": []}
    for item in patch_texts:
        prefix, text = item if isinstance(item, tuple) else ("", item)
        if text and text.strip():
            for key, values in parse_patch(text, prefix).items():
                found[key].extend(values)
    files, cut_files = _capped(_unique(found["files"]), "files")
    symbols, cut_symbols = _capped(_unique(found["symbols"]), "symbols")
    commits, cut_commits = _capped(found["commits"], "commits")
    authors, cut_authors = _capped(found["authors"], "commits")
    result = {"changed": {"files": files, "symbols": symbols}, "commits": commits,
              "commit_authors": authors}
    if cut_files or cut_symbols or cut_commits or cut_authors:
        result["truncated"] = True
    return result


def author_from_commits(commit_authors) -> dict | None:
    """``{"git_user_email", "source": "commit"}`` of the first local commit with an email."""
    for author in commit_authors or ():
        email = (author.get("email") or "").strip()
        if email:
            return {"git_user_email": email, "source": "commit"}
    return None


def build_features_entry(source, author=None, changed=None, commits=None, **extra) -> dict:
    """The ``features`` log entry: caps applied, empty values (and empty
    ``author`` keys) dropped. A splatted ``features_from_patches`` result
    works: its ``commit_authors`` is not stored and its ``truncated`` is kept."""
    extra.pop("commit_authors", None)
    truncated = bool(extra.pop("truncated", False))
    entry = {"type": "features", "features_version": FEATURES_VERSION, "source": source}
    author = {k: v for k, v in (author or {}).items() if not _empty(v)}
    if author:
        entry["author"] = author
    kept_changed = {}
    for key, values in (changed or {}).items():
        kept, cut = _capped(_unique(values or ()), key)
        truncated = truncated or cut
        if kept:
            kept_changed[key] = kept
    if kept_changed:
        entry["changed"] = kept_changed
    kept_commits, cut = _capped(list(commits or ()), "commits")
    truncated = truncated or cut
    if kept_commits:
        entry["commits"] = kept_commits
    entry.update((k, v) for k, v in extra.items() if not _empty(v))
    if truncated:
        entry["truncated"] = True
    return entry


def code_facts(features) -> dict:
    """A features value minus its provenance: what a run of the same code
    (a rerun, a git-free run of an export) copies, ``{}`` for None."""
    return {k: v for k, v in (features or {}).items() if k not in _PROVENANCE}


def _unique(values) -> list:
    return list(dict.fromkeys(values))


def _capped(values: list, key: str):
    cap = CAPS.get(key)
    if cap is None or len(values) <= cap:
        return values, False
    return values[:cap], True


def _empty(value) -> bool:
    return value is None or (isinstance(value, (str, list, tuple, dict)) and not value)
