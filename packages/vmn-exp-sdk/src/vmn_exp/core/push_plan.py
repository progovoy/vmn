"""Selection helpers for ``vmn exp push``: the order runs are pushed in and
what a push would do to one run (``--dry-run``), without remote writes."""
from vmn_exp.core.push_identity import run_identity
from vmn_exp.core.push_run import (
    COLLISION, NEW, UP_TO_DATE, UPDATE, ledger_entry, up_to_date,
)


def parents_first(verstrs, parent_of):
    """*verstrs* reordered so each run's parent, when selected too, precedes
    it: a parent renamed on a collision rewrites its children's ``parent``
    before they are pushed."""
    selected, seen, order = set(verstrs), set(), []

    def visit(verstr):
        if verstr in seen:
            return
        seen.add(verstr)
        parent = parent_of(verstr)
        if parent in selected:
            visit(parent)
        order.append(verstr)

    for verstr in verstrs:
        visit(verstr)
    return order


def plan_push(local, target, app_name, verstr, ledger):
    """:data:`UP_TO_DATE` from the ledger alone, else one remote metadata
    read: :data:`NEW`, :data:`UPDATE` or :data:`COLLISION` (would rename)."""
    identity = run_identity(app_name, local.load_metadata(app_name, verstr))
    if up_to_date(ledger_entry(ledger, verstr, identity), local, app_name, verstr):
        return UP_TO_DATE
    remote = target.load_metadata(app_name, verstr)
    if remote is None:
        return NEW
    return UPDATE if run_identity(app_name, remote) == identity else COLLISION
