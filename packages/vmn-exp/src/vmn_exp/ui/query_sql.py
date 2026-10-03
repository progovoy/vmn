#!/usr/bin/env python3
"""The query language compiled to a Postgres predicate over ``jsonb`` rows
(plan 11 §4.4, the second backend of :func:`vmn_exp.core.query.filter_rows`).

:func:`compile_sql` walks the AST of :func:`vmn_exp.core.query.parse_query`
and returns ``(where, params)``: a SQL boolean expression over a ``jsonb``
column holding the row, with every value and field name passed as a
named ``%(qN)s`` parameter (``params`` is their dict). The semantics are the Python backend's, kept two-valued:
each comparison is ``COALESCE(..., false)``, so a missing field fails it and
``not`` partitions the rows. A conformance test runs the whole query-language
corpus through both backends.
"""
import json

from vmn_exp.core.query import parse_query

# What Python's ``x or y`` treats as false, as jsonb.
_FALSY = "('null', '{}', '[]', '\"\"', '0', 'false')"


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


class _Compiler:
    def __init__(self, column):
        self.column = column
        self.params = {}

    def param(self, value, cast=""):
        name = f"q{len(self.params)}"
        self.params[name] = value
        return f"%({name})s{cast}"

    def node(self, node):
        kind = node[0]
        if kind in ("or", "and"):
            joiner = f" {kind.upper()} "
            return "(" + joiner.join(self.node(term) for term in node[1]) + ")"
        if kind == "not":
            return f"(NOT {self.node(node[1])})"
        value = self.field(node[1])
        if kind == "in":
            return "(" + " OR ".join(self.equal(value, v) for v in node[2]) + ")"
        return self.compare(value, node[2], node[3])

    def field(self, field):
        kind, arg = field
        if kind == "path":
            return f"({self.column} #> {self.param(list(arg), '::text[]')})"
        packages = f"({self.column} #> '{{env,packages}}')"
        key_packages = f"({self.column} #> '{{env,key_packages}}')"
        chosen = (
            f"(CASE WHEN {packages}::text NOT IN {_FALSY} THEN {packages}"
            f" WHEN {key_packages}::text NOT IN {_FALSY} THEN {key_packages} END)"
        )
        return f"({chosen} -> {self.param(arg)})"

    def equal(self, value, literal):
        if literal is None:
            return f"({value} IS NULL OR {value} = 'null'::jsonb)"
        return f"COALESCE({value} = {self.param(json.dumps(literal), '::jsonb')}, false)"

    def compare(self, value, op, literal):
        if op == "=":
            return self.equal(value, literal)
        if op == "!=":
            return f"(NOT {self.equal(value, literal)})"
        if op == "~":
            return self.contains(value, literal)
        if op == "!~":
            return f"(NOT {self.contains(value, literal)})"
        return self.ordered(value, op, literal)

    def ordered(self, value, op, literal):
        if _is_number(literal):
            typed, operand = "number", f"({value})::numeric"
            right = self.param(repr(literal), "::numeric")
        elif isinstance(literal, str):
            typed, operand = "string", f'({value} #>> \'{{}}\') COLLATE "C"'
            right = self.param(literal, "::text")
        else:
            return "false"
        return (
            f"COALESCE(CASE WHEN jsonb_typeof({value}) = '{typed}'"
            f" THEN {operand} {op} {right} ELSE false END, false)"
        )

    def contains(self, value, literal):
        def hit(expr):
            return (
                f"(jsonb_typeof({expr}) = 'string' AND"
                f" strpos(lower({expr} #>> '{{}}'), lower({self.param(literal, '::text')})) > 0)"
            )

        return (
            f"COALESCE(CASE jsonb_typeof({value})"
            f" WHEN 'string' THEN {hit(value)}"
            f" WHEN 'array' THEN EXISTS (SELECT 1 FROM jsonb_array_elements({value}) e"
            f" WHERE {hit('e')})"
            f" WHEN 'object' THEN EXISTS (SELECT 1 FROM jsonb_each({value}) o"
            f" WHERE {hit('o.value')}) ELSE false END, false)"
        )


def compile_sql(text, column="data"):
    """``(where, params)`` matching query *text* over the jsonb *column*;
    ``("true", {})`` for an empty query. Raises ``QueryError`` like
    :func:`~vmn_exp.core.query.compile_query`."""
    if not text or not text.strip():
        return "true", {}
    compiler = _Compiler(column)
    where = compiler.node(parse_query(text))
    return where, compiler.params
