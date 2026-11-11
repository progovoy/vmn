"""``list_experiments``' parameters grouped by what they select (plan 42
E12d): one pure ``resolve_mode`` names the answer's shape (flat page, groups,
tree page) and whether it is a Jobs view, or refuses a combination naming
the parameters that conflict."""
import pytest

pytest.importorskip("fastapi")
from fastapi import HTTPException  # noqa: E402

from vmn_exp.ui.leaderboard_params import (  # noqa: E402
    FLAT,
    GROUPED,
    TREE,
    GroupParams,
    JobAggParams,
    Mode,
    PageParams,
    TreeParams,
    resolve_mode,
)


def _mode(top=None, by_comments=False, page=None, group=None, tree=None, job_agg=None):
    return resolve_mode(page or PageParams(), group or GroupParams(), tree or TreeParams(),
                        job_agg or JobAggParams(), top=top, by_comments=by_comments)


def _refusal(**given):
    with pytest.raises(HTTPException) as caught:
        _mode(**given)
    assert caught.value.status_code == 400
    return caught.value.detail


@pytest.mark.parametrize("given, mode", [
    ({}, Mode(FLAT, jobs=False)),
    (dict(top=True), Mode(FLAT, jobs=True)),
    (dict(top="jobs", page=PageParams(top_q="status = running")), Mode(FLAT, jobs=True)),
    (dict(page=PageParams(cursor="c", last=5)), Mode(FLAT, jobs=False)),
    (dict(group=GroupParams(group="parent")), Mode(GROUPED, jobs=False)),
    (dict(top=True, group=GroupParams(group="parent", collapse_all=True)),
     Mode(GROUPED, jobs=True)),
    (dict(tree=TreeParams(children_of="v")), Mode(TREE, jobs=False)),
    (dict(top=True, tree=TreeParams(children_of="v")), Mode(TREE, jobs=True)),
    (dict(top=True, job_agg=JobAggParams(job_agg="max")), Mode(FLAT, jobs=True)),
])
def test_each_documented_combination_resolves_to_its_mode(given, mode):
    assert _mode(**given) == mode


def test_top_q_without_top_is_refused():
    assert "top_q" in _refusal(page=PageParams(top_q="status = running"))


@pytest.mark.parametrize("given", [
    dict(group=GroupParams(collapse_all=True)),
    dict(top=True, group=GroupParams(collapse_all=True)),
    dict(group=GroupParams(group="parent", collapse_all=True)),
])
def test_collapse_all_needs_group_and_top(given):
    assert "collapse_all" in _refusal(**given)


def test_job_agg_nested_belongs_to_the_job_aggregation_mode():
    assert "job_agg" in _refusal(job_agg=JobAggParams(job_agg_nested=True))
    assert _mode(top=True, job_agg=JobAggParams(job_agg_nested=True)).jobs
    assert JobAggParams(job_agg_nested=True).given() == {
        "agg": None, "by": None, "value": None, "metric": None, "nested": True}


@pytest.mark.parametrize("given, named", [
    (dict(group=GroupParams(group="parent"), page=PageParams(last=3)), "last"),
    (dict(group=GroupParams(group="parent"), page=PageParams(cursor="c")), "cursor"),
    (dict(tree=TreeParams(children_of="v"), group=GroupParams(group="parent")), "group"),
    (dict(tree=TreeParams(children_of="v"), by_comments=True), "comments"),
])
def test_the_existing_cross_checks_name_the_conflicting_parameters(given, named):
    assert named in _refusal(**given)
