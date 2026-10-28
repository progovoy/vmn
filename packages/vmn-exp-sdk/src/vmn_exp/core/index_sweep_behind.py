#!/usr/bin/env python3
"""How a journaled :class:`~vmn_exp.core.index_sweep.Sweep` catches up
without listing every record under the index lock.

* **Journal mark.** The journal says how far it has hinted (:meth:`journal_at`,
  the reader's cursor); a refresh that took every hint up to it has the
  records of that point (:meth:`persistable_mark`, which the index persists
  with them). A restart whose mark the journal still covers
  :meth:`resume`\\s from the persisted records — no full listing — while the
  journal replays the entries since the mark as hints.
* **Behind serving.** With ``behind`` (a remote store, listed in-process) a
  due full listing is a :class:`~vmn_exp.core.index_relist.Relisting`: each
  refresh applies what it listed so far, its hints and live records too,
  ``RELIST_PER_REFRESH`` records at a time, the newest first. A cold index
  (no records to serve) does not wait for it either: it loads what is listed
  as it comes (:meth:`relisted_ready`, :meth:`next_relisted`), while a
  request gets its empty snapshot that says how many records it expects
  (:meth:`relisted_new`).
* **Overflow.** A journal tick with too many entries for the app hints the
  names it saw and lists the record names (:meth:`overflowed`), never every
  record's files.

Hints are taken ``HINTS_PER_REFRESH`` at a time, so a burst of them (an
overflow, a replay) is spread over refreshes instead of one long hold of the
lock.
"""
from vmn_exp.core import index_relist
from vmn_exp.core.index_freshness import FULL_LISTING, JOURNAL
from vmn_exp.core.index_lazy import has_meta
from vmn_exp.core.index_listing import METADATA_FILE
from vmn_exp.core.index_sweep_state import _settled

HINTS_PER_REFRESH = 2000
RELIST_PER_REFRESH = 2000


class SweepBehind:
    behind = False  # list fully in a Relisting (the index says, per refresh)
    _relisting = None
    _hint_mark = None  # the journal's position its hints so far reach
    mark_taken = None  # the position the hints taken so far reach
    _resume_pending = _awaiting_replay = _names_wanted = False

    def journal_at(self, ms):
        """Every journal entry up to *ms* (the reader's cursor) was hinted."""
        with self._hint_lock:
            self._hint_mark = ms
            self._awaiting_replay = False

    def resume(self):
        """Carry on from the persisted records without a full listing: the
        journal replays what changed since their mark."""
        self._resume_pending = self._awaiting_replay = True

    def overflowed(self, names):
        """The journal named too many records at once, *names*: hint them and
        list the record names for what it missed."""
        with self._hint_lock:
            self._hinted.update(names)
        self._names_wanted = True

    def persistable_mark(self):
        """The journal position the records stand at, or None while they
        might not (no full listing or resume yet, one under way, a replay
        awaited)."""
        relisting = self._relisting
        if self._last_full is None or self._awaiting_replay or (relisting and relisting.files):
            return None
        return self.mark_taken

    def listing_phase(self):
        """``("full_listing", share listed or None)``, ``("journal", None)``
        while catching up on the journal, else None."""
        relisting = self._relisting
        if relisting is not None and relisting.files:
            return FULL_LISTING, relisting.progress()
        if relisting or self._awaiting_replay or self._resume_pending or self._names_wanted:
            return JOURNAL, None
        return (JOURNAL, None) if self._hinted else None

    def _take_hint_batch(self):
        return self._take_hints(HINTS_PER_REFRESH)

    def _take_hints(self, limit=None):
        with self._hint_lock:
            if limit is not None and len(self._hinted) > limit:
                hinted = set()
                while len(hinted) < limit:
                    hinted.add(self._hinted.pop())
            else:
                hinted, self._hinted = self._hinted, set()
                self.mark_taken = self._hint_mark
        self._took(hinted)
        return hinted

    def _begin_journaled(self, records, now):
        if self._resume_pending:
            self._resume_pending = False
            if self._last_full is None:
                self._last_full = self._rolled_at = now
                self._judge_all_live(records)
                self._unprinted = set(records)
        if self._names_wanted:
            if self.behind:
                self._relist(records, files=False)
            else:
                self._hint_unlisted(records, self.watch.record_names())
            self._names_wanted = False

    def _hint_unlisted(self, records, names):
        if names is None:
            self.request_full()
            return
        with self._hint_lock:
            self._hinted.update((names - records.keys() - self._pending) | (records.keys() - names))

    def _judge_all_live(self, records):
        if self._live is None:
            self._live = {k for k, r in records.items() if has_meta(r) and not _settled(r)}

    def _relist(self, records, files):
        """Start a relisting, unless one that covers it is under way."""
        current = self._relisting
        if current is not None and (current.files or not files):
            return
        self._judge_all_live(records)
        self._relisting = index_relist.Relisting(self.watch, records.keys(), files)
        if files:
            self.last_reconcile_at = self._relisting.started_at

    def relisted_ready(self):
        """Whether a files relisting under way has listed records not taken
        yet (no journal hint waiting: the next refresh serves those first)."""
        relisting = self._relisting
        return (relisting is not None and relisting.files and relisting.ready()
                and not self._hinted)

    def next_relisted(self, records, now):
        """``(files to refresh, keys gone)`` of the next relisted records."""
        checked, gone = self._relisted(records, now)
        self._pending |= {k for k, files in checked.items() if METADATA_FILE not in files}
        return checked, [key for key in gone if key in records]

    def relisted_new(self):
        """While a files relisting runs behind serving, ``(records known,
        new names listed, of those not handed over yet)`` — None while a
        cold one named none yet; False when none runs."""
        relisting = self._relisting
        if relisting is None or not relisting.files:
            return False
        return relisting.new_names()

    def hints_waiting(self):
        """Whether journal hints wait for the next listing."""
        return bool(self._hinted)

    def wait_relisted(self, timeout):
        """Until a files relisting under way has records to take (or ends),
        at most *timeout* seconds."""
        relisting = self._relisting
        if relisting is not None and relisting.files:
            relisting.wait_ready(timeout)

    def _hinted_files(self, keys):
        files = self.watch.files
        listing = index_relist.files_of(files, keys) if self.behind else files(keys)
        if self._relisting is not None:
            self._relisting.saw(keys)
        return listing

    def _relisted(self, records, now):
        """``(files of the relisted records that changed, keys gone)`` of
        what the relisting under way listed since the last refresh."""
        relisting = self._relisting
        try:
            keys, files, done = relisting.take(RELIST_PER_REFRESH)
        except Exception:
            self._relisting = None  # the next refresh starts another
            self._names_wanted |= not relisting.files
            raise
        if done:
            self._relisting = None
        with self._hint_lock:
            self._hinted.update(relisting.take_refused())
            if not relisting.files:
                self._hinted.update(keys)
                return {}, set()
        self._took(keys)
        if done:
            self._listed_fully(now)
        changed, _ = self.watch.listed_changes(keys, files)
        return changed, {key for key in keys if METADATA_FILE not in files.get(key, {})}

    def _listed_fully(self, now):
        self._last_full = self._rolled_at = now
        self._restored, self._unprinted = False, set()
