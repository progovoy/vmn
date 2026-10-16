#!/usr/bin/env python3
"""What similar runs compares: a run's facts, read once into a :class:`Profile`.

A profile is built from a leaderboard row plus the run's ``features``,
``intent`` and ``hypothesis`` (see the plan's formats), and holds each signal
in the shape its comparison wants — sets for Jaccard, a parsed base commit
and version, the script of the command line, the text document.

Rows carry the base code as ``code_verstr`` (``<base>-dev.<commit7>.<diff7>``)
and ``base_version``; an MLflow import has neither, but may name its source
commit in ``imported_from``. A run whose features entry names no changes ran
a clean tree (``clean``): its changes are known to be none. They are unknown
without an entry, and when its writer could not see the code — an MLflow
import, an export's author-only entry, a backfill that found the code object
gone (told from a clean tree's backfill by the clean code verstr). Values of
an unexpected type (a hand-edited record, ``log_input(digest=<int>)``) are
skipped one by one. Pure: no storage.
"""
import hashlib
import json
import re
from collections import namedtuple

from vmn_exp.core.features import AUTHOR_ONLY_VERSION

SYS_PREFIX = "sys_"
# The diff part of a clean tree's dev verstr (version_stamp's snapshot identity).
CLEAN_DIFF = "0000000"

KEYWORD_REPEAT = 3

Input = namedtuple("Input", "name dataset digest")


def _dict(value):
    return value if isinstance(value, dict) else {}


def _strings(value):
    """The non-empty strings of a list (none for anything else)."""
    return [v for v in value if isinstance(v, str) and v] if isinstance(value, list) else []


def keyword_phrases(intent):
    """The intent's keywords, lowercased, in their order (none for an intent
    that is no mapping)."""
    return [k.strip().lower() for k in _strings(_dict(intent).get("keywords")) if k.strip()]


def document_text(row, features=None, intent=None, hypothesis=None, create_note=None):
    """A run's text document: what people wrote about it — its intent (the
    text, and each keyword :data:`KEYWORD_REPEAT` times, since a keyword is a
    deliberate label), name, note (*create_note*, the first ``create`` entry's,
    standing in for a missing one), tags (keys and values), local commit
    subjects and hypothesis."""
    row, intent = _dict(row), _dict(intent)
    parts = [intent.get("text"), row.get("name"), row.get("note") or create_note, hypothesis]
    parts += [str(part) for pair in _dict(row.get("tags")).items() for part in pair]
    parts += _strings(_dict(features).get("commits"))
    parts += [phrase for phrase in keyword_phrases(intent) for _ in range(KEYWORD_REPEAT)]
    return "\n".join(part for part in parts if isinstance(part, str) and part)


class Profile:
    """One run's signals in the shape their comparisons want (see :func:`build_profile`)."""

    __slots__ = (
        "args",
        "base",
        "branch",
        "clean",
        "commit",
        "files",
        "has_intent",
        "inputs",
        "keywords",
        "objective",
        "params",
        "rerun",
        "script",
        "symbols",
        "text",
    )


def _named(value):
    """A mapping's string-keyed items, as a dict."""
    return {k: v for k, v in _dict(value).items() if isinstance(k, str)}


def objective_names(row):
    """The metric names a run optimises: its metrics minus its params (which
    the fold copies into metrics) and the ``sys_*`` system metrics."""
    params = _dict(row.get("params"))
    return frozenset(
        name for name in _named(row.get("metrics"))
        if name not in params and not name.startswith(SYS_PREFIX)
    )


def _code(row):
    """``(commit7, base_version)`` of the code a run started from (either None)."""
    head, sep, tail = str(row.get("code_verstr") or "").rpartition("-dev.")
    commit = tail.split(".", 1)[0] if sep else None
    if not commit:
        source = _dict(row.get("imported_from")).get("source_commit")
        commit = source if isinstance(source, str) else None
    base = row.get("base_version") or (head if sep else None)
    return (commit[:7] if commit else None), (str(base) if base else None)


def _clean_code(row):
    """Whether the row's ``code_verstr`` is a clean tree's."""
    _, sep, tail = str(row.get("code_verstr") or "").rpartition("-dev.")
    return bool(sep) and tail.partition(".")[2] == CLEAN_DIFF


def _changes_known(row, features):
    """Whether *features* — the run's entry, None without one — knows the
    run's changes (see the module docstring)."""
    if not isinstance(features, dict) or features.get("features_version") == AUTHOR_ONLY_VERSION:
        return False
    source = features.get("source")
    if source == "mlflow":  # an import: MLflow never saw the code
        return False
    return source != "backfill" or _clean_code(row)


def _dataset(name):
    """``imagenet@3`` -> ``imagenet``: a registry input's name without its version."""
    base, sep, version = name.rpartition("@")
    return base if sep and base and version.isdigit() else name


def _digest(value):
    """An input's digest as text: a string, or an integer (a crc32) — else none."""
    if isinstance(value, bool) or not isinstance(value, (str, int)):
        return None
    return str(value) or None


def _inputs(inputs):
    return tuple(
        Input(name, _dataset(name), _digest(value.get("digest")))
        for name, value in sorted(_named(inputs).items())
        if isinstance(value, dict)
    )


def rerun_key(row):
    """A run's rerun identity: a stable hash of its ``code_verstr``, its
    params (verbatim) and the set of its inputs (each one's digest, else its
    uri); runs of equal keys are reruns of one experiment. None without a
    ``code_verstr``: nothing is known to rerun it."""
    code = row.get("code_verstr")
    if not code:
        return None
    inputs = sorted({str(_input_identity(v)) for v in _dict(row.get("inputs")).values()})
    identity = [str(code), _named(row.get("params")), inputs]
    try:
        canonical = json.dumps(identity, sort_keys=True, default=repr)
    except (TypeError, ValueError):  # mixed-type or recursive keys of a hand-edited record
        canonical = repr(identity)
    return hashlib.blake2b(canonical.encode(), digest_size=16).hexdigest()


def _input_identity(value):
    value = _dict(value)
    return _digest(value.get("digest")) or value.get("uri")


_LAUNCHERS = frozenset(
    "python python3 pythonw py ipython uv uvx run poetry pipenv conda torchrun "
    "accelerate launch deepspeed mpirun mpiexec srun horovodrun bash sh zsh env time "
    "nohup exec node rscript julia".split()
)
# `python -m <one of these> [its options] <script or program>` runs that script.
_LAUNCHER_MODULES = frozenset(
    "torch.distributed.run torch.distributed.launch accelerate.commands.launch "
    "accelerate.commands.accelerate_cli deepspeed.launcher.runner deepspeed.launcher.launch "
    "horovod.runner.launch mpi4py torch_xla.distributed.xla_dist pdb debugpy cProfile "
    "profile".split()
)
_PYTHON = re.compile(r"python\d+(\.\d+)*$")
_SCRIPT = re.compile(r"\.(py|sh|ipynb|r|jl|js|ts|rb|pl|lua)$", re.IGNORECASE)


def _argv(command):
    if isinstance(command, str):
        return command.split()
    if isinstance(command, (list, tuple)):
        return [str(token) for token in command]
    return []


def _launcher(token):
    name = token.rsplit("/", 1)[-1].lower()
    return (token.startswith("-") or "=" in token or token.isdigit()
            or name in _LAUNCHERS or bool(_PYTHON.match(name)))


def _takes_value(token):
    return token.startswith("-") and "=" not in token and token != "--"


def _entry(argv, i):
    return argv[i].rsplit("/", 1)[-1], tuple(argv[i + 1:])


def entrypoint(command):
    """``(script, args)`` of a command line (argv list or string): the first
    script-looking path, else the module after ``-m`` — looked past when it is
    a launcher (``python -m torch.distributed.run ... train.py``) — else the
    program (:func:`_program`); ``(None, ())`` when there is none."""
    argv = _argv(command)
    for i, token in enumerate(argv):
        if token == "-m" and i + 1 < len(argv):
            return _module_entry(argv[i + 1], argv[i + 2:])
        if not token.startswith("-") and "=" not in token and _SCRIPT.search(token):
            return _entry(argv, i)
    return _program(argv)


def _module_entry(module, rest):
    if module in _LAUNCHER_MODULES:
        launched = entrypoint(rest)
        if launched[0]:
            return launched
    return module, tuple(rest)


def _program(argv):
    """The first word that is no launcher, flag, ``K=V`` or flag value (a
    word right after a flag, unless no other follows: ``srun -p gpu
    hostname``), or what follows a ``--`` that ends the launchers' options
    (``srun -p gpu -- ./bench``)."""
    value = None
    for i, token in enumerate(argv):
        if token == "--":
            launched = entrypoint(argv[i + 1:])
            if launched[0]:
                return launched
            break
        if _launcher(token):
            continue
        if i and _takes_value(argv[i - 1]):
            value = i if value is None else value
            continue
        return _entry(argv, i)
    return (None, ()) if value is None else _entry(argv, value)


def build_profile(row=None, features=None, intent=None, hypothesis=None,
                  command=None, create_note=None, text=None):
    """The :class:`Profile` of one run (or of a working tree: *row* may lack a verstr).

    The command is the row's ``command`` (annotated rows), else *command*
    (the run state's), else ``features.entrypoint``. *text*, when given,
    replaces the run's text document (a ``--context`` query).
    """
    row, intent = _dict(row), _dict(intent)
    known, features = _changes_known(row, features), _dict(features)
    changed = _dict(features.get("changed"))
    p = Profile()
    p.commit, p.base = _code(row)
    p.files = frozenset(_strings(changed.get("files")) + _strings(changed.get("untracked")))
    p.symbols = frozenset(_strings(changed.get("symbols")))
    p.clean = known and not (p.files or p.symbols)
    p.inputs = _inputs(row.get("inputs"))
    p.params = _named(row.get("params"))
    p.rerun = rerun_key(row)
    p.script, p.args = entrypoint(row.get("command") or command or features.get("entrypoint"))
    p.objective = objective_names(row)
    branch = row.get("branch") or features.get("branch")
    p.branch = branch if isinstance(branch, str) and branch else None
    if text is not None:
        p.text, p.keywords = (text if isinstance(text, str) else ""), ()
    else:
        p.text = document_text(row, features, intent, hypothesis, create_note)
        p.keywords = tuple(keyword_phrases(intent))
    context = text.strip() if isinstance(text, str) else ""
    p.has_intent = bool(context or intent.get("text") or p.keywords)
    return p

