#!/usr/bin/env python3
"""The posting lists of the similar index: ``{token: [verstr, ...]}``, each
list in snapshot order.

:func:`filed` files every run anew; :func:`refiled` brings an earlier
snapshot's postings up to a new one from what changed — a run gone, new or
holding other tokens — so a new generation costs about what changed, not
the app. A posting list is never changed once built: postings of successive
snapshots share every list no run of theirs moved in or out of. Pure.
"""

# Changes past which refiling every run beats patching the lists:
# max(REFILE_MIN, runs // REFILE_SHARE).
REFILE_MIN, REFILE_SHARE = 64, 8


def filed(profiles, tokens_of, check=None):
    """The postings of *profiles* (``{verstr: Profile}`` in snapshot order)
    under *tokens_of(profile)*; *check(done)* is called once per run."""
    postings = {}
    for done, (verstr, profile) in enumerate(profiles.items()):
        if check is not None:
            check(done)
        for token in tokens_of(profile):
            postings.setdefault(token, []).append(verstr)
    return postings


def kept_order(old_pos, order):
    """Whether the runs of *order* that *old_pos* (verstr -> position in the
    earlier snapshot) knows are still in their earlier order."""
    last = -1
    for verstr in order:
        at = old_pos.get(verstr)
        if at is not None:
            if at < last:
                return False
            last = at
    return True


def worth_patching(changes, runs):
    """Whether *changes* (a count) are few enough among *runs* to patch the lists."""
    return changes <= max(REFILE_MIN, runs // REFILE_SHARE)


def refiled(old, pos, changes, tokens_of):
    """*old* postings brought up to a snapshot whose runs sit at *pos*
    (verstr -> position): *changes* are ``(verstr, profile before | None,
    profile now | None)`` of each run gone, new or rebuilt; every other run
    of *old* must keep its relative order (:func:`kept_order`)."""
    drops, adds = {}, {}
    for verstr, before, now in changes:
        was = tokens_of(before) if before is not None else set()
        has = tokens_of(now) if now is not None else set()
        for token in was - has:
            drops.setdefault(token, set()).add(verstr)
        for token in has - was:
            adds.setdefault(token, []).append(verstr)
    if not drops and not adds:
        return old
    postings = dict(old)
    for token in set(drops) | set(adds):
        verstrs = _without(old.get(token, ()), drops.get(token))
        for verstr in sorted(adds.get(token, ()), key=pos.__getitem__):
            _insert(verstrs, verstr, pos)
        if verstrs:
            postings[token] = verstrs
        else:
            postings.pop(token, None)
    return postings


def _without(verstrs, gone):
    """A new list of *verstrs* minus the *gone* ones."""
    return [v for v in verstrs if v not in gone] if gone else list(verstrs)


def _insert(verstrs, verstr, pos):
    """Insert *verstr* into *verstrs* (sorted by *pos*) at its place."""
    at, lo, hi = pos[verstr], 0, len(verstrs)
    while lo < hi:
        mid = (lo + hi) // 2
        if pos[verstrs[mid]] < at:
            lo = mid + 1
        else:
            hi = mid
    verstrs.insert(lo, verstr)
