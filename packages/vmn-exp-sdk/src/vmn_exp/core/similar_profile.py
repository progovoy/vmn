#!/usr/bin/env python3
"""What similar runs compares: a run's facts, read once into a :class:`Profile`.

A profile is built from a leaderboard row plus the run's ``features``,
``intent`` and ``hypothesis`` (see the plan's formats), and holds each signal
in the shape its comparison wants — sets for Jaccard, a parsed base commit
and version, the script of the command line, the text document's term counts.

Rows carry the base code as ``code_verstr`` (``<base>-dev.<commit7>.<diff7>``)
and ``base_version``; an MLflow import has neither, but may name its source
commit in ``imported_from``. Pure: no storage.
"""
import re
from collections import Counter, namedtuple

from vmn_exp.core.similar_text import document_terms, keyword_phrases, tokenize

SYS_PREFIX = "sys_"

Input = namedtuple("Input", "name dataset digest kind")


class Profile:
    """One run's signals in the shape their comparisons want (see :func:`build_profile`)."""

    __slots__ = (
        "args",
        "base",
        "branch",
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


def objective_names(row):
    """The metric names a run optimises: its metrics minus its params (which
    the fold copies into metrics) and the ``sys_*`` system metrics."""
    params = _dict(row.get("params"))
    return frozenset(
        name for name in _dict(row.get("metrics"))
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


def _dataset(name):
    """``imagenet@3`` -> ``imagenet``: a registry input's name without its version."""
    base, sep, version = name.rpartition("@")
    return base if sep and base and version.isdigit() else name


def _inputs(inputs):
    return tuple(
        Input(name, _dataset(name), value.get("digest") or None, value.get("kind"))
        for name, value in sorted(_dict(inputs).items())
        if isinstance(value, dict)
    )


_LAUNCHERS = frozenset(
    "python python3 pythonw py ipython uv uvx run poetry pipenv conda torchrun "
    "accelerate launch deepspeed mpirun srun bash sh zsh env time nohup exec node "
    "rscript julia".split()
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


def entrypoint(command):
    """``(script, args)`` of a command line (argv list or string): the first
    script-looking path, else the module after ``-m``, else the first word
    that is no launcher, flag or ``K=V``; ``(None, ())`` when there is none."""
    argv = _argv(command)
    for i, token in enumerate(argv):
        if token == "-m" and i + 1 < len(argv):
            return argv[i + 1], tuple(argv[i + 2:])
        if not token.startswith("-") and "=" not in token and _SCRIPT.search(token):
            return token.rsplit("/", 1)[-1], tuple(argv[i + 1:])
    for i, token in enumerate(argv):
        if not _launcher(token):
            return token.rsplit("/", 1)[-1], tuple(argv[i + 1:])
    return None, ()


def build_profile(row=None, features=None, intent=None, hypothesis=None,
                  command=None, create_note=None, text=None):
    """The :class:`Profile` of one run (or of a working tree: *row* may lack a verstr).

    The command is the row's ``command`` (annotated rows), else *command*
    (the run state's), else ``features.entrypoint``. *text*, when given,
    replaces the run's text document (a ``--context`` query).
    """
    row, features = _dict(row), _dict(features)
    changed = _dict(features.get("changed"))
    p = Profile()
    p.commit, p.base = _code(row)
    p.files = frozenset(_strings(changed.get("files")) + _strings(changed.get("untracked")))
    p.symbols = frozenset(_strings(changed.get("symbols")))
    p.commit_changes = features.get("changed_source") == "commit"
    p.inputs = _inputs(row.get("inputs"))
    p.params = _dict(row.get("params"))
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
    intent = _dict(intent)
    p.has_intent = bool((text or "").strip() or intent.get("text") or p.keywords)
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
