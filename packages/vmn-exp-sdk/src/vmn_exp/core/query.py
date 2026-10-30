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
    primary    = "(" or_expr ")" | ( "under" | "similar" ) "(" string ")" | comparison
    comparison = any_field cmp_op literal
               | any_field ( "<" | "<=" | ">" | ">=" ) "ago" "(" string ")"
               | any_field [ "not" ] "in" "(" literal { "," literal } ")"
    any_field  = field | "up." up_field | "up" "(" up_field ( "=" | "==" ) literal ")" "." up_field
    up_field   = ( "params" | "tags" ) "." ( name | string ) | "name"
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
``archived = true`` the archived runs. ``author ~ "alice"`` matches who ran it
(git email, else OS user, else writer) and ``has_intent = false`` the runs
nobody described yet; ``intent ~ "focal"`` reads the latest intent's text
and ``keywords ~ "imbalance"`` its keywords; ``notes ~ "sigterm"`` matches
the run's note signatures (:mod:`vmn_exp.core.note_sigs`). ``under("<verstr>")`` matches
the runs in that run's subtree (not the run itself) and ``similar("<text>")``
the runs whose similar-runs text document holds every word of the text
(:mod:`vmn_exp.core.query_similar`). ``up.params.trade_date`` reads the
nearest ancestor holding that param and ``up(tags.kind = "study").params.group``
the nearest ancestor whose ``tags.kind`` is ``"study"``
(:mod:`vmn_exp.core.query_up`; the built-in ``kind`` is no selector).
``timestamp < ago("1h")`` compares with the UTC ISO time that long before
now (``30m``, ``1h``, ``2d``; :mod:`vmn_exp.core.query_ago`): every entry
point pins it to that time when it compiles a query (:func:`pin_ago`), so no
cache keeps a query's clock.
"""

import functools

from vmn_exp.core.query_ago import ORDERED, duration_sec, iso_before
from vmn_exp.core.query_up import UP, dig, readable, rows_ancestor_fields
from vmn_exp.core.query_up import equal as _equal
from vmn_exp.core.system_metrics import is_system_metric
from vmn_exp.core.tree import ancestry_of

# Every non-metric field a row can carry, from ``experiment_row`` +
# ``experiment_status.status_fields`` + ``experiment_tree.annotate_tree``
# (``queue_sec``) + the board's ``duration_ratio`` (plan 28 N4).
# Spelled out so a typo is a query error instead of a silently empty result;
# BELOW_FIELDS are the Jobs view's counts of the runs below a top-level row.
BELOW_FIELDS = frozenset({"live_below", "running_below", "stuck_below"})
ROW_FIELDS = BELOW_FIELDS | frozenset(
    """
    idx verstr code_verstr timestamp note branch base_version parent
    name archived tags last_metric_at status exit_code started_at finished_at heartbeat
    duration_sec pid host command stale_sec heartbeat_interval_sec children
    kind depth tree_status settled imported_from forked_from forked_from_step rerun_of
    author has_intent intent keywords notes
    end_reason error_summary signal root failure_sig released_at resume_count
    queue_sec duration_ratio
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

# ``under("v")`` reads each row's ancestor verstrs, supplied as this field.
UNDER, ANCESTORS = "under", "ancestors"
# ``similar("text")`` reads a resolver ``text -> verstrs`` given as this extra.
SIMILAR = "similar"
# The ``sys_*`` metrics kept off lean rows, ``verstr -> {metric: value}``, as this extra.
SYSTEM_METRICS = "system_metrics"
AGO = "ago"
_CALLS = {UNDER: "under() takes one quoted verstr", SIMILAR: "similar() takes one quoted text"}
_CALL_FIELDS = {UNDER: ANCESTORS, SIMILAR: SIMILAR}  # what a call's predicate reads


def _has_words(text):
    """Whether ``similar(text)`` has a word to match (what it matches on)."""
    from vmn_exp.core.similar_match import words  # the FTS layer, only when asked

    return bool(words(text))

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
    dot = "." if kind == "dot" else ""
    if kind in ("name", "dot") and isinstance(value, tuple):
        prefix, key = value[:2]
        sub = f".{value[2]}" if len(value) == 3 else ""
        return f"'{dot}{prefix}.\"{key}\"{sub}'"
    return f"'{dot}{value}'"


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
        elif char == "." and (text[pos + 1 : pos + 2].isalpha() or text.startswith("._", pos)):
            (_, value, _), pos = _lex_name(text, pos + 1)  # ``up(...).params.k``
            tokens.append(("dot", value, pos))
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


def _field(name, pos):
    """The AST field node *name* reads: ``("path", keys)``,
    ``("env_packages", package)`` or ``("up", None, keys)``."""
    inner = _without_up(name)
    if inner is not None:
        return up_field(None, inner, pos)
    if isinstance(name, tuple) and len(name) == 3:
        return _nested_field(*name, pos)
    if isinstance(name, tuple):
        prefix, key = name
        if prefix in DICT_PREFIXES:
            return ("path", (prefix, key))
        _fail(f"unknown field '{prefix}.{key}'", pos)
    parts = name.split(".")
    if len(parts) == 1:
        if name not in ROW_FIELDS:
            _fail(f"unknown field '{name}'", pos)
        return ("path", (name,))
    if len(parts) == 2 and parts[0] in DICT_PREFIXES:
        return ("path", tuple(parts))
    if len(parts) == 3:
        p0, p1, p2 = parts
        if p0 in NESTED_SUBFIELDS:
            return _nested_field(p0, p1, p2, pos)
        if p0 == "env" and p1 == "packages":
            return ("env_packages", p2)
    _fail(f"unknown field '{name}'", pos)


def _without_up(name):
    """*name* past its ``up.`` prefix, or None when it has none."""
    head, dot, rest = (name[0] if isinstance(name, tuple) else name).partition(".")
    if head != UP or not dot or not rest:
        return None
    return (rest,) + name[1:] if isinstance(name, tuple) else rest


def _readable_keys(name, pos, message):
    """The keys of *name*, a field an ``up`` field may read, else *message*."""
    field = _field(name, pos)
    if field[0] != "path" or not readable(field[1]):
        _fail(message, pos)
    return field[1]


def up_field(selector, name, pos):
    """The ``up`` field node reading *name* of the nearest ancestor holding
    it (*selector* None) or matching *selector* ``(keys, literal)``."""
    keys = _readable_keys(name, pos, "an up field reads params.<key>, tags.<key> or name")
    return (UP, selector, keys)


def _nested_field(prefix, key, sub, pos):
    """``inputs.<name>.<sub>`` / ``outputs.<artifact path>.<sub>``."""
    allowed = NESTED_SUBFIELDS.get(prefix)
    if allowed is None:
        _fail(f"unknown field '{prefix}.\"{key}\".{sub}'", pos)
    if sub not in allowed:
        _fail(f"{prefix}.{key}.{sub}: sub-field must be {', '.join(allowed)}", pos)
    return ("path", (prefix, key, sub))


def _env_packages(row):
    """Rows carry ``env_summary()``, whose packages are the ``key_packages``."""
    env = row.get("env") or {}
    return env.get("packages") or env.get("key_packages") or {}


def _getter(field):
    if field[0] == UP:  # the row's ``up`` reader (filter_rows supplies it)
        def ancestor(row):
            reader = row.get(UP)
            return reader(field) if reader else None
        return ancestor
    kind, arg = field
    if kind == "env_packages":
        return lambda row: _env_packages(row).get(arg)
    return lambda row: dig(row, arg)


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


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


_CANONICAL_OPS = {"==": "=", "contains": "~"}


def _predicate(node):
    """Compile an AST *node* (see :func:`parse_query`) to ``row -> bool``."""
    kind = node[0]
    if kind in ("or", "and"):
        terms = [_predicate(term) for term in node[1]]
        combine = any if kind == "or" else all
        return lambda row: combine(term(row) for term in terms)
    if kind == "not":
        inner = _predicate(node[1])
        return lambda row: not inner(row)
    if kind in _CALLS:  # the row's ancestors / similar() texts hold the argument
        arg, key = node[1], _CALL_FIELDS[kind]
        return lambda row: arg in (row.get(key) or ())
    get = _getter(node[1])
    if kind == "in":
        values = node[2]
        return lambda row: any(_equal(get(row), value) for value in values)
    compare, literal = _COMPARISONS[node[2]], node[3]
    return lambda row: compare(get(row), literal)


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
        self.agos = []  # (start, end, seconds) of each ``ago(...)``

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
        tree = self.parse_or()
        if self.peek()[0] != "end":
            _fail(f"unexpected {_describe(self.peek())}", self.peek()[2])
        return tree

    # A chain of and/or terms is one flat node, not a nested one per term, so
    # a 20k-term query evaluates without deep recursion.
    def parse_or(self):
        terms = [self.parse_and()]
        while self.accept("kw", "or"):
            terms.append(self.parse_and())
        return terms[0] if len(terms) == 1 else ("or", tuple(terms))

    def parse_and(self):
        terms = [self.parse_not()]
        while self.accept("kw", "and"):
            terms.append(self.parse_not())
        return terms[0] if len(terms) == 1 else ("and", tuple(terms))

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
            return ("not", self.parse_not())
        self.expect("(", "(", "'('")
        inner = self.parse_or()
        self.expect(")", ")", "')'")
        return inner

    def parse_comparison(self):
        token = self.peek()
        if token[0] != "name":
            _fail(f"expected a field name, found {_describe(token)}", token[2])
        self.next()
        if token[1] in _CALLS and self.peek()[0] == "(":
            return self.parse_call(token[1])
        field = self.field_of(token)

        negate = bool(self.accept("kw", "not"))
        if self.accept("kw", "in"):
            node = ("in", field, tuple(self.parse_literal_list()))
            return ("not", node) if negate else node
        if negate:
            _fail("expected 'in' after 'not'", self.peek()[2])

        operator = self.peek()
        if operator[0] not in ("op", "kw") or operator[1] not in _COMPARISONS:
            _fail(f"expected an operator, found {_describe(operator)}", operator[2])
        self.next()
        if self.peek()[:2] == ("name", AGO):
            return ("cmp", field, operator[1], self.parse_ago(operator))
        literal = self.parse_literal()
        if operator[1] in ("~", "!~", "contains") and not isinstance(literal, str):
            _fail(f"'{operator[1]}' needs a string on the right", operator[2])
        return ("cmp", field, _CANONICAL_OPS.get(operator[1], operator[1]), literal)

    def parse_call(self, name):
        """``under("<verstr>")`` (the rows in that run's subtree) or
        ``similar("<text>")`` (the runs whose text holds its words)."""
        self.next()
        token = self.next()
        if token[0] != "lit" or not isinstance(token[1], str):
            _fail(_CALLS[name], token[2])
        if name == SIMILAR and not _has_words(token[1]):
            _fail("similar() needs a word to match", token[2])
        self.expect(")", ")", "')'")
        return (name, token[1])

    def parse_ago(self, operator):
        """``ago("<duration>")`` right of an ordering *operator*: its seconds,
        its span recorded for :func:`pin_ago`."""
        start = self.next()[2]
        if operator[1] not in ORDERED:
            _fail("ago() compares with <, <=, > or >=", start)
        self.expect("(", "(", "'(' after 'ago'")
        token = self.next()
        seconds = duration_sec(token[1]) if token[0] == "lit" else None
        if seconds is None:
            _fail('ago() takes a duration like "30m", "1h" or "2d"', token[2])
        end = self.expect(")", ")", "')'")[2] + 1
        self.agos.append((start, end, seconds))
        return seconds

    def field_of(self, token):
        """The field node the name *token*, just read, starts."""
        if token[1] == UP and self.peek()[0] == "(":
            return self.parse_up()
        return _field(token[1], token[2])

    def parse_up(self):
        """``up(<field> = <literal>).<field>``: the field of the nearest
        ancestor whose first field equals the literal."""
        self.next()
        token = self.next()
        if token[0] != "name":
            _fail("up() selects on params.<key>, tags.<key> or name", token[2])
        selector = _readable_keys(token[1], token[2],
                                  "up() selects on params.<key>, tags.<key> or name")
        operator = self.next()
        if operator[0] != "op" or operator[1] not in ("=", "=="):
            _fail("up() takes one '<field> = <value>'", operator[2])
        literal = self.parse_literal()
        if literal is None:
            _fail("up() matches a value, not null", operator[2])
        self.expect(")", ")", "')'")
        dot = self.next()
        if dot[0] != "dot":
            _fail("expected '.<field>' after up(...)", dot[2])
        return up_field((selector, literal), dot[1], dot[2])

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
def _parsed(text):
    """``(tree, ago spans)`` of *text*, its ``ago()`` calls unpinned."""
    parser = _Parser(text)
    return parser.parse(), tuple(parser.agos)


def pin_ago(text, now=None):
    """*text* with each ``ago("<duration>")`` replaced by the quoted UTC ISO
    time that long before *now* (default the clock); *text* itself when it
    has none. Raises :class:`QueryError` (offsets in *text*) when it has one
    and does not compile."""
    if not text or AGO not in text:
        return text
    out, at = [], 0
    for start, end, seconds in _parsed(text)[1]:
        out += [text[at:start], f'"{iso_before(seconds, now)}"']
        at = end
    return "".join(out) + text[at:]


def parse_query(text):
    """The AST of query *text*: ``("or"|"and", [nodes])``, ``("not", node)``,
    ``("in", field, [literals])`` or ``("cmp", field, op, literal)``, with
    ``op`` one of ``= != < <= > >= ~ !~`` and ``field`` either
    ``("path", keys)`` (nested dict keys from the row) or
    ``("env_packages", package)`` or ``("up", selector, keys)``
    (:mod:`vmn_exp.core.query_up`); ``under("v")`` is ``("under", v)``, ``similar("t")``
    ``("similar", t)``. Raises :class:`QueryError` like
    :func:`compile_query`; the SQL backend compiles the same tree. Its
    ``ago()`` calls are pinned to now (:func:`pin_ago`)."""
    if not text or not text.strip():
        raise QueryError("empty query")
    return _parsed(pin_ago(text))[0]


@functools.lru_cache(maxsize=256)
def parse_field(text):
    """The field node of *text*, one field alone (``params.lr``,
    ``up(tags.kind = "study").params.group``); :class:`QueryError` otherwise."""
    parser = _Parser(text or "")
    token = parser.next()
    if token[0] != "name":
        _fail(f"expected a field name, found {_describe(token)}", token[2])
    field = parser.field_of(token)
    if parser.peek()[0] != "end":
        _fail(f"unexpected {_describe(parser.peek())}", parser.peek()[2])
    return field


def compile_query(text):
    """Compile query *text* into a ``row -> bool`` predicate.

    Raises :class:`QueryError` for bad syntax, an unknown field or an operator
    used with a literal it cannot work on.

    Cached: the dashboard polls with an unchanged query, and a predicate is a
    stateless closure over the parsed expression, so it is safe to share. An
    exception is not cached — a bad query re-raises from a fresh parse. A
    query with ``ago()`` is cached by its pinned text (:func:`pin_ago`).
    """
    return _compiled(pin_ago(text))


@functools.lru_cache(maxsize=256)
def _compiled(text):
    return _predicate(parse_query(text))


@functools.lru_cache(maxsize=256)
def query_roots(text):
    """The top-level row keys *text* reads (``outputs`` for
    ``outputs."a.png".size``, ``status`` for ``status = "failed"``)."""
    roots = (
        (value[0] if isinstance(value, tuple) else value).split(".")[0]
        for kind, value, _ in tokenize(text)
        if kind == "name"
    )
    return frozenset(ANCESTORS if root == UNDER else root for root in roots)


@functools.lru_cache(maxsize=256)
def reads_system_metrics(text):
    """Whether *text* reads a ``metrics.sys_*`` field."""
    return any(kind == "name" and is_system_metric(_metric_of(value))
               for kind, value, _ in tokenize(text))


def _metric_of(name):
    """The metric a ``metrics.<k>`` field name reads, else ``""``."""
    if isinstance(name, tuple):
        return name[1] if name[0] == "metrics" and len(name) == 2 else ""
    root, _, key = name.partition(".")
    return key if root == "metrics" else ""


def _completing(text, extra):
    """``row -> row`` giving a row the *extra* fields ``{key: of(verstr)}``
    *text* reads but the row lacks — a copy, only for evaluating — and, when
    it reads a ``sys_*`` metric, the metrics ``extra["system_metrics"]``
    keeps off the row."""
    wanted = {key: of for key, of in (extra or {}).items() if key in query_roots(text)}
    system_of = (extra or {}).get(SYSTEM_METRICS) if reads_system_metrics(text) else None
    if not wanted and system_of is None:
        return lambda row: row

    def complete(row):
        missing = {k: of(row["verstr"]) for k, of in wanted.items() if k not in row}
        system = system_of(row["verstr"]) if system_of else None
        if system:
            missing["metrics"] = {**row.get("metrics", {}), **system}
        return dict(row, **missing) if missing else row

    return complete


def filter_rows(rows, text, extra=None):
    """Rows matching *text*; all of them when *text* is empty or None.

    *extra* ``{key: of(verstr)}`` supplies fields kept off lean rows (the
    index snapshot's ``outputs``, :mod:`vmn_exp.core.query_extra`): a query
    reading one sees it, the rows returned are the ones given. ``under()``
    reads ``ancestors``, by default from the *rows*' own ``parent`` links;
    ``similar()`` asks ``extra["similar"](text)`` for its verstrs, once per
    distinct text (:func:`~vmn_exp.core.query_similar.similar_hits`); an
    ``up`` field reads ``extra["up"](verstr)(node)``, by default over the
    *rows* (:mod:`vmn_exp.core.query_up`).
    """
    if not text or not text.strip():
        return rows
    predicate = compile_query(text)
    roots = query_roots(text)
    if ANCESTORS in roots and ANCESTORS not in (extra or {}):
        extra = dict(extra or {}, ancestors=ancestry_of(rows))
    if UP in roots and UP not in (extra or {}):
        extra = dict(extra or {}, up=rows_ancestor_fields(rows).of)
    if SIMILAR in roots:
        from vmn_exp.core.query_similar import similar_hits  # it imports this module

        extra = dict(extra or {}, similar=similar_hits(parse_query(text), extra))
    complete = _completing(text, extra)
    return [row for row in rows if predicate(complete(row))]
