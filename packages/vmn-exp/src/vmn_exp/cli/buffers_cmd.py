"""``vmn-exp buffers list`` / ``vmn-exp buffers ship [--store URI] [--keep]``:
this host's kept or orphaned direct-to-bucket log buffers (plan 40 C6).

``list`` is read-only and takes no repo lock. ``ship`` ships each buffer of
the store it is given whose owner lock it can take
(:mod:`vmn_exp.cli.pushing.buffer_recover`), one line per buffer, and exits 1 only
when a buffer it locked could not be shipped; skipped buffers do not fail it.
"""
import argparse
import sys

from vmn_exp.cli.duration_text import humanize_sec
from vmn_exp.cli.pushing import buffer_recover
from vmn_exp.core.status import parse_iso
from vmn_exp.core.storage_resolve import merge_env_into_params, store_uri


def _parser():
    p = argparse.ArgumentParser(
        prog="vmn-exp buffers",
        description="This host's kept or orphaned direct-to-bucket log buffers")
    sub = p.add_subparsers(dest="action", required=True)
    sub.add_parser("list", help="list the buffers, live or not")
    ship = sub.add_parser("ship", help="ship the buffers no live process owns")
    ship.add_argument("--store", help="the store URI (default: $VMN_STORE or the $VMN_STORE_BUCKET shorthand)")
    ship.add_argument("--keep", action="store_true",
                      help="leave a fully shipped buffer dir in place")
    return p


def store_from_env(env):
    """The store URI *env* names (``VMN_STORE*``, then the legacy
    ``VMN_EXPERIMENT_*`` twins), None without one."""
    params = {}
    merge_env_into_params(params, env)
    return store_uri(params)


def run_buffers(argv, io):
    """The command with this host's buffer dirs and *io*."""
    from vmn_exp.storage.buffer_host import LocalBufferHost
    from vmn_exp.storage.host_dirs import log_buffers_bases
    from vmn_exp.storage.open import open_storage

    return buffers_main(
        argv, host=LocalBufferHost(), bases=log_buffers_bases(io.env),
        store_env=store_from_env(io.env),
        open_remote=lambda uri, area: open_storage(uri, area=area, writer=False, clock=io.clock, env=io.env),
        out=sys.stdout, now=io.clock.now().timestamp())


def buffers_main(argv, *, host, bases, store_env, open_remote, out, now):
    args = _parser().parse_args(argv)
    buffers = buffer_recover.kept_buffers(bases, host)
    if args.action == "list":
        for buffer in buffers:
            out.write(_list_line(buffer, now) + "\n")
        return 0
    store = args.store or store_env
    if not store:
        out.write("vmn-exp buffers ship: pass --store (or set VMN_STORE)\n")
        return 2
    return _ship_all(buffers, store, host, open_remote, args.keep, out)


def _list_line(buffer, now):
    state = {True: "live", False: "orphaned", None: "unknown"}[buffer.live]
    if buffer.marker is None:
        return f"{buffer.root}  {state} ({buffer.why})  {buffer.size} bytes"
    started = parse_iso(buffer.started_at)
    age = humanize_sec(max(0.0, now - started.timestamp())) if started else "?"
    runs = ",".join(f"{app}/{verstr}" for app, verstr in buffer.runs) or "-"
    return (f"{buffer.root}  {state}  age {age}  host {buffer.host}  pid {buffer.pid}  "
            f"store {buffer.remote}  runs {runs}  {buffer.size} bytes")


def _ship_all(buffers, store, host, open_remote, keep, out):
    remotes = {}
    failed = False
    for buffer in buffers:
        remote = _store_remote(buffer, store, open_remote, remotes) if buffer.marker else None
        if buffer.marker and remote is None:
            out.write(f"{buffer.root}: another store: skipped\n")
            continue
        outcome = buffer_recover.ship_buffer(buffer, remote, host, keep=keep)
        failed |= outcome.status == buffer_recover.FAILED
        out.write(_ship_line(buffer, outcome) + "\n")
    return 1 if failed else 0


def _store_remote(buffer, store, open_remote, remotes):
    """*store*'s storage of *buffer*'s area when the buffer is that store's, else None."""
    if buffer.area not in remotes:
        remotes[buffer.area] = open_remote(store, buffer.area)
    remote = remotes[buffer.area]
    return remote if repr(remote.cache_identity()) == buffer.remote else None


def _ship_line(buffer, outcome):
    if outcome.status == buffer_recover.SHIPPED:
        return f"{buffer.root}: shipped"
    if outcome.status == buffer_recover.FAILED:
        return f"{buffer.root}: failed: {outcome.detail}"
    why = f" ({outcome.detail})" if outcome.detail else ""
    return f"{buffer.root}: {outcome.status}: skipped{why}"
