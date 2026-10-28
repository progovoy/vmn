#!/usr/bin/env python3
"""Registering a batch of runs of one code version (``vmn_exp.sdk.create_runs``).

The runs share their code identity, record template, parent, environment and
``features`` entry. Each costs the store its own claim (``create_exclusive``),
its parent's child marker and its create entry — params and tags in one
write — and the code version's runs are listed at most twice per batch.
"""
import collections
import threading

from vmn_exp._base import now_iso
from vmn_exp.core import run_hint
from vmn_exp.core.writer import (
    RunExistsError,
    _claim_made,
    _run_verstr_candidates,
    _taken_verstrs,
    check_run_id,
    create_tags_entry,
    default_run_suffix,
    env_yaml,
    flush_log,
    hinted_names,
    record_maker,
    template_with_env,
    write_create_entries,
    write_env_file,
)
from vmn_exp.storage.fanout import fan_out

SPEC_FIELDS = ("name", "params", "tags", "note", "run_id")


def run_specs(runs):
    """*runs* as dicts of every :data:`SPEC_FIELDS` key; ValueError for an
    unknown field, a bad tag key or a run id named twice."""
    specs = [_spec(run) for run in runs]
    ids = collections.Counter(s["run_id"] for s in specs if s["run_id"])
    twice = sorted(i for i, n in ids.items() if n > 1)
    if twice:
        raise ValueError(f"run_id given more than once: {', '.join(twice)}")
    return specs


def _spec(run):
    unknown = sorted(set(run) - set(SPEC_FIELDS))
    if unknown:
        raise ValueError(f"Unknown run fields {unknown}; expected {list(SPEC_FIELDS)}")
    spec = {key: run.get(key) for key in SPEC_FIELDS}
    if spec["tags"]:
        spec["tags"] = create_tags_entry(spec["tags"])["set"]
    return spec


def create_runs(storage, app_name, code_verstr, template, specs, *, parent=None,
                env=None, features=None, workers=16, exist_ok=False):
    """Create a run per spec (:func:`run_specs`); their verstrs, in order.

    A ``run_id`` is claimed exactly: RunExistsError when another record holds
    it — unless *exist_ok* and that record has the same parent and name, then
    it is returned as is. The others get the code version's next free names
    (:class:`_Names`).
    """
    for spec in specs:
        if spec["run_id"]:
            check_run_id(code_verstr, spec["run_id"])
    names = _Names(storage, app_name, code_verstr, {s["run_id"] for s in specs if s["run_id"]})
    planned = [s["run_id"] or names.next() for s in specs]
    batch = _Batch(storage, app_name, code_verstr, template_with_env(template, env),
                   parent, env_yaml(env), features, exist_ok, names)
    results = fan_out(batch.register, list(zip(specs, planned)), workers,
                      "vmn-create-runs")
    errors = [r for r in results if isinstance(r, Exception)]
    if errors:
        raise errors[0]
    _note_hint(storage, app_name, code_verstr, results)
    return results


class _Names:
    """Free-looking names for the batch's runs without a ``run_id``, from one
    iterator the claims share: past the last ``.rN`` this process claimed
    while that run exists, else from one listing. The first name another host
    took meanwhile lists once more; later ones just take the next name."""

    def __init__(self, storage, app_name, code_verstr, exclude):
        self._scope = (storage, app_name, code_verstr)
        self._suffix = default_run_suffix()
        self._exclude = set(exclude)  # the batch's run_ids, then every name handed out
        self._lock = threading.Lock()
        self._relisted = False
        self._free = None

    def next(self):
        with self._lock:
            if self._free is None:
                hinted = None if self._suffix else hinted_names(*self._scope)
                self._free = hinted if hinted is not None else self._listed()
            return self._take()

    def after_collision(self):
        with self._lock:
            if not self._relisted:
                self._relisted = True
                self._free = self._listed()
            return self._take()

    def _listed(self):
        taken = _taken_verstrs(*self._scope, self._suffix)
        return _run_verstr_candidates(self._scope[2], taken, self._suffix)

    def _take(self):
        name = next(n for n in self._free if n not in self._exclude)
        self._exclude.add(name)
        return name


def _note_hint(storage, app_name, code_verstr, verstrs):
    """Let a later ``.rN`` allocation of this process start past the batch."""
    numbers = [run_hint.run_number(code_verstr, v) for v in verstrs]
    numbers = [n for n in numbers if n]
    if numbers:
        run_hint.note(run_hint.hint_key(storage, app_name, code_verstr), max(numbers))


class _Batch:
    """What every run of a batch shares, and one run's registration."""

    def __init__(self, storage, app_name, code_verstr, template, parent, env_text,
                 features, exist_ok, names):
        self.storage, self.app_name, self.code_verstr = storage, app_name, code_verstr
        self.template, self.parent, self.env_text = template, parent, env_text
        self.features, self.exist_ok, self.names = features, exist_ok, names

    def register(self, item):
        """The run's verstr, or the RunExistsError its run id met."""
        spec, name = item
        template = dict(self.template, note=spec["note"], timestamp=now_iso())
        make_record = record_maker(template, self.code_verstr, self.parent, spec["name"])
        while not _claim_made(self.storage, self.app_name, name, make_record):
            if spec["run_id"]:
                return self._existing(spec)
            name = self.names.after_collision()
        write_env_file(self.storage, self.app_name, name, self.env_text)
        write_create_entries(self.storage, self.app_name, name,
                             _create_data(spec), spec["note"], self.features)
        flush_log(self.storage, self.app_name, name)  # a scratch dir's pods are elsewhere
        return name

    def _existing(self, spec):
        run_id = spec["run_id"]
        if self.exist_ok:
            meta = self.storage.load_metadata(self.app_name, run_id) or {}
            same = (meta.get("parent"), meta.get("name")) == (
                self.parent, str(spec["name"]) if spec["name"] else None)
            if same:
                return run_id
        return RunExistsError(f"Run '{run_id}' already exists for {self.app_name}")


def _create_data(spec):
    data = {}
    if spec["params"]:
        data["params"] = dict(spec["params"])
    if spec["tags"]:
        data["tags"] = spec["tags"]
    return data
