"""The name a hunk header's context points at (git's funcname line, any language).

``hunk_symbol("def focal_loss(x):")`` -> ``"focal_loss"``. Declarations
(def/class/function/fn/func/impl/struct/..., ``const f = (...) =>``, ``f: function``)
and C-like signatures (``static int f(int x)``) give their identifier; any other
context falls back to its trimmed text, cut at 80 characters.
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


def _declared_name(rest: str) -> str | None:
    for pattern in (_FUNCTION, _IMPL, _ASSIGNED, _PROPERTY):
        match = pattern.match(rest)
        if match:
            return match.group(1)
    match = _TYPE.match(rest)
    if match and not (match.group(1) in _C_RETURN_TYPES and "(" in rest):
        return match.group(2)
    return None


def _signature_name(rest: str) -> str | None:
    """``int f(int x)`` / ``void Foo::bar(int)`` / ``  method(args) {``: the name before
    the first ``(``, unless the line reads as a statement or a call."""
    before, paren, _ = rest.partition("(")
    if not paren or rest.rstrip().endswith(";"):
        return None
    match = _NAME_BEFORE_PAREN.search(before)
    if not match:
        return None
    lead = before[: match.start()]
    if lead.endswith(".") or "=" in lead:
        return None
    if _STATEMENT_WORDS.intersection(lead.split() + [match.group(1)]):
        return None
    return match.group(1)
