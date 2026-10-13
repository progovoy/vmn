#!/usr/bin/env python3
"""Nesting for experiments: outer jobs (sweeps, orchestrators) and the inner
jobs they spawn.

An experiment records the verstr of the run that launched it in its metadata as
``parent``. This module folds a flat list of rows into that shape — who has
children, how deep a run sits, and what an outer job's *effective* status is
once its whole subtree is taken into account.

Pure: rows in, new rows out, no storage. :func:`subtree_status` reads run
states only through the reader its caller passes in.
"""
from collections import Counter

from vmn_exp.core.status import (
    CREATED,
    FAILED,
    RUNNING,
    STUCK,
    SUCCEEDED,
    derive_status,
    status_fields,
)

OUTER = "outer"  # has children
INNER = "inner"  # has a parent
SINGLE = "single"  # neither

# What a mixed subtree reports. A single failure is the headline; an unfinished
# run outranks a clean one, because the subtree isn't done yet.
_PRECEDENCE = (FAILED, STUCK, RUNNING, CREATED, SUCCEEDED)


def rollup_status(statuses):
    """The single status that best describes a set of runs, or None if empty."""
    statuses = {s for s in statuses if s}
    return next((c for c in _PRECEDENCE if c in statuses), None)


def children_by_parent(nodes):
    """``{parent verstr: [child verstr]}`` — a run is never its own child."""
    children_of = {}
    for node in nodes:
        parent = node.get("parent")
        if parent and parent != node["verstr"]:
            children_of.setdefault(parent, []).append(node["verstr"])
    return children_of


def subtree_verstrs(verstr, children_of):
    """*verstr* and everything below it, cycle-safe."""
    seen, stack, out = set(), [verstr], []
    while stack:
        current = stack.pop()
        if current in seen:
            continue
        seen.add(current)
        out.append(current)
        stack.extend(children_of.get(current, []))
    return out


def ancestors(verstr, parent_of):
    """*verstr*'s parent chain, nearest first (its length is the run's
    depth): a missing parent ends it, a cycle stops at its entry point."""
    chain, seen, cursor = [], {verstr}, parent_of.get(verstr)
    while cursor and cursor not in seen:
        chain.append(cursor)
        seen.add(cursor)
        cursor = parent_of.get(cursor)
    return chain


def ancestry_of(rows):
    """``verstr -> ancestors`` over *rows*' own ``parent`` links."""
    parent_of = {r["verstr"]: r.get("parent") for r in rows if r.get("parent")}
    return lambda verstr: ancestors(verstr, parent_of)


def own_rollup_status(status, has_children, incomplete=False):
    """What a run's own *status* adds to its tree's rollup: nothing (None)
    for a container — an outer run that never ran itself — and ``created``
    on top for an *incomplete* sweep (see :func:`sweep_incomplete`)."""
    own = None if has_children and status == CREATED else status
    return rollup_status((own, CREATED)) if incomplete else own


def sweep_trial_count(children):
    """How many trial slots a sweep's child rows fill (a retry counts once)."""
    return len({(c.get("tags") or {}).get("sweep_trial", c.get("verstr")) for c in children})


def sweep_incomplete(row):
    """Whether *row* is a sweep whose planned size (``sweep_planned``, put on
    the row by the index) is more than the trials it has (``sweep_trials``)."""
    planned = row.get("sweep_planned")
    return planned is not None and row.get("sweep_trials", 0) < planned


def _own(verstr, children_of, by_verstr):
    row = by_verstr.get(verstr) or {}
    return own_rollup_status(
        row.get("status"), bool(children_of.get(verstr)), sweep_incomplete(row)
    )


def _subtree_statuses(verstr, children_of, by_verstr):
    """What *verstr* and everything reachable below it add to its rollup
    (cycle-safe): a container outer adds nothing, so if all its children
    succeeded the tree is ``succeeded``."""
    return [_own(v, children_of, by_verstr) for v in subtree_verstrs(verstr, children_of)]


def _has_cycle(verstrs, parent_of):
    """Whether any parent chain from *verstrs* loops back on itself."""
    done = set()
    for start in verstrs:
        path, cursor = set(), start
        while cursor and cursor not in done:
            if cursor in path:
                return True
            path.add(cursor)
            cursor = parent_of.get(cursor)
        done |= path
    return False


def _tree_statuses(verstrs, children_of, by_verstr, parent_of):
    """``{verstr: rollup over its subtree}``, linear for any acyclic forest."""
    if _has_cycle(verstrs, parent_of):
        return {
            v: rollup_status(_subtree_statuses(v, children_of, by_verstr))
            for v in verstrs
        }
    rank = {status: i for i, status in enumerate(_PRECEDENCE)}
    best = {}
    for root in verstrs:
        # Post-order without recursion: a node is ranked after its children.
        stack = [(root, False)]
        while stack:
            node, expanded = stack.pop()
            if node in best:
                continue
            children = children_of.get(node, [])
            if not expanded:
                stack.append((node, True))
                stack.extend((c, False) for c in children if c not in best)
                continue
            own = rank.get(_own(node, children_of, by_verstr), len(rank))
            best[node] = min([own] + [best[c] for c in children])
    return {v: (_PRECEDENCE + (None,))[best[v]] for v in verstrs}


def annotate_tree(rows):
    """Add ``children``, ``kind``, ``depth``, ``root`` (the top-level
    ancestor, None for a top-level run) and ``tree_status`` to each row.

    ``status`` is left as the row's own status; ``tree_status`` is the rollup
    over the row and everything beneath it.
    """
    return _annotate_tree_in_place([dict(r) for r in rows])


def annotate_rows(rows, run_states, observed_at=None, now=None):
    """Copies of *rows* with their derived status fields and tree fields.

    *run_states* is ``{verstr: raw run state}``, *observed_at* ``{verstr:
    run_state.yml store write time}``. Time-dependent: never cache the output.
    """
    run_states = run_states or {}
    observed_at = observed_at or {}
    return _annotate_tree_in_place([
        dict(row, **status_fields(
            run_states.get(row["verstr"]), now=now,
            observed_at=observed_at.get(row["verstr"]),
        ))
        for row in rows
    ])


def _annotate_tree_in_place(rows):
    by_verstr = {r["verstr"]: r for r in rows}
    parent_of = {r["verstr"]: r.get("parent") for r in rows if r.get("parent")}

    children_of = children_by_parent(rows)
    for row in rows:
        if row.get("sweep_planned") is not None:
            kids = children_of.get(row["verstr"], [])
            row["sweep_trials"] = sweep_trial_count(by_verstr[c] for c in kids)
    tree_statuses = _tree_statuses(list(by_verstr), children_of, by_verstr, parent_of)

    for row in rows:
        verstr = row["verstr"]
        children = children_of.get(verstr, [])
        row["children"] = children
        if children:
            row["kind"] = OUTER
        elif row.get("parent"):
            row["kind"] = INNER
        else:
            row["kind"] = SINGLE
        chain = ancestors(verstr, parent_of)
        row["depth"] = len(chain)
        row["root"] = chain[-1] if chain else None
        row["tree_status"] = tree_statuses[verstr]
        row["child_counts"] = count_statuses(
            (by_verstr.get(c) or {}).get("status") for c in children
        )
    return rows


def count_statuses(statuses):
    """``{status: n}`` over *statuses* — an outer run's inner-run tally."""
    return dict(Counter(statuses))


TREE_FIELDS = ("children", "kind", "depth", "tree_status", "child_counts")


def subtree_status(
    verstr, parent_of, read_state, children_of=None, observed_at=None, row_of=None,
):
    """``(run_state, tree_fields)`` for one run, reading its subtree's states only.

    *parent_of* is ``{verstr: parent}`` for the app's runs (only ``.get`` is
    used when *children_of* — ``{parent: [child]}``, as
    :func:`children_by_parent` builds it — is passed in); *read_state(verstr)*
    returns a raw run state and is called once per subtree member. Ancestors
    are walked for ``depth`` but never read. *observed_at(verstr)*, when
    given, returns the store's write time of a member's run state (see
    :func:`~version_stamp.core.experiment_status.derive_status`).
    *row_of(verstr)*, when given, returns a run's index row (or None): a sweep
    row's ``sweep_planned`` and its trials' tags make an incomplete sweep
    ``created`` (see :func:`sweep_incomplete`) and add ``sweep_planned`` /
    ``sweep_trials`` to the tree fields.
    """
    if children_of is None:
        children_of = children_by_parent(
            [{"verstr": v, "parent": p} for v, p in parent_of.items()]
        )
    states = {v: read_state(v) for v in subtree_verstrs(verstr, children_of)}
    children = list(children_of.get(verstr, []))
    parent = parent_of.get(verstr)

    def status_of(v):
        return derive_status(states[v], observed_at=observed_at(v) if observed_at else None)

    sweep = _sweep_fields(verstr, children, row_of)
    own = own_rollup_status(status_of(verstr), bool(children), sweep_incomplete(sweep))
    below = (status_of(v) for v in states if v != verstr)
    tree = {
        "children": children,
        "kind": OUTER if children else (INNER if parent else SINGLE),
        "depth": len(ancestors(verstr, parent_of)),
        "tree_status": rollup_status([own, *below]),
        "child_counts": count_statuses(status_of(c) for c in children),
        **sweep,
    }
    return states[verstr], tree


def _sweep_fields(verstr, children, row_of):
    """``{sweep_planned, sweep_trials}`` of a sweep row *row_of* knows, else {}."""
    planned = ((row_of(verstr) if row_of else None) or {}).get("sweep_planned")
    if planned is None:
        return {}
    rows = ((row_of(c) or {"verstr": c}) for c in children)
    return {"sweep_planned": planned, "sweep_trials": sweep_trial_count(rows)}


def run_status(verstr, parent_of, read_state, observed_at=None, children_of=None, row_of=None):
    """One run's status fields plus its tree fields, reading its subtree only.

    Arguments as for :func:`subtree_status`; *observed_at(verstr)* weighs the
    store's write time into the run's own status as well as the rollup.
    """
    run_state, tree = subtree_status(
        verstr, parent_of, read_state, children_of=children_of, observed_at=observed_at,
        row_of=row_of,
    )
    status = status_fields(run_state, observed_at=observed_at(verstr) if observed_at else None)
    status.update(tree)
    return status


FLEET_MAX_CHILDREN_DETAIL = 50


def _number_of(row, key):
    """*row*'s numeric ``metrics[key]``, else ``params[key]``, else None."""
    for source in (row.get("metrics") or {}, row.get("params") or {}):
        value = source.get(key)
        if isinstance(value, (int, float)):
            return value
    return None


def _child_row_fields(row):
    """What the fleet table shows of a child from its index *row*."""
    return {
        "idx": row.get("idx"),
        "name": row.get("name"),
        "params": row.get("params") or {},
        "metrics": row.get("metrics") or {},
        "progress": _number_of(row, "progress"),
        "progress_total": _number_of(row, "progress_total"),
    }


def fleet_summary(verstr, children_of, read_state, observed_at=None, expected=None, read_child_row=None):
    """Fleet status for an outer run: per-child status counts and progress.

    Returns None when *verstr* has no children. *expected* is the declared
    pod count (from the parent's ``expected_pods`` param); defaults to the
    number of children. *read_child_row(verstr)* returns an indexed row
    dict for a child (its ``idx``/``name``/``params``/``metrics`` and
    progress), or None.
    """
    children = children_of.get(verstr, [])
    if not children:
        return None

    child_details = []
    statuses = []
    for child in children:
        state = read_state(child)
        obs = observed_at(child) if observed_at else None
        status = derive_status(state, observed_at=obs)
        statuses.append(status)

        if len(child_details) < FLEET_MAX_CHILDREN_DETAIL:
            row = (read_child_row(child) if read_child_row else None) or {}
            child_details.append(dict(_child_row_fields(row), verstr=child, status=status))

    if expected is None:
        expected = len(children)
    else:
        expected = max(expected, len(children))

    counts = count_statuses(statuses)
    known = sum(counts.values())
    waiting = max(0, expected - known)

    return {
        "expected": expected,
        "counts": {
            RUNNING: counts.get(RUNNING, 0),
            SUCCEEDED: counts.get(SUCCEEDED, 0),
            FAILED: counts.get(FAILED, 0),
            STUCK: counts.get(STUCK, 0),
            CREATED: counts.get(CREATED, 0),
            "waiting": waiting,
        },
        "children": child_details,
    }
