#!/usr/bin/env python3
"""A tiny query language over experiment rows — vmn's ``search_runs``.

``metrics.loss < 0.5 and status in ("failed", "stuck") and note ~ "baseline"``
compiles to a plain predicate over the rows that
:func:`version_stamp.core.experiment_log.experiment_row` (plus ``status_fields``
and ``annotate_tree``) already built, so the CLI, the REST API, the web ui and
the ``vmn_exp.sdk`` SDK filter identically.

Grammar::

    query      = or_expr
    or_expr    = and_expr { "or" and_expr }
    and_expr   = not_expr { "and" not_expr }
    not_expr   = "not" not_expr | primary
    primary    = "(" or_expr ")" | comparison
    comparison = field cmp_op literal
               | field [ "not" ] "in" "(" literal { "," literal } ")"
    cmp_op     = "=" | "==" | "!=" | "<" | "<=" | ">" | ">="
               | "~" | "!~" | "contains"
    field      = name | ( "metrics" | "params" | "tags" ) "." ( name | string )
               | ( "inputs" | "outputs" ) "." ( name | string ) "." name
    literal    = number | string | "true" | "false" | "null"
    number     = [ "-" ] digits [ "." digits ] [ ( "e" | "E" ) [ "+" | "-" ] digits ]

Hand-written lexer plus recursive descent: no third-party dependency, and no
``eval`` anywhere near text that arrives in an HTTP query parameter. ``not`` and
parentheses nest at most ``MAX_NESTING`` levels (deeper is a ``QueryError``);
``and``/``or`` chains of any length are flat.

``~``/``contains``/``!~`` match a case-insensitive substring; against a
list-valued field (``command``, ``children``) they match any element, and
against a dict-valued one (``tags``) any value.

Semantics, deliberately two-valued (no SQL ``UNKNOWN``): a missing or ``None``
field fails every ordering and substring comparison rather than poisoning the
expression, so a query and its ``not`` always partition the rows. ``= null`` is
how you ask for absence; ``!= x`` is therefore true for a row that has no ``x``.
Values of unlike types (number vs string, bool vs number) never order — the
comparison is false, never a ``TypeError``.

A dict-prefixed field name that isn't a plain identifier — it has a ``/``,
``.`` or ``-`` in it, e.g. a Lightning/TensorBoard-style ``train/loss`` — is
written as a quoted string right after the dot: ``metrics."train/loss"`` or
``params.'val-acc'``. Ordinary names keep working unquoted exactly as before;
the quoted form is purely additive.

``metrics.x`` and ``params.x`` read different dicts: ``params`` carries the
values the run was given verbatim, so ``params.model = "xgb"`` and
``params.cache = true`` match strings and booleans, while ``metrics`` is the
numeric fold the leaderboard sorts and charts. ``tags.x`` reads the run's
current tags, which are always strings (``tags.stage = "prod"``); a removed
or never-set tag is missing. ``name ~ "sweep"`` matches the run name and
``archived = true`` the archived runs.
"""

import functools

# Every non-metric field a row can carry, from ``experiment_row`` +
# ``experiment_status.status_fields`` + ``experiment_tree.annotate_tree``.
# Spelled out so a typo is a query error instead of a silently empty result.
ROW_FIELDS = frozenset(
    """
    idx verstr code_verstr timestamp note branch base_version parent
    name archived tags last_metric_at status exit_code started_at finished_at heartbeat
    duration_sec pid host command stale_sec heartbeat_interval_sec children
    kind depth tree_status imported_from forked_from forked_from_step rerun_of
    """.split()
)

# Each dotted prefix reads its own dict on the row. ``params`` holds values
# verbatim (so ``params.model = "xgb"`` and ``params.cache = true`` work);
# ``metrics`` holds the numeric fold, which is what sorting and charts use;
# ``tags`` holds the run's current tags, always strings.
# ``env`` holds the environment summary dict (python, packages, …).
DICT_PREFIXES = ("metrics", "params", "tags", "env", "comments")

# Three-part fields: ``inputs.<name>.<sub>`` and ``outputs.<artifact path>.<sub>``
# (quote a key with a dot or slash in it: ``outputs."model.pkl".digest``).
NESTED_SUBFIELDS = {
    "inputs": ("uri", "digest", "kind"),
    "outputs": ("path", "digest", "size"),
}

_KEYWORDS = frozenset({"and", "or", "not", "in", "contains", "true", "false", "null"})
_OPERATORS = ("==", "!=", "<=", ">=", "!~", "=", "<", ">", "~")


class QueryError(ValueError):
    """An experiment query that cannot be compiled."""


# ---------------------------------------------------------------------------
# Lexer
# ---------------------------------------------------------------------------


def _fail(message, pos):
    raise QueryError(f"{message} at offset {pos}")


def _describe(token):
    """A user-facing rendering of *token* for "expected X, found ..." errors.

    The end-of-input sentinel has ``value=None``, which would otherwise print
    as the Python-internal-looking ``found 'None'``; render it in words
    instead. A quoted-name token's value is a ``(prefix, key)`` tuple, which
    would otherwise print as a raw Python tuple.
    """
    kind, value, _ = token
    if kind == "end":
        return "end of query"
    if kind == "name" and isinstance(value, tuple):
        prefix, key = value[:2]
        sub = f".{value[2]}" if len(value) == 3 else ""
        return f"'{prefix}.\"{key}\"{sub}'"
    return f"'{value}'"


def _lex_string(text, pos):
    quote = text[pos]
    end = text.find(quote, pos + 1)
    if end < 0:
        _fail("unterminated string literal", pos)
    return ("lit", text[pos + 1 : end], pos), end + 1


def _digits_end(text, pos):
    while pos < len(text) and text[pos].isdigit():
        pos += 1
    return pos


def _lex_exponent(text, pos, start):
    """End of an ``e[+-]digits`` exponent at *pos* (just past the ``e``)."""
    if pos < len(text) and text[pos] in "+-":
        pos += 1
    end = _digits_end(text, pos)
    if end == pos:
        _fail(f"invalid number '{text[start:pos]}'", start)
    return end


def _lex_number(text, pos):
    end = pos + 1
    while end < len(text) and (text[end].isdigit() or text[end] == "."):
        end += 1
    if end < len(text) and text[end] in "eE":
        end = _lex_exponent(text, end + 1, pos)
    raw = text[pos:end]
    try:
        value = float(raw) if any(c in raw for c in ".eE") else int(raw)
    except ValueError:
        _fail(f"invalid number '{raw}'", pos)
    return ("lit", value, pos), end


def _lex_name(text, pos):
    end = pos
    while end < len(text) and (text[end].isalnum() or text[end] in "_."):
        end += 1
    raw = text[pos:end]
    # A quote right after a trailing dot (``metrics."train/loss"``) names a
    # field whose key contains characters an unquoted identifier can't
    # capture (``/``, ``.``, ``-``, ...). The unquoted path above is
    # untouched: this only triggers when nothing alnum/``_``/``.`` could be
    # consumed, i.e. the loop stopped right on a quote.
    if raw.endswith(".") and end < len(text) and text[end] in "'\"":
        prefix = raw[:-1]
        string_token, end = _lex_string(text, end)
        return _lex_subfield(text, end, prefix, string_token[1], pos)
    kind = "kw" if raw.lower() in _KEYWORDS else "name"
    return (kind, raw.lower() if kind == "kw" else raw, pos), end


def _lex_subfield(text, end, prefix, key, pos):
    """A quoted key, and the ``.digest`` sub-field that may follow it."""
    if not text.startswith(".", end):
        return ("name", (prefix, key), pos), end
    sub_end = end + 1
    while sub_end < len(text) and (text[sub_end].isalnum() or text[sub_end] == "_"):
        sub_end += 1
    return ("name", (prefix, key, text[end + 1 : sub_end]), pos), sub_end


def tokenize(text):
    """Split query *text* into ``(kind, value, offset)`` tokens."""
    tokens, pos = [], 0
    while pos < len(text):
        char = text[pos]
        if char.isspace():
            pos += 1
        elif char in "(),":
            tokens.append((char, char, pos))
            pos += 1
        elif char in "'\"":
            token, pos = _lex_string(text, pos)
            tokens.append(token)
        elif char.isdigit() or (char == "-" and text[pos + 1 : pos + 2].isdigit()):
            token, pos = _lex_number(text, pos)
            tokens.append(token)
        elif char.isalpha() or char == "_":
            token, pos = _lex_name(text, pos)
            tokens.append(token)
        else:
            operator = next((o for o in _OPERATORS if text.startswith(o, pos)), None)
            if operator is None:
                _fail(f"unexpected character '{char}'", pos)
            tokens.append(("op", operator, pos))
            pos += len(operator)
    tokens.append(("end", None, len(text)))
    return tokens


# ---------------------------------------------------------------------------
# Value access and comparison
# ---------------------------------------------------------------------------


def _getter(name, pos):
    if isinstance(name, tuple) and len(name) == 3:
        return _nested_getter(*name, pos)
    if isinstance(name, tuple):
        prefix, key = name
        if prefix in DICT_PREFIXES:
            return lambda row: (row.get(prefix) or {}).get(key)
        _fail(f"unknown field '{prefix}.{key}'", pos)
    parts = name.split(".")
    if len(parts) == 1:
        if name not in ROW_FIELDS:
            _fail(f"unknown field '{name}'", pos)
        return lambda row: row.get(name)
    if len(parts) == 2 and parts[0] in DICT_PREFIXES:
        prefix, key = parts
        return lambda row: (row.get(prefix) or {}).get(key)
    if len(parts) == 3:
        p0, p1, p2 = parts
        if p0 in NESTED_SUBFIELDS:
            return _nested_getter(p0, p1, p2, pos)
        if p0 == "env" and p1 == "packages":
            return lambda row: _env_packages(row).get(p2)
        _fail(f"unknown field '{name}'", pos)
    _fail(f"unknown field '{name}'", pos)


def _env_packages(row):
    """Rows carry ``env_summary()``, whose packages are the ``key_packages``."""
    env = row.get("env") or {}
    return env.get("packages") or env.get("key_packages") or {}


def _nested_getter(prefix, key, sub, pos):
    """``inputs.<name>.<sub>`` / ``outputs.<artifact path>.<sub>``."""
    allowed = NESTED_SUBFIELDS.get(prefix)
    if allowed is None:
        _fail(f"unknown field '{prefix}.\"{key}\".{sub}'", pos)
    if sub not in allowed:
        _fail(f"{prefix}.{key}.{sub}: sub-field must be {', '.join(allowed)}", pos)
    return lambda row: ((row.get(prefix) or {}).get(key) or {}).get(sub)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _equal(left, right):
    if right is None:
        return left is None
    if left is None or isinstance(left, bool) != isinstance(right, bool):
        return False
    return left == right


def _ordered(left, right, compare):
    if _is_number(left) and _is_number(right):
        return compare(left, right)
    if isinstance(left, str) and isinstance(right, str):
        return compare(left, right)
    return False


def _contains(left, right):
    """Case-insensitive substring match; lists and dicts match any element."""
    if isinstance(left, dict):
        left = list(left.values())
    if isinstance(left, (list, tuple)):
        return any(_contains(item, right) for item in left if isinstance(item, str))
    return isinstance(left, str) and right.lower() in left.lower()


_COMPARISONS = {
    "=": _equal,
    "==": _equal,
    "!=": lambda left, right: not _equal(left, right),
    "<": lambda left, right: _ordered(left, right, lambda a, b: a < b),
    "<=": lambda left, right: _ordered(left, right, lambda a, b: a <= b),
    ">": lambda left, right: _ordered(left, right, lambda a, b: a > b),
    ">=": lambda left, right: _ordered(left, right, lambda a, b: a >= b),
    "~": _contains,
    "contains": _contains,
    "!~": lambda left, right: not _contains(left, right),
}


# ---------------------------------------------------------------------------
# Parser
# ---------------------------------------------------------------------------


# How deep ``not`` and parentheses may nest. Far beyond anything a person
# writes, and far below the interpreter's recursion limit — a hostile ``?q=``
# gets a 400, not a RecursionError.
MAX_NESTING = 100


class _Parser:
    def __init__(self, text):
        self.tokens = tokenize(text)
        self.pos = 0
        self.depth = 0

    def peek(self):
        return self.tokens[self.pos]

    def next(self):
        token = self.tokens[self.pos]
        self.pos += 1
        return token

    def accept(self, kind, value=None):
        token = self.peek()
        if token[0] == kind and (value is None or token[1] == value):
            return self.next()
        return None

    def expect(self, kind, value, what):
        token = self.accept(kind, value)
        if token is None:
            _fail(f"expected {what}", self.peek()[2])
        return token

    def parse(self):
        predicate = self.parse_or()
        if self.peek()[0] != "end":
            _fail(f"unexpected {_describe(self.peek())}", self.peek()[2])
        return predicate

    # A chain of and/or terms is one flat predicate, not a nested closure per
    # term, so a 20k-term query evaluates without deep recursion.
    def parse_or(self):
        terms = [self.parse_and()]
        while self.accept("kw", "or"):
            terms.append(self.parse_and())
        if len(terms) == 1:
            return terms[0]
        return lambda row: any(term(row) for term in terms)

    def parse_and(self):
        terms = [self.parse_not()]
        while self.accept("kw", "and"):
            terms.append(self.parse_not())
        if len(terms) == 1:
            return terms[0]
        return lambda row: all(term(row) for term in terms)

    def parse_not(self):
        token = self.peek()
        if (token[0] == "kw" and token[1] == "not") or token[0] == "(":
            self.depth += 1
            if self.depth > MAX_NESTING:
                _fail(f"query nests deeper than {MAX_NESTING} levels", token[2])
            try:
                return self._parse_nested()
            finally:
                self.depth -= 1
        return self.parse_comparison()

    def _parse_nested(self):
        if self.accept("kw", "not"):
            inner = self.parse_not()
            return lambda row: not inner(row)
        self.expect("(", "(", "'('")
        inner = self.parse_or()
        self.expect(")", ")", "')'")
        return inner

    def parse_comparison(self):
        token = self.peek()
        if token[0] != "name":
            _fail(f"expected a field name, found {_describe(token)}", token[2])
        self.next()
        get = _getter(token[1], token[2])

        negate = bool(self.accept("kw", "not"))
        if self.accept("kw", "in"):
            values = self.parse_literal_list()

            def matches(row):
                return any(_equal(get(row), value) for value in values)

            return (lambda row: not matches(row)) if negate else matches
        if negate:
            _fail("expected 'in' after 'not'", self.peek()[2])

        operator = self.peek()
        if operator[0] not in ("op", "kw") or operator[1] not in _COMPARISONS:
            _fail(f"expected an operator, found {_describe(operator)}", operator[2])
        self.next()
        literal = self.parse_literal()
        if operator[1] in ("~", "!~", "contains") and not isinstance(literal, str):
            _fail(f"'{operator[1]}' needs a string on the right", operator[2])
        compare = _COMPARISONS[operator[1]]
        return lambda row: compare(get(row), literal)

    def parse_literal(self):
        token = self.next()
        if token[0] == "lit":
            return token[1]
        if token[0] == "kw" and token[1] in ("true", "false", "null"):
            return {"true": True, "false": False, "null": None}[token[1]]
        _fail(f"expected a value, found {_describe(token)}", token[2])

    def parse_literal_list(self):
        self.expect("(", "(", "'(' after 'in'")
        values = [self.parse_literal()]
        while self.accept(",", ","):
            values.append(self.parse_literal())
        self.expect(")", ")", "')'")
        return values


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


@functools.lru_cache(maxsize=256)
def compile_query(text):
    """Compile query *text* into a ``row -> bool`` predicate.

    Raises :class:`QueryError` for bad syntax, an unknown field or an operator
    used with a literal it cannot work on.

    Cached: the dashboard polls with an unchanged query, and a predicate is a
    stateless closure over the parsed expression, so it is safe to share. An
    exception is not cached — a bad query re-raises from a fresh parse.
    """
    if not text or not text.strip():
        raise QueryError("empty query")
    return _Parser(text).parse()


@functools.lru_cache(maxsize=256)
def query_roots(text):
    """The top-level row keys *text* reads (``outputs`` for
    ``outputs."a.png".size``, ``status`` for ``status = "failed"``)."""
    return frozenset(
        (value[0] if isinstance(value, tuple) else value.split(".")[0])
        for kind, value, _ in tokenize(text)
        if kind == "name"
    )


def _completing(text, extra):
    """``row -> row`` giving a row the *extra* fields ``{key: of(verstr)}``
    *text* reads but the row lacks — a copy, only for evaluating."""
    wanted = {key: of for key, of in (extra or {}).items() if key in query_roots(text)}
    if not wanted:
        return lambda row: row

    def complete(row):
        missing = {k: of(row["verstr"]) for k, of in wanted.items() if k not in row}
        return dict(row, **missing) if missing else row

    return complete


def filter_rows(rows, text, extra=None):
    """Rows matching *text*; all of them when *text* is empty or None.

    *extra* ``{key: of(verstr)}`` supplies fields kept off lean rows (the
    index snapshot's ``outputs``): a query reading one sees it, the rows
    returned are the ones given.
    """
    if not text or not text.strip():
        return rows
    predicate = compile_query(text)
    complete = _completing(text, extra)
    return [row for row in rows if predicate(complete(row))]
