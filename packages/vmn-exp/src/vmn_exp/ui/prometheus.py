#!/usr/bin/env python3
"""The Prometheus text exposition format (0.0.4) ``/metrics`` is written in:
one :class:`Family` per metric name, its ``# HELP``/``# TYPE`` lines once
and its samples together, label values escaped."""


def label_value(value):
    """*value* escaped for a quoted label value (backslash, quote, newline)."""
    return str(value).replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


class Family:
    def __init__(self, name, kind, help_text):
        self.name, self.kind, self.help = name, kind, help_text
        self.samples = []

    def add(self, labels, value):
        """A sample of *labels* (a dict, in order); a None *value* is left out."""
        if value is None:
            return
        body = ",".join(f'{key}="{label_value(v)}"' for key, v in labels.items())
        self.samples.append(f"{self.name}{{{body}}} {value}")

    def lines(self):
        return [f"# HELP {self.name} {self.help}", f"# TYPE {self.name} {self.kind}",
                *self.samples]


def exposition(families):
    """The text of *families*, newline-terminated."""
    return "".join(line + "\n" for family in families for line in family.lines())
