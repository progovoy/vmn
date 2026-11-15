import io


class FakeConsole:
    """Collects what is written in ``stdout``/``stderr`` and reads lines from
    the *stdin* text it was given."""

    def __init__(self, stdin=""):
        self.stdout = ""
        self.stderr = ""
        self._stdin = io.StringIO(stdin)

    def out(self, text):
        self.stdout += f"{text}\n"

    def err(self, text):
        self.stderr += f"{text}\n"

    def read_line(self):
        return self._stdin.readline().removesuffix("\n")
