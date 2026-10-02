"""``vmn-exp push <app> [-v <ref>...] [--dry-run] [--json]``: upload the local
root's runs (e.g. recorded under ``VMN_EXP_OFFLINE``) to the remote store.

The target is the store the flags, ``VMN_EXPERIMENT_STORE`` or conf name;
``VMN_EXP_OFFLINE`` never hides it here. Each run goes through
:func:`vmn_exp.core.push_rename.push_or_rename`, parents before children.
``--dry-run`` reads the ledger and one remote metadata object per run that
is not up to date, and writes nothing.
"""
import json
from collections import Counter
from dataclasses import asdict

from vmn_exp._base import VMN_LOGGER
from vmn_exp.core.fork import resolve_run
from vmn_exp.core.push_code import CodePusher
from vmn_exp.core.push_ledger import PushLedger
from vmn_exp.core.push_plan import parents_first, plan_push
from vmn_exp.core.push_rename import SKIPPED, push_or_rename
from vmn_exp.core.push_run import (
    COLLISION, FAILED, NEW, UP_TO_DATE, UPDATE, Outcome, require_push_target,
)
from vmn_exp.core.storage_resolve import experiment_dir, store_uri
from vmn_exp.registry.view import registered_runs
from vmn_exp.storage.areas import RUNS
from vmn_exp.storage.local import LocalSnapshotStorage
from vmn_exp.storage.registry import open_store

_NO_REMOTE = (
    "exp push needs a remote store: pass --store (or --bucket), or set "
    "VMN_EXPERIMENT_STORE or conf experiment.storage.uri"
)


def experiment_push(vcs, params, app_name, args):
    try:
        local, target = _stores(vcs, params)
        verstrs = _select(local, app_name, getattr(args, "version", None))
    except ValueError as exc:
        VMN_LOGGER.error(str(exc))
        return 1
    ledger = PushLedger.for_target(local, app_name, target)
    if args.dry_run:
        outcomes = [Outcome(v, plan_push(local, target, app_name, v, ledger))
                    for v in verstrs]
    else:
        code = CodePusher(local, target, app_name)
        registered = registered_runs(local)
        outcomes = [push_or_rename(local, target, app_name, v, ledger, code, registered)
                    for v in verstrs]
    failed = _report(outcomes, args.json, args.dry_run)
    return 1 if failed else 0


def _stores(vcs, params):
    uri = store_uri(params)
    root = experiment_dir(vcs, params)
    if not uri or not root:
        raise ValueError(_NO_REMOTE if root else "exp push needs a local experiment dir")
    target = open_store(uri, area=RUNS)
    require_push_target(target)
    return LocalSnapshotStorage(root, RUNS), target


def _select(local, app_name, refs):
    """The runs to push, parents first: *refs* resolved, else every local run."""
    if refs:
        verstrs = list(dict.fromkeys(resolve_run(local, app_name, r, "push") for r in refs))
        metas = {v: local.load_metadata(app_name, v) or {} for v in verstrs}
    else:
        runs = sorted(local.list_snapshots(app_name),
                      key=lambda m: (m.get("timestamp") or "", m["verstr"]))
        metas = {m["verstr"]: m for m in runs}
        verstrs = list(metas)
    return parents_first(verstrs, lambda v: metas[v].get("parent"))


def _report(outcomes, as_json, dry_run):
    """Print *outcomes*; the number that failed."""
    for outcome in outcomes:
        for warning in outcome.warnings:
            VMN_LOGGER.warning(f"{outcome.verstr}: {warning}")
    failed = sum(o.status == FAILED or (o.status == COLLISION and not dry_run)
                 for o in outcomes)
    if as_json:
        print(json.dumps([asdict(o) for o in outcomes], indent=2))
        return failed
    for outcome in outcomes:
        print(_line(outcome))
    counts = Counter(o.status for o in outcomes)
    renamed = sum(bool(o.renamed_from) or (dry_run and o.status == COLLISION)
                  for o in outcomes)
    print(f"pushed {counts[NEW] + counts[UPDATE]}, up-to-date {counts[UP_TO_DATE]}, "
          f"renamed {renamed}, skipped {counts[SKIPPED]}, failed {failed}")
    return failed


def _line(outcome):
    text = f"{outcome.renamed_from or outcome.verstr}  {outcome.status}"
    if outcome.renamed_from:
        text += f" -> {outcome.verstr}"
    if outcome.detail:
        text += f" ({outcome.detail})"
    return text
