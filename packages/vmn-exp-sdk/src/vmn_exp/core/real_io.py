"""The real implementations of vmn_exp.core.ports: thin stdlib classes.

Only entry points build them (``real_io()``) and pass them down; logic takes
the ports as parameters. Stdlib only, so it stays off the SDK's heavy-import
list.
"""
import os
import secrets
import socket
import subprocess
import sys
import time
from collections.abc import Mapping
from datetime import datetime, timezone

from vmn_exp.core.ports import IO


class RealClock:
    def now(self):
        return datetime.now(timezone.utc)

    def monotonic(self):
        return time.monotonic()

    def sleep(self, sec):
        time.sleep(sec)


class RealEnv(Mapping):
    """A live, read-only view of ``os.environ``."""

    def __getitem__(self, key):
        return os.environ[key]

    def __iter__(self):
        return iter(os.environ)

    def __len__(self):
        return len(os.environ)


class RealProcesses:
    def run(self, cmd, **kwargs):
        try:
            return subprocess.run(cmd, **kwargs)
        except FileNotFoundError as err:
            if err.filename != kwargs.get("executable", cmd[0]):
                raise  # a missing cwd, not a missing binary
            return None

    def popen(self, cmd, **kwargs):
        return subprocess.Popen(cmd, **kwargs)


class RealRandom:
    def hex_id(self):
        return secrets.token_hex(16)

    def token_hex(self, nbytes):
        return secrets.token_hex(nbytes)

    def token_urlsafe(self, nbytes):
        return secrets.token_urlsafe(nbytes)

    def token_bytes(self, nbytes):
        return secrets.token_bytes(nbytes)


class RealHost:
    def pid(self):
        return os.getpid()

    def hostname(self):
        return socket.gethostname()


class RealConsole:
    def out(self, text):
        print(text)

    def err(self, text):
        print(text, file=sys.stderr)

    def read_line(self):
        return sys.stdin.readline().removesuffix("\n")


def real_io():
    return IO(
        clock=RealClock(),
        env=RealEnv(),
        processes=RealProcesses(),
        random=RealRandom(),
        host=RealHost(),
        console=RealConsole(),
    )
