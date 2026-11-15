import subprocess

HANG = object()  # a scripted command that never finishes: its timeout expires


class FakeProcesses:
    """Answers each command from a script, ``{tuple(cmd): CompletedProcess | HANG}``;
    an unscripted command is a missing binary (``run`` returns None, ``popen``
    raises FileNotFoundError). Every call is kept in ``calls``."""

    def __init__(self, script=None):
        self._script = dict(script or {})
        self.calls = []

    def run(self, cmd, **kwargs):
        self.calls.append((list(cmd), kwargs))
        result = self._script.get(tuple(cmd))
        if result is HANG:
            raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout"))
        return result

    def popen(self, cmd, **kwargs):
        self.calls.append((list(cmd), kwargs))
        if tuple(cmd) not in self._script:
            raise FileNotFoundError(2, "No such file or directory", cmd[0])
        return FakePopen(self._script[tuple(cmd)])


class FakePopen:
    """A child that has already finished with its scripted CompletedProcess."""

    def __init__(self, done):
        self.returncode = done.returncode
        self._done = done

    def communicate(self, input=None, timeout=None):
        return self._done.stdout, self._done.stderr

    def wait(self, timeout=None):
        return self.returncode
