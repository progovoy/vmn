#!/usr/bin/env python3
"""Whether an outer run's subtree is settled, and the row objects that
prove it unchanged: what a settled pivot (plan 28 N2) or baseline (N3) is
kept across generations by.

An outer run is settled when no time bucket changes it nor its subtree (the
board's live patch holds no row of it, :mod:`~vmn_exp.ui.leaderboard_live`).
A derived generation keeps every unchanged row object, so the subtree is
unchanged while its rows, and the chain above it an ``up`` field reads, are
the same objects (an O(subtree) identity walk at C speed, no build).
"""
from operator import is_

from vmn_exp.core.tree import ancestors
from vmn_exp.ui.leaderboard_scope import scope_positions


def settled(base, scope):
    """Whether no time bucket changes *scope*'s subtree or *scope*."""
    at = base.position.get(scope)
    return at is not None and at not in base.patch.changed


def subtree_rows(base, scope):
    """The rows of *scope*'s subtree, then *scope* and its ancestors'."""
    position, rows = base.position, base.rows
    chain = [scope] + ancestors(scope, base.snapshot.edges)
    return ([rows[i] for i in scope_positions(base, scope)]
            + [rows[position[v]] for v in chain if v in position])


def same_rows(kept, rows):
    """Whether *rows* are the very objects *kept*."""
    return len(kept) == len(rows) and all(map(is_, kept, rows))
