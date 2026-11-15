"""The only way a ui job turns request values into ``vmn``/``vmn-exp`` argv.

Every option that carries a value is the single token ``--flag=value``, so a
value can never be read as a flag whatever it starts with; a positional never
starts with ``-``. A bad value raises :class:`ValueError` (a 400).
"""

ACTIONS = (
    "stamp", "release", "goto", "restore", "prune", "exp_create", "exp_add",
    "note", "exp_tag", "exp_rewind", "exp_push", "exp_archive", "exp_unarchive",
)

# The flags each action's argv may carry (switches included).
EMITTED = {
    "stamp": ("--release-mode", "--pr", "--dry-run"),
    "release": ("--version",),
    "goto": ("--version",),
    "restore": ("--version",),
    "prune": ("--keep", "--older-than"),
    "exp_create": ("--note", "--metrics"),
    "exp_add": ("--version", "--note", "--metrics"),
    "note": ("--version", "--note"),
    "exp_tag": ("--remove",),
    "exp_rewind": ("--version", "--step"),
    "exp_push": ("--version",),
    "exp_archive": (),
    "exp_unarchive": (),
}

LONG_FLAGS = (
    "--release-mode", "--pr", "--version", "--keep", "--older-than",
    "--note", "--metrics", "--remove", "--step",
)
SWITCHES = ("--dry-run",)


def opt(flag, value):
    """``--flag=value`` as one token."""
    if flag not in LONG_FLAGS:
        raise ValueError(f"Unknown job option {flag!r}")
    if not isinstance(value, str):
        raise ValueError(f"{flag} needs a string value")
    return f"{flag}={value}"


def positional(value):
    """*value* as a positional token: a non-empty string not starting with '-'."""
    if not isinstance(value, str) or not value or value.startswith("-"):
        raise ValueError(f"Invalid argument {value!r}")
    return value


def switch(flag):
    """A boolean flag from :data:`SWITCHES`."""
    if flag not in SWITCHES:
        raise ValueError(f"Unknown job switch {flag!r}")
    return flag
