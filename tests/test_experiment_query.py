"""Pure-function tests for the experiment-run query language.

No git, no docker, no storage — rows are hand-built dicts shaped like the ones
``core.experiment_log.experiment_row`` + ``status_fields`` + ``annotate_tree``
produce, so these guard the one predicate the CLI, the REST API, the ui and the
SDK all share.
"""
import pytest

from version_stamp.core.experiment_query import (
    QueryError,
    compile_query,
    filter_rows,
)


def _row(verstr, **kw):
    row = {
        "idx": 1,
        "verstr": verstr,
        "code_verstr": verstr,
        "timestamp": "2026-09-21T12:00:00Z",
        "note": None,
        "branch": "master",
        "base_version": "0.0.1",
        "parent": None,
        "metrics": {},
        "status": "succeeded",
        "tree_status": "succeeded",
        "kind": "single",
        "depth": 0,
        "exit_code": 0,
        "duration_sec": 10.0,
    }
    row.update(kw)
    return row


ROWS = [
    _row("0.0.1", idx=1, status="succeeded", metrics={"loss": 0.25, "acc": 0.9},
         note="baseline run", duration_sec=100.0, exit_code=0),
    _row("0.0.2", idx=2, status="failed", metrics={"loss": 0.75},
         note="tweaked lr", duration_sec=700.0, exit_code=1),
    _row("0.0.3", idx=3, status="stuck", metrics={}, note=None,
         duration_sec=None, exit_code=None, kind="outer", depth=0),
    _row("0.0.4", idx=4, status="running", metrics={"loss": 0.1},
         note="Baseline again", duration_sec=5.0, exit_code=None,
         kind="inner", depth=1, parent="0.0.3"),
]


def _verstrs(text, rows=ROWS):
    return [r["verstr"] for r in filter_rows(rows, text)]


# ---- comparison operators --------------------------------------------------


def test_equality_on_string_field():
    assert _verstrs('status = "failed"') == ["0.0.2"]


def test_equality_accepts_double_equals():
    assert _verstrs('status == "failed"') == ["0.0.2"]


def test_inequality_on_string_field():
    assert _verstrs('status != "failed"') == ["0.0.1", "0.0.3", "0.0.4"]


def test_single_quoted_string_literal():
    assert _verstrs("status = 'stuck'") == ["0.0.3"]


def test_less_than_on_metric():
    assert _verstrs("metrics.loss < 0.5") == ["0.0.1", "0.0.4"]


def test_less_or_equal_on_metric():
    assert _verstrs("metrics.loss <= 0.25") == ["0.0.1", "0.0.4"]


def test_greater_than_on_metric():
    assert _verstrs("metrics.loss > 0.25") == ["0.0.2"]


def test_greater_or_equal_on_duration():
    assert _verstrs("duration_sec >= 600") == ["0.0.2"]


def test_integer_literal_compares_with_float_field():
    assert _verstrs("exit_code = 1") == ["0.0.2"]


def test_bare_top_level_int_field():
    assert _verstrs("idx > 2") == ["0.0.3", "0.0.4"]


def test_depth_field():
    assert _verstrs("depth = 1") == ["0.0.4"]


# ---- literals --------------------------------------------------------------


def test_true_literal():
    rows = [_row("1.0.0", metrics={"ok": True}), _row("2.0.0", metrics={"ok": False})]
    assert _verstrs("metrics.ok = true", rows) == ["1.0.0"]


def test_false_literal():
    rows = [_row("1.0.0", metrics={"ok": True}), _row("2.0.0", metrics={"ok": False})]
    assert _verstrs("metrics.ok = false", rows) == ["2.0.0"]


def test_keywords_are_case_insensitive():
    assert _verstrs('status = "failed" OR status = "stuck"') == ["0.0.2", "0.0.3"]
    assert _verstrs('NOT (status = "failed") AND idx < 3') == ["0.0.1"]
    assert _verstrs('status IN ("failed")') == ["0.0.2"]


def test_field_names_stay_case_sensitive():
    with pytest.raises(QueryError):
        compile_query('STATUS = "failed"')


def test_string_literal_comparison_stays_case_sensitive():
    assert _verstrs('note = "baseline run"') == ["0.0.1"]
    assert _verstrs('note = "BASELINE RUN"') == []


# ---- boolean composition ---------------------------------------------------


def test_and_composition():
    assert _verstrs('status = "succeeded" and metrics.loss < 0.5') == ["0.0.1"]


def test_or_composition():
    assert _verstrs('status = "failed" or status = "running"') == ["0.0.2", "0.0.4"]


def test_not_composition():
    assert _verstrs('not status = "succeeded"') == ["0.0.2", "0.0.3", "0.0.4"]


def test_and_binds_tighter_than_or():
    # parsed as (loss > 0.5 and status = "failed") or status = "running"
    text = 'metrics.loss > 0.5 and status = "failed" or status = "running"'
    assert _verstrs(text) == ["0.0.2", "0.0.4"]


def test_parentheses_override_precedence():
    text = 'metrics.loss > 0.5 and (status = "failed" or status = "running")'
    assert _verstrs(text) == ["0.0.2"]


def test_not_binds_tighter_than_and():
    # parsed as (not status = "failed") and idx <= 2
    assert _verstrs('not status = "failed" and idx <= 2') == ["0.0.1"]


def test_nested_parentheses():
    assert _verstrs('((idx = 1) or ((idx = 4)))') == ["0.0.1", "0.0.4"]


# ---- in --------------------------------------------------------------------


def test_in_literal_list():
    assert _verstrs('status in ("running", "stuck")') == ["0.0.3", "0.0.4"]


def test_in_numeric_list():
    assert _verstrs("idx in (1, 4)") == ["0.0.1", "0.0.4"]


def test_not_in_literal_list():
    assert _verstrs('status not in ("running", "stuck")') == ["0.0.1", "0.0.2"]


def test_in_is_false_for_missing_field():
    assert _verstrs('metrics.nope in (1, 2)') == []


def test_in_requires_a_list():
    with pytest.raises(QueryError):
        compile_query('status in "running"')


# ---- string matching -------------------------------------------------------


def test_tilde_is_case_insensitive_substring_match():
    assert _verstrs('note ~ "baseline"') == ["0.0.1", "0.0.4"]


def test_contains_is_an_alias_for_tilde():
    assert _verstrs('note contains "baseline"') == ["0.0.1", "0.0.4"]


def test_negated_substring_match():
    assert _verstrs('note !~ "baseline"') == ["0.0.2", "0.0.3"]


def test_substring_match_on_missing_note_is_false():
    assert _verstrs('note ~ "anything"') == []


def test_substring_match_against_non_string_field_is_false():
    assert _verstrs('metrics.loss ~ "0.25"') == []


def test_substring_match_requires_a_string_literal():
    with pytest.raises(QueryError):
        compile_query("note ~ 3")


# ---- fields ----------------------------------------------------------------


def test_nested_metric_access():
    assert _verstrs("metrics.acc >= 0.9") == ["0.0.1"]


def test_params_prefix_resolves_against_the_rows_params_not_metrics():
    """``params.`` addresses the row's verbatim params dict, ``metrics.`` the metrics.

    It used to alias the metrics lookup, which made a string param unqueryable.
    """
    rows = [
        _row("1.0.0", params={"lr": 0.01}, metrics={"lr": 0.01, "loss": 9.0}),
        _row("2.0.0", params={"lr": 0.5}, metrics={"lr": 0.5, "loss": 0.1}),
    ]
    assert _verstrs("params.lr < 0.1", rows) == ["1.0.0"]
    assert _verstrs("params.loss < 1", rows) == []
    assert _verstrs("metrics.loss < 1", rows) == ["2.0.0"]


def test_params_prefix_matches_a_string_param():
    rows = [
        _row("1.0.0", params={"model": "xgb"}, metrics={}),
        _row("2.0.0", params={"model": "linear"}, metrics={}),
    ]
    assert _verstrs('params.model = "xgb"', rows) == ["1.0.0"]


def test_params_prefix_matches_a_boolean_param():
    rows = [
        _row("1.0.0", params={"cache": True}, metrics={"cache": 1.0}),
        _row("2.0.0", params={"cache": False}, metrics={"cache": 0.0}),
    ]
    assert _verstrs("params.cache = true", rows) == ["1.0.0"]
    assert _verstrs("params.cache = false", rows) == ["2.0.0"]


def test_params_prefix_on_a_row_without_params_matches_nothing():
    assert _verstrs('params.model = "xgb"') == []


def test_unknown_top_level_field_is_a_query_error():
    with pytest.raises(QueryError) as exc:
        compile_query('statuz = "failed"')
    assert "statuz" in str(exc.value)


def test_unknown_metric_name_is_allowed_and_simply_matches_nothing():
    assert _verstrs("metrics.made_up < 1") == []


def test_deep_dotted_path_beyond_metrics_is_rejected():
    with pytest.raises(QueryError):
        compile_query("metrics.a.b < 1")


# ---- missing values and None semantics -------------------------------------


def test_missing_metric_does_not_crash_and_fails_the_test():
    assert "0.0.3" not in _verstrs("metrics.loss < 0.5")


def test_none_field_fails_every_ordering_comparison():
    row = _row("9.9.9", duration_sec=None)
    for text in (
        "duration_sec < 1",
        "duration_sec <= 1",
        "duration_sec > 1",
        "duration_sec >= 1",
    ):
        assert filter_rows([row], text) == []


def test_not_of_a_failing_comparison_is_true_for_missing_fields():
    # Two-valued semantics: a query and its `not` partition the rows, so a row
    # without the metric shows up in exactly one of the two.
    yes = set(_verstrs("metrics.loss < 0.5"))
    no = set(_verstrs("not (metrics.loss < 0.5)"))
    assert yes == {"0.0.1", "0.0.4"}
    assert no == {"0.0.2", "0.0.3"}
    assert yes | no == {r["verstr"] for r in ROWS}
    assert not yes & no


def test_equals_null_tests_for_missing_or_none():
    assert _verstrs("metrics.loss = null") == ["0.0.3"]
    assert _verstrs("duration_sec = null") == ["0.0.3"]


def test_not_equals_null_tests_for_presence():
    assert _verstrs("metrics.loss != null") == ["0.0.1", "0.0.2", "0.0.4"]


def test_not_equals_a_value_is_true_when_the_field_is_missing():
    assert _verstrs("metrics.loss != 0.25") == ["0.0.2", "0.0.3", "0.0.4"]


# ---- type handling ---------------------------------------------------------


def test_number_versus_string_ordering_is_false_not_a_typeerror():
    assert filter_rows(ROWS, 'metrics.loss < "abc"') == []


def test_string_field_ordering_is_lexicographic():
    assert _verstrs('verstr < "0.0.3"') == ["0.0.1", "0.0.2"]


def test_string_versus_number_ordering_is_false():
    assert _verstrs("verstr < 1") == []


def test_booleans_are_not_compared_as_numbers():
    rows = [_row("1.0.0", metrics={"ok": True})]
    assert filter_rows(rows, "metrics.ok > 0") == []


# ---- syntax errors ---------------------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        "",
        "   ",
        "(idx = 1",
        "idx = 1)",
        "idx = ",
        "idx = 1 and",
        "and idx = 1",
        "idx === 1",
        'note ~ "unterminated',
        "idx = 1 idx = 2",
        "idx",
        "= 1",
        "idx in ()",
        "idx in (1,)",
        "not",
        "idx $ 1",
    ],
)
def test_malformed_queries_raise_query_error(text):
    with pytest.raises(QueryError):
        compile_query(text)


def test_unbalanced_paren_message_points_at_the_problem():
    with pytest.raises(QueryError) as exc:
        compile_query("(idx = 1")
    msg = str(exc.value)
    assert ")" in msg
    assert "at " in msg


def test_trailing_operator_message_mentions_the_position():
    with pytest.raises(QueryError) as exc:
        compile_query("idx = 1 and")
    assert "at " in str(exc.value)


def test_unknown_operator_message_names_the_offending_text():
    with pytest.raises(QueryError) as exc:
        compile_query("idx $ 1")
    assert "$" in str(exc.value)


def test_unterminated_string_says_so():
    with pytest.raises(QueryError) as exc:
        compile_query('note ~ "oops')
    assert "unterminated" in str(exc.value).lower()


def test_injection_flavored_input_is_rejected_not_evaluated():
    with pytest.raises(QueryError):
        compile_query('metrics.loss < 0.5) or __import__("os")')


def test_dunder_call_syntax_is_rejected():
    with pytest.raises(QueryError):
        compile_query('__import__("os").system("touch /tmp/pwned")')


# ---- convenience surface ---------------------------------------------------


def test_compile_query_returns_a_reusable_predicate():
    predicate = compile_query("metrics.loss < 0.5")
    assert predicate(ROWS[0]) is True
    assert predicate(ROWS[1]) is False
    assert predicate(ROWS[0]) is True


def test_filter_rows_returns_the_same_row_objects():
    out = filter_rows(ROWS, "idx = 1")
    assert out[0] is ROWS[0]


def test_filter_rows_with_no_query_returns_everything():
    assert filter_rows(ROWS, None) is ROWS
    assert filter_rows(ROWS, "") is ROWS
    assert filter_rows(ROWS, "  ") is ROWS


def test_predicate_tolerates_a_row_missing_status_entirely():
    assert filter_rows([{"verstr": "1.0.0"}], 'status = "failed"') == []
    assert filter_rows([{"verstr": "1.0.0"}], "status = null") == [
        {"verstr": "1.0.0"}
    ]


def test_compiling_the_same_query_reuses_the_predicate():
    """The dashboard polls with an unchanged ``q``; reparsing it every request
    is pure waste, so identical text must hand back the identical predicate."""
    first = compile_query('metrics.loss < 0.5 and status = "succeeded"')
    second = compile_query('metrics.loss < 0.5 and status = "succeeded"')
    assert first is second
    # Still a correct predicate, not just a cached object.
    assert first({"status": "succeeded", "metrics": {"loss": 0.2}}) is True
    assert first({"status": "failed", "metrics": {"loss": 0.2}}) is False


def test_a_bad_query_is_not_cached_as_a_success():
    for _ in range(2):
        with pytest.raises(QueryError):
            compile_query("metrics.loss <")
