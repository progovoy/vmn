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
from version_stamp.core.experiment_status import (
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


def _depth(verstr, parent_of):
    """Distance to the top of the parent chain. A cycle stops at its entry point."""
    depth = 0
    seen = {verstr}
    cursor = verstr
    while True:
        parent = parent_of.get(cursor)
        if not parent or parent in seen:
            return depth
        depth += 1
        seen.add(parent)
        cursor = parent


def _subtree_statuses(verstr, children_of, by_verstr):
    """Own statuses of *verstr* and everything reachable below it (cycle-safe)."""
    return [
        (by_verstr.get(v) or {}).get("status")
        for v in subtree_verstrs(verstr, children_of)
    ]


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
            own = rank.get((by_verstr.get(node) or {}).get("status"), len(rank))
            best[node] = min([own] + [best[c] for c in children])
    return {v: (_PRECEDENCE + (None,))[best[v]] for v in verstrs}


def annotate_tree(rows):
    """Add ``children``, ``kind``, ``depth`` and ``tree_status`` to each row.

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
        row["depth"] = _depth(verstr, parent_of)
        row["tree_status"] = tree_statuses[verstr]
    return rows


TREE_FIELDS = ("children", "kind", "depth", "tree_status")


def subtree_status(verstr, parent_of, read_state, children_of=None, observed_at=None):
    """``(run_state, tree_fields)`` for one run, reading its subtree's states only.

    *parent_of* is ``{verstr: parent}`` for the app's runs (only ``.get`` is
    used when *children_of* — ``{parent: [child]}``, as
    :func:`children_by_parent` builds it — is passed in); *read_state(verstr)*
    returns a raw run state and is called once per subtree member. Ancestors
    are walked for ``depth`` but never read. *observed_at(verstr)*, when
    given, returns the store's write time of a member's run state (see
    :func:`~version_stamp.core.experiment_status.derive_status`).
    """
    if children_of is None:
        children_of = children_by_parent(
            [{"verstr": v, "parent": p} for v, p in parent_of.items()]
        )
    states = {v: read_state(v) for v in subtree_verstrs(verstr, children_of)}
    children = list(children_of.get(verstr, []))
    parent = parent_of.get(verstr)
    tree = {
        "children": children,
        "kind": OUTER if children else (INNER if parent else SINGLE),
        "depth": _depth(verstr, parent_of),
        "tree_status": rollup_status(
            derive_status(s, observed_at=observed_at(v) if observed_at else None)
            for v, s in states.items()
        ),
    }
    return states[verstr], tree


def run_status(verstr, parent_of, read_state, observed_at=None, children_of=None):
    """One run's status fields plus its tree fields, reading its subtree only.

    Arguments as for :func:`subtree_status`; *observed_at(verstr)* weighs the
    store's write time into the run's own status as well as the rollup.
    """
    run_state, tree = subtree_status(
        verstr, parent_of, read_state, children_of=children_of, observed_at=observed_at
    )
    status = status_fields(run_state, observed_at=observed_at(verstr) if observed_at else None)
    status.update(tree)
    return status


FLEET_MAX_CHILDREN_DETAIL = 50


def fleet_summary(verstr, children_of, read_state, observed_at=None, expected=None, read_child_row=None):
    """Fleet status for an outer run: per-child status counts and progress.

    Returns None when *verstr* has no children. *expected* is the declared
    pod count (from the parent's ``expected_pods`` param); defaults to the
    number of children. *read_child_row(verstr)* returns an indexed row
    dict for a child (used for per-child progress), or None.
    """
    children = children_of.get(verstr, [])
    if not children:
        return None

    child_details = []
    counts = {}
    for child in children:
        state = read_state(child)
        obs = observed_at(child) if observed_at else None
        status = derive_status(state, observed_at=obs)
        counts[status] = counts.get(status, 0) + 1

        if len(child_details) < FLEET_MAX_CHILDREN_DETAIL:
            progress = None
            progress_total = None
            if read_child_row:
                row = read_child_row(child)
                if row:
                    metrics = row.get("metrics") or {}
                    params = row.get("params") or {}
                    progress = (
                        metrics.get("progress") if isinstance(metrics.get("progress"), (int, float)) else
                        params.get("progress") if isinstance(params.get("progress"), (int, float)) else
                        None
                    )
                    progress_total = (
                        metrics.get("progress_total") if isinstance(metrics.get("progress_total"), (int, float)) else
                        params.get("progress_total") if isinstance(params.get("progress_total"), (int, float)) else
                        None
                    )
            child_details.append({
                "verstr": child,
                "status": status,
                "progress": progress,
                "progress_total": progress_total,
            })

    if expected is None:
        expected = len(children)
    else:
        expected = max(expected, len(children))

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
