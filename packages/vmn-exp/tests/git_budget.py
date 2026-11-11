"""What a git-process budget test prints when a bound is exceeded (plan 39 B9a)."""
from collections import Counter

_OPTIONS_WITH_VALUE = {"-C", "-c"}


def _subcommand(argv):
    args = iter(argv[1:])
    for arg in args:
        if arg in _OPTIONS_WITH_VALUE:
            next(args, None)
        elif not arg.startswith("-"):
            return arg
    return "?"


def summarize(calls):
    """One ``<count> <subcommand>`` line per git subcommand, most frequent
    first, then every argv in call order."""
    counts = Counter(_subcommand(argv) for argv in calls)
    lines = [f"{count} {name}" for name, count in counts.most_common()]
    lines += [" ".join(argv) for argv in calls]
    return "\n".join(lines)
