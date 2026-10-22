#!/usr/bin/env python3
"""``vmn-exp ui diag``: take a diagnostic dump of a running ``vmn-exp ui``.

* ``--url <base> [--token T] [-o FILE]`` GETs ``<base>/api/v1/diag`` (admin).
* ``--pid <PID> [--data-dir D] [--wait S] [-o FILE]`` sends SIGUSR1 and waits
  for the server to write ``<data-dir>/diag/diag-<ts>-<pid>.json`` — works
  when the server is too starved to answer HTTP. When no dump comes (a
  pegged interpreter never runs the Python handler), it sends SIGUSR2 and
  takes every thread's stack, written from C to ``stacks-<pid>.log``.
* ``--summarize FILE`` summarizes a dump carried out of an air-gapped site.

Each prints the dump's path and :func:`vmn_exp.ui.diag_summary.summarize`.
"""
import glob
import json
import os
import shutil
import signal
import time
import urllib.error
import urllib.request

from version_stamp.api import VMN_LOGGER
from vmn_exp.ui.diag_summary import summarize

DIAG_PATH = "/api/v1/diag"
POLL_SEC = 0.1
HTTP_TIMEOUT_SEC = 120
STACKS_WAIT_SEC = 5


def handle_diag(args):
    sources = [s for s in (args.diag_url, args.diag_pid, args.diag_summarize) if s is not None]
    if len(sources) != 1:
        VMN_LOGGER.error("usage: vmn-exp ui diag (--url URL [--token T] | --pid PID "
                         "[--data-dir D] [--wait S] | --summarize FILE) [-o FILE]")
        return 2
    if args.diag_summarize is not None:
        return _report(args.diag_summarize)
    if args.diag_url is not None:
        return _from_url(args)
    return _from_pid(args)


def _report(path):
    try:
        with open(path) as f:
            dump = json.load(f)
    except (OSError, ValueError) as e:
        VMN_LOGGER.error(f"Cannot read the dump {path}: {e}")
        return 1
    print(path)
    print(summarize(dump))
    return 0


def _from_url(args):
    url = args.diag_url.rstrip("/") + DIAG_PATH
    request = urllib.request.Request(url, headers={"Accept": "application/json"})
    token = args.token or os.environ.get("VMN_UI_TOKEN")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SEC) as response:
            body = response.read()
        json.loads(body)
    except (urllib.error.URLError, OSError, ValueError) as e:
        VMN_LOGGER.error(f"GET {url} failed: {e}")
        return 1
    dest = args.diag_output or time.strftime("vmn-exp-diag-%Y%m%dT%H%M%SZ.json", time.gmtime())
    _ensure_parent(dest)
    with open(dest, "wb") as f:
        f.write(body)
    return _report(dest)


def _from_pid(args):
    pid = args.diag_pid
    pattern = os.path.join(_data_dir(args), "diag", f"diag-*-{pid}.json")
    before = set(glob.glob(pattern))
    try:
        os.kill(pid, signal.SIGUSR1)
    except OSError as e:
        VMN_LOGGER.error(f"Cannot signal pid {pid}: {e}")
        return 1
    path = _wait_for_dump(pattern, before, time.monotonic() + args.diag_wait)
    if path is None:
        return _stacks_from_pid(args, pid, pattern)
    if args.diag_output:
        _ensure_parent(args.diag_output)
        shutil.copyfile(path, args.diag_output)
        path = args.diag_output
    return _report(path)


def _stacks_from_pid(args, pid, pattern):
    """No JSON dump came: every thread's stack via SIGUSR2 instead."""
    from vmn_exp.ui.diag.stacks import stacks_path

    path = stacks_path(_data_dir(args), pid)
    start = os.path.getsize(path) if os.path.exists(path) else 0
    try:
        os.kill(pid, signal.SIGUSR2)
    except OSError as e:
        VMN_LOGGER.error(f"Cannot signal pid {pid}: {e}")
        return 1
    stacks = _wait_for_growth(path, start, time.monotonic() + STACKS_WAIT_SEC)
    if not stacks:
        VMN_LOGGER.error(f"No new dump matching {pattern} within {args.diag_wait}s, nor "
                         f"stacks in {path} (is --data-dir the server's?)")
        return 1
    dest = args.diag_output or time.strftime("vmn-exp-stacks-%Y%m%dT%H%M%SZ.txt", time.gmtime())
    _ensure_parent(dest)
    with open(dest, "w") as f:
        f.write(stacks)
    print(f"No JSON dump within {args.diag_wait}s (the server's Python handler never ran); "
          f"every thread's stack instead:")
    print(dest)
    return 0


def _wait_for_growth(path, start, deadline):
    """What *path* gained past *start* once it stops growing, or ``""``."""
    seen = -1
    while time.monotonic() < deadline:
        size = os.path.getsize(path) if os.path.exists(path) else 0
        if size > start and size == seen:
            with open(path, errors="replace") as f:
                f.seek(start)
                return f.read()
        seen = size
        time.sleep(POLL_SEC * 2)
    return ""


def _wait_for_dump(pattern, before, deadline):
    """The first new, complete (parseable) file matching *pattern*, or ``None``."""
    while True:
        for path in sorted(set(glob.glob(pattern)) - before):
            if _complete(path):
                return path
        if time.monotonic() >= deadline:
            return None
        time.sleep(POLL_SEC)


def _complete(path):
    try:
        with open(path) as f:
            json.load(f)
        return True
    except (OSError, ValueError):
        return False


def _data_dir(args):
    """The data dir ``vmn-exp ui`` would use for these flags."""
    from vmn_exp.ui.cli import DEFAULT_DATA_DIR
    from vmn_exp.ui.config import resolve_config

    cfg = resolve_config(args)
    return cfg.data_dir if cfg is not None else args.data_dir or DEFAULT_DATA_DIR


def _ensure_parent(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
