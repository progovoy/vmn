#!/usr/bin/env python3
"""``vmn-exp similar-backfill <app> [--all-apps] [--dry-run]``: give runs
recorded without features the ``features`` entry their code implies
(docs/plans/18-similar-runs.md §3.5).

Every run without a ``features`` entry at the current ``FEATURES_VERSION``
qualifies (runs from before features existed, a capture that failed, an entry
of an older version) except live (running/stuck) runs and imports. The entry
(``source: backfill``) is derived from the text patches of the run's code
alone, never its untracked tarball, each code object read and parsed once, and
appended under this host's writer id. What an older entry observed at
submission (author, branch, untracked paths, ...) is carried over; only the
patch-derived ``changed``/``commits`` are recomputed. Without one, the author
is the first local commit's ``From:`` and the writer that created the run (a
run ``vmn-exp migrate`` converted from v1 names its run state's ``host``).

A clean tree's entry, with nothing changed, is complete; a run whose code
object is gone counts as ``partial`` and gets one without ``changed`` — or
with its older entry's. Code the store lists but could not read fails the run
(nothing written: the next backfill retries it), as does any other error of
one run, a malformed run state included.
"""
from collections import Counter, defaultdict

from vmn_exp._base import VMN_LOGGER
from vmn_exp.cli.migrate_convert import LEGACY_WRITER
from vmn_exp.cli.views import plural
from vmn_exp.core import index as experiment_index
from vmn_exp.core.code_patches import (
    CodeReadError,
    code_patch_texts,
    patch_items,
    record_patch_texts,
    run_dep_paths,
    unreadable_code_keys,
)
from vmn_exp.core.code_store import code_storage, find_code_key
from vmn_exp.core.features import author_from_commits, build_features_entry, is_current
from vmn_exp.core.provenance import _has_in_record_patches
from vmn_exp.core.rerun import _dirty_snapshot, code_verstr_of
from vmn_exp.core.status import RUNNING, STUCK
from vmn_exp.core.writer import flush_log, get_writer_id, stamped_entry
from vmn_exp.gitmode.features import features_from_patches  # without vmn's own commits

BACKFILLED, PARTIAL, SKIPPED, FAILED = "backfilled", "partial", "skipped", "failed"
SOURCE = "backfill"
# What a features entry says that the run's patches can tell again.
_PATCH_DERIVED = ("features_version", "source", "changed", "commits", "truncated",
                  "changed_source")
# What the new entry restates whatever it carries over.
_RESTATED = ("features_version", "source")


def experiment_similar_backfill(storage, app_name, args):
    dry_run = bool(getattr(args, "dry_run", False))
    all_apps = bool(getattr(args, "all_apps", False))
    counts = Counter()
    for app in storage.list_apps() if all_apps else [app_name]:
        if all_apps:
            print(f"{app}:")
        for verstr, status, detail in backfill_app(storage, app, dry_run):
            print(f"{verstr}  {status}" + (f" ({detail})" if detail else ""))
            counts[status] += 1
    summary = ", ".join(f"{s} {counts[s]}" for s in (BACKFILLED, PARTIAL, SKIPPED, FAILED))
    print(summary + (" (dry run: nothing written)" if dry_run else ""))
    return 1 if counts[FAILED] else 0


def backfill_app(storage, app_name, dry_run=False):
    """``(verstr, status, detail)`` per run of *app_name*, in storage order;
    *dry_run* derives every entry and appends none."""
    snap = experiment_index.indexed_snapshot(storage, app_name, wait=True)
    code = _CodeFeatures(storage, app_name)
    for row in snap.rows:
        verstr = row["verstr"]
        try:
            reason = _skip_reason(snap, row)
            if reason:
                yield verstr, SKIPPED, reason
                continue
            status, detail, entry = _derive(storage, app_name, verstr,
                                            snap.features_of(verstr), code,
                                            snap.run_states.get(verstr))
            if not dry_run:
                _append(storage, app_name, verstr, entry)
        except Exception as exc:
            VMN_LOGGER.debug(f"Backfilling {verstr} failed", exc_info=True)
            yield verstr, FAILED, str(exc) or type(exc).__name__
            continue
        yield verstr, status, detail


def _skip_reason(snap, row):
    verstr = row["verstr"]
    if is_current(snap.features_of(verstr)):
        return "up to date"
    if row.get("imported_from"):
        return "imported"
    status = snap.status_of(verstr)
    return status if status in (RUNNING, STUCK) else None


def _derive(storage, app_name, verstr, older, code, run_state):
    """``(status, detail, features entry)`` of one run."""
    metadata = storage.load_metadata(app_name, verstr)
    if metadata is None:
        raise RuntimeError("the record is gone")
    parsed, missing = code.of(metadata)

    def creator():
        return _creator(storage, app_name, verstr, run_state)

    if missing:
        return PARTIAL, missing, _entry(older, None, creator)
    entry = _entry(older, parsed or {}, creator)
    return BACKFILLED, _counts(entry) if parsed else "clean tree", entry


def _entry(older, parsed, creator):
    """The new entry: *parsed* patches' changes over what *older* observed —
    all of which it keeps when *parsed* is None (the code is gone); *creator*
    names the run's creating writer when the author is unknown."""
    older = older or {}
    carried = {k: v for k, v in older.items()
               if k not in (_RESTATED if parsed is None else _PATCH_DERIVED)}
    if not carried.get("author"):
        author = dict(author_from_commits((parsed or {}).get("commit_authors")) or {})
        carried["author"] = dict(author, writer=creator())
    if parsed is None:
        return build_features_entry(SOURCE, **carried)
    untracked = (older.get("changed") or {}).get("untracked")
    changed = dict(parsed.get("changed") or {}, untracked=untracked)
    return build_features_entry(SOURCE, changed=changed, commits=parsed.get("commits"),
                                truncated=parsed.get("truncated", False), **carried)


def _creator(storage, app_name, verstr, run_state):
    """The writer whose log holds the run's first ``create`` entry, or None.
    The v1 migration's pseudo-writer is no host: its run state's ``host`` is."""
    creates = sorted(
        (entry.get("timestamp") or "", writer)
        for writer, entries in storage.load_logs_by_writer(app_name, verstr).items()
        for entry in entries
        if entry.get("type") == "create"
    )
    writer = creates[0][1].strip() if creates else None
    if writer != LEGACY_WRITER:
        return writer
    host = (run_state or {}).get("host")
    return str(host).strip() if host else None


def _counts(entry):
    changed = entry.get("changed") or {}
    parts = [(len(changed.get("files") or ()), "file"),
             (len(changed.get("symbols") or ()), "symbol"),
             (len(entry.get("commits") or ()), "commit")]
    return ", ".join(plural(n, noun) for n, noun in parts)


def _append(storage, app_name, verstr, entry):
    log_entry = stamped_entry(entry)
    if storage.append_log_entry(app_name, verstr, get_writer_id(), log_entry) is False:
        raise RuntimeError("the record is gone")
    # One-shot command: no heartbeat will ship the entry to a remote later.
    flush_log(storage, app_name, verstr)


class _CodeFeatures:
    """The parsed patches of an app's runs' code; each code object is read and
    parsed once, an exported snapshot's code verstr looked up once."""

    def __init__(self, storage, app_name):
        self._storage = storage
        self._app = app_name
        self._parsed = {}  # code key -> features_from_patches result, None = missing
        self._keys = {}  # code verstr -> its one code object's key, or None
        self._names = None  # code verstr -> its code objects' keys, listed once

    def of(self, metadata):
        """``(parsed patches, None)``, ``(None, None)`` for a clean tree, or
        ``(None, why the code is missing)``."""
        key = metadata.get("code")
        if key:
            return self._object(key, metadata, f"code object {key} is missing")
        if _dirty_snapshot(metadata):
            code_verstr = code_verstr_of(metadata)
            if code_verstr not in self._keys:
                self._keys[code_verstr] = self._find_key(code_verstr)
            missing = f"no code object of {code_verstr} in the store"
            key = self._keys[code_verstr]
            return self._object(key, metadata, missing) if key else (None, missing)
        if _has_in_record_patches(metadata):
            patches = record_patch_texts(self._storage, self._app, metadata["verstr"],
                                         run_dep_paths(metadata))
            return features_from_patches(patch_items(patches)), None
        return None, None

    def _find_key(self, code_verstr):
        """The one complete code object of *code_verstr*; CodeReadError when
        there is none to be found because the store could not read one."""
        names = self._code_names().get(code_verstr, [])
        key = find_code_key(self._storage, self._app, code_verstr, names)
        if key is None:
            unread = unreadable_code_keys(self._storage, self._app, code_verstr, names)
            if unread:
                raise CodeReadError(f"could not read code object {', '.join(unread)}")
        return key

    def _code_names(self):
        if self._names is None:
            self._names = defaultdict(list)
            for key in code_storage(self._storage).list_record_names(self._app):
                self._names[key.rsplit(".", 1)[0]].append(key)
        return self._names

    def _object(self, key, metadata, missing):
        if key not in self._parsed:
            patches = code_patch_texts(self._storage, self._app, key, run_dep_paths(metadata))
            self._parsed[key] = (
                None if patches is None else features_from_patches(patch_items(patches)))
        parsed = self._parsed[key]
        return (parsed, None) if parsed is not None else (None, missing)
