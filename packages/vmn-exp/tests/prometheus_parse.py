"""A strict reader of the Prometheus text exposition format (0.0.4) for the
``/metrics`` tests: every sample follows its family's ``# TYPE`` line, a
family is never split, no sample repeats, label values unescape."""
import re

_NAME = r"[a-zA-Z_:][a-zA-Z0-9_:]*"
_SAMPLE = re.compile(rf"^({_NAME})(?:\{{(.*)\}})? (\S+)$")
_LABEL = re.compile(r'([a-zA-Z_][a-zA-Z0-9_]*)="((?:[^"\\\n]|\\[\\"n])*)"(?:,|$)')
_KINDS = ("counter", "gauge")


def parse(text):
    """``{(name, ((label, value), ...)): float}`` of *text*'s samples."""
    assert text.endswith("\n"), "the exposition ends with a newline"
    samples, typed, current = {}, set(), None
    for line in text[:-1].split("\n"):
        if line.startswith("# HELP "):
            continue
        if line.startswith("# TYPE "):
            _, _, name, kind = line.split(" ")
            assert kind in _KINDS, line
            assert name not in typed, f"{name} typed twice (a split family)"
            typed.add(name)
            current = name
            continue
        match = _SAMPLE.match(line)
        assert match, f"not a sample: {line!r}"
        name, body, value = match.groups()
        assert name == current, f"{name} outside its family"
        key = (name, tuple(sorted(_labels(body or "").items())))
        assert key not in samples, f"duplicate sample {key}"
        samples[key] = float(value)
    return samples


def _labels(body):
    out, pos = {}, 0
    while pos < len(body):
        match = _LABEL.match(body, pos)
        assert match, f"bad labels at {body[pos:]!r}"
        out[match.group(1)] = re.sub(r"\\(.)", lambda m: "\n" if m.group(1) == "n" else m.group(1),
                                     match.group(2))
        pos = match.end()
    return out


def value(samples, metric, /, **labels):
    """The sample *metric* with exactly *labels*, else None."""
    return samples.get((metric, tuple(sorted(labels.items()))))


def label_sets(samples, name):
    """Every label dict *name* has a sample for."""
    return [dict(labels) for (n, labels) in samples if n == name]
