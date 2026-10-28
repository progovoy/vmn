"""Plan 28 P4: an app's team views, settings/conf ``experiment.ui.views:
[{name, page: jobs|runs|job, search, default}]``, at most 20, one default
per page — validated when settings are parsed, read tolerantly from a conf."""
import pytest
import yaml
from vmn_exp.core.app_settings import MAX_VIEWS, SettingsError, parse_settings, views_entries

GOOD = """\
ui:
  views:
    - {name: health, page: runs, search: '?show=t:health&show=t:state', default: true}
    - {name: by kind, page: job, search: 'group=tags.kind'}
    - {name: health, page: jobs, search: ''}
"""


def test_views_are_kept_and_read_with_their_defaults():
    settings = parse_settings(GOOD)
    assert views_entries(settings["ui"]) == [
        {"name": "health", "page": "runs", "search": "?show=t:health&show=t:state",
         "default": True},
        {"name": "by kind", "page": "job", "search": "?group=tags.kind", "default": False},
        {"name": "health", "page": "jobs", "search": "", "default": False},
    ]


def test_no_views_is_no_entries():
    assert views_entries({}) == []
    assert views_entries(None) == []
    assert views_entries({"views": []}) == []


def _view(name="v", page="runs", **kw):
    return {"name": name, "page": page, "search": "?sort=loss", **kw}


@pytest.mark.parametrize("views, words", [
    ("health", "list"),
    (["health"], r"ui\.views\[0\]"),
    ([{"page": "runs", "search": ""}], "name"),
    ([{"name": "v", "search": ""}], "page"),
    ([{"name": "v", "page": "runs"}], "search"),
    ([_view(name="")], "name"),
    ([_view(name="  ")], "name"),
    ([_view(name=3)], "name"),
    ([_view(page="run")], "page"),
    ([_view(search=["?a=1"])], "search"),
    ([_view(default="yes")], "default"),
    ([_view(columns=["t:health"])], "columns"),
    ([_view(), _view()], "twice"),
    ([_view(name="a", default=True), _view(name="b", default=True)], "default"),
    ([_view(name=f"v{i}") for i in range(MAX_VIEWS + 1)], "at most 20"),
])
def test_invalid_views_are_refused_naming_the_entry(views, words):
    with pytest.raises(SettingsError, match=words):
        parse_settings(yaml.safe_dump({"ui": {"views": views}}))


def test_one_default_per_page_and_a_name_per_page():
    views = [_view(name="a", default=True), _view(name="a", page="jobs", default=True),
             _view(name="b", page="job", default=True)]
    settings = parse_settings(yaml.safe_dump({"ui": {"views": views}}))
    assert [v["default"] for v in views_entries(settings["ui"])] == [True, True, True]


def test_twenty_views_are_allowed():
    views = [_view(name=f"v{i}") for i in range(MAX_VIEWS)]
    settings = parse_settings(yaml.safe_dump({"ui": {"views": views}}))
    assert len(views_entries(settings["ui"])) == MAX_VIEWS


def test_a_conf_with_bad_views_reads_as_none():
    assert views_entries({"views": [_view(), _view()]}) == []
    assert views_entries({"views": "nope"}) == []
