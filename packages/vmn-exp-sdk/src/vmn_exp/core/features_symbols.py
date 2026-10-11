"""The names a patch's code defines (any language).

``hunk_symbol("def focal_loss(x):")`` -> ``"focal_loss"``: the name a hunk
header's context (git's funcname line) points at. Declarations
(def/class/function/fn/func/impl/struct/..., ``const f = (...) =>``, ``f: function``)
and C-like signatures (``static int f(int x)``) give their identifier; any other
context falls back to its trimmed text, cut at 80 characters.

``defined_symbol(line, path)``: the name an added or removed line defines, by
the same rules made strict — a content line is far more often a call, a
statement or prose than a funcname line is — and only in source files: Python
``def``/``class`` alone; elsewhere declarations, arrow functions, and
signatures with a return type or a declaring modifier (or a bare
``name(params) {``, a method); no text fallback.
"""
from __future__ import annotations

import re

FALLBACK_CHARS = 80

_IDENT = r"[A-Za-z_$][\w$]*"
_MODIFIERS = re.compile(
    r"(?:(?:export|default|public|private|protected|internal|static|abstract|final|sealed|"
    r"open|override|virtual|async|unsafe|inline|data|partial|suspend|local|declare|readonly|"
    r"extern(?:\s+\"[^\"]*\")?|pub(?:\s*\([^)]*\))?|const(?=\s+fn\b))\s+)*"
)
_FUNCTION = re.compile(
    r"(?:(?:def|func|fn|fun|sub|proc)\b|function\b\*?)\s*(?:\([^)]*\)\s*)?\*?\s*(?:self\.)?"
    rf"({_IDENT}[?!]?)"
)
_IMPL = re.compile(rf"impl(?:\s*<[^>]*>)?\s+(?:[\w:<>, ]+?\s+for\s+)?({_IDENT})")
_TYPE = re.compile(
    r"(class|interface|trait|module|namespace|object|protocol|record|type|enum|struct|union)"
    rf"\s+({_IDENT})"
)
_C_RETURN_TYPES = ("enum", "struct", "union")  # `struct node *make_node(...)` is a function
_ASSIGNED = re.compile(
    rf"(?:const|let|var)\s+({_IDENT})\s*=\s*(?:async\s+)?(?:function\b|\(|{_IDENT}\s*=>)"
)
_PROPERTY = re.compile(rf"({_IDENT})\s*:\s*(?:async\s+)?function\b")
_NAME_BEFORE_PAREN = re.compile(rf"(~?{_IDENT})\s*$")
_STATEMENT_WORDS = frozenset(
    "if elif else for foreach while until unless switch case catch return sizeof typeof new "
    "delete throw await yield with assert print do not and or in is lambda super this self "
    "echo when match go defer".split()
)


def hunk_symbol(context: str) -> str | None:
    """The identifier *context* declares, else its text (<= 80 chars); None when empty."""
    text = context.strip()
    if not text:
        return None
    rest = text[_MODIFIERS.match(text).end():]
    return _declared_name(rest) or _signature_name(rest) or text[:FALLBACK_CHARS].rstrip()


def _named_by(patterns, rest: str) -> str | None:
    for pattern in patterns:
        match = pattern.match(rest)
        if match:
            return match.group(1)
    return None


def _declared_name(rest: str) -> str | None:
    return _named_by((_FUNCTION, _IMPL, _ASSIGNED, _PROPERTY), rest) or _declared_type(rest)


def _declared_type(rest: str) -> str | None:
    match = _TYPE.match(rest)
    if match and not (match.group(1) in _C_RETURN_TYPES and "(" in rest):
        return match.group(2)
    return None


def _signature_name(rest: str) -> str | None:
    """``int f(int x)`` / ``void Foo::bar(int)`` / ``  method(args) {``: the name before
    the first ``(``, unless the line reads as a statement or a call."""
    found = _name_before_paren(rest)
    if not found:
        return None
    name, lead, _ = found
    if lead.endswith(".") or "=" in lead or _STATEMENT_WORDS.intersection(lead.split() + [name]):
        return None
    return name


def _name_before_paren(rest: str):
    """``(name, what precedes it, what follows its "(")`` of the first ``(``
    of a line not ending in ``;``, else None."""
    before, paren, after = rest.partition("(")
    if not paren or rest.rstrip().endswith(";"):
        return None
    match = _NAME_BEFORE_PAREN.search(before)
    return (match.group(1), before[: match.start()], after) if match else None


_PYTHON_FILES = frozenset("py pyi pyw pyx pxd".split())
_CODE_FILES = frozenset(
    "c h cc cpp cxx hh hpp hxx cu cuh m mm java kt kts scala groovy cs swift dart go rs "
    "js jsx mjs cjs ts tsx mts cts php rb lua pl pm jl ex exs sh bash zsh".split()
)
_PY_DEFINITION = re.compile(
    rf"(?:async\s+)?def\s+({_IDENT})\s*[(\[]|class\s+({_IDENT})\s*[(:\[]"
)
_ARROW_ASSIGNED = re.compile(  # `const f = (x) => ...`, not `const n = (a + b) * 2`
    rf"(?:const|let|var)\s+({_IDENT})\s*(?::[^=]+)?=\s*(?:async\s+)?"
    rf"(?:function\b|\([^)]*\)\s*(?::[^=]+)?=>|{_IDENT}\s*=>)"
)
_DECLARING = frozenset(
    "public private protected internal static abstract final override virtual async "
    "suspend open inline extern".split()
)
_NOT_TYPES = _STATEMENT_WORDS | frozenset(
    "synchronized using lock fixed checked unchecked try elseif raise import from except "
    "del goto then export default".split()
)
_TYPE_LEAD = re.compile(r"[\w$<>,*&\[\]\s]*")
_CALL_ARGUMENTS = re.compile(r"[\"'`]|=>|\bfunction\b")
_MACRO = re.compile(r"[A-Z][A-Z0-9_]*")
_NAME_START = re.compile(r"[A-Za-z_$~]")


def _extension(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name.rsplit(".", 1)[-1].lower() if "." in name else ""


def defined_symbol(line: str, path: str) -> str | None:
    """The name *line* — a diff content line without its ``+``/``-`` — defines
    in the file *path*; None for calls, statements, comments, prose and
    files that are not source code."""
    kind = _extension(path)
    if kind not in _PYTHON_FILES and kind not in _CODE_FILES:
        return None
    text = line.strip()
    if kind in _PYTHON_FILES:
        match = _PY_DEFINITION.match(text)
        return (match.group(1) or match.group(2)) if match else None
    modifiers = _MODIFIERS.match(text).end()
    rest = text[modifiers:]
    declaring = bool(_DECLARING.intersection(text[:modifiers].split()))
    return _strict_declared_name(rest) or _defined_signature(rest, declaring)


def _strict_declared_name(rest: str) -> str | None:
    name = _named_by((_FUNCTION, _IMPL, _ARROW_ASSIGNED, _PROPERTY), rest)
    if name or rest.rstrip().endswith(";"):  # `struct node head;` declares a variable
        return name
    return _declared_type(rest)


def _defined_signature(rest: str, declaring: bool) -> str | None:
    """``int f(int x)``, ``void A::f() const {``, ``public T f(...)``, or a bare
    ``f(params) {`` (a method or constructor; not a macro or a call taking
    a callback)."""
    found = _NAME_START.match(rest) and _name_before_paren(rest)
    if not found:
        return None
    name, lead, after = found
    if lead.endswith(".") or not _TYPE_LEAD.fullmatch(lead.replace("::", "")):
        return None
    if _NOT_TYPES.intersection(lead.split() + [name]):
        return None
    if lead.strip() or declaring:
        return name
    bare_method = (rest.rstrip().endswith("{") and not _CALL_ARGUMENTS.search(after)
                   and not _MACRO.fullmatch(name))
    return name if bare_method else None
