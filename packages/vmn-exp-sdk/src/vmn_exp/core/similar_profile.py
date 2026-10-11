#!/usr/bin/env python3
"""What similar runs compares: a run's facts, read once into a :class:`Profile`.

A profile is built from a leaderboard row plus the run's ``features``,
``intent`` and ``hypothesis`` (see the plan's formats), and holds each signal
in the shape its comparison wants — sets for Jaccard, a parsed base commit
and version, the script of the command line, the text document's term counts.

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
import re
from collections import Counter, namedtuple

from vmn_exp.core.similar_text import document_terms, keyword_phrases, tokenize

SYS_PREFIX = "sys_"
# The diff part of a clean tree's dev verstr (version_stamp's snapshot identity).
CLEAN_DIFF = "0000000"
# The version of an export's entry that names only its author (core.snapshot_features).
_AUTHOR_ONLY_VERSION = 0

Input = namedtuple("Input", "name dataset digest kind")


class Profile:
    """One run's signals in the shape their comparisons want (see :func:`build_profile`)."""

    __slots__ = (
        "args",
        "base",
        "branch",
        "clean",
        "commit",
        "commit_changes",
        "files",
        "has_intent",
        "inputs",
        "keywords",
        "length",
        "objective",
        "params",
        "script",
        "symbols",
        "terms",
    )


def _dict(value):
    return value if isinstance(value, dict) else {}


def _strings(value):
    return [v for v in value if isinstance(v, str) and v] if isinstance(value, list) else []


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
    if not isinstance(features, dict) or features.get("features_version") == _AUTHOR_ONLY_VERSION:
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
        Input(name, _dataset(name), _digest(value.get("digest")), value.get("kind"))
        for name, value in sorted(_named(inputs).items())
        if isinstance(value, dict)
    )


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
    p.commit_changes = features.get("changed_source") == "commit"
    p.inputs = _inputs(row.get("inputs"))
    p.params = _named(row.get("params"))
    p.script, p.args = entrypoint(row.get("command") or command or features.get("entrypoint"))
    p.objective = objective_names(row)
    branch = row.get("branch") or features.get("branch")
    p.branch = branch if isinstance(branch, str) and branch else None
    if text is not None:
        terms, p.keywords = tokenize(text), ()
    else:
        terms = document_terms(row, features, intent, hypothesis, create_note)
        p.keywords = tuple(keyword_phrases(intent))
    p.terms, p.length = Counter(terms), len(terms)
    context = text.strip() if isinstance(text, str) else ""
    p.has_intent = bool(context or intent.get("text") or p.keywords)
    return p


def as_profile(run):
    """*run* if it is a :class:`Profile`, else the profile of a run view
    ``{"row", "features"?, "intent"?, "hypothesis"?, "command"?, "text"?}``."""
    if isinstance(run, Profile):
        return run
    return build_profile(run.get("row"), run.get("features"), run.get("intent"),
                         run.get("hypothesis"), command=run.get("command"), text=run.get("text"))


def profile_tokens(p, structured=True):
    """The inverted-index tokens of a profile: ``w:`` words, and with
    *structured* ``file:``/``sym:``/``input:``/``ds:``/``pkey:``/``cmd:``/
    ``metric:``/``commit:`` ones."""
    tokens = {"w:" + term for term in p.terms}
    if structured:
        tokens.update("file:" + f for f in p.files)
        tokens.update("sym:" + s for s in p.symbols)
        tokens.update("ds:" + i.dataset for i in p.inputs)
        tokens.update("input:" + i.digest for i in p.inputs if i.digest)
        tokens.update("pkey:" + k for k in p.params)
        tokens.update("metric:" + m for m in p.objective)
        if p.script:
            tokens.add("cmd:" + p.script)
        if p.commit:
            tokens.add("commit:" + p.commit)
    return tokens
