"""The hand validators the body sweep needed (plan 42 E12a), each without an
app: a wrong-typed field is refused with its name, never passed on."""
from types import SimpleNamespace

import pytest

pytest.importorskip("fastapi")
from fastapi import HTTPException  # noqa: E402

from vmn_exp.registry.names import valid_alias_name, valid_model_name  # noqa: E402
from vmn_exp.ui.auth.device import DeviceFlow, DeviceFlowError  # noqa: E402
from vmn_exp.ui.body_checks import comment_links, workspace_fields  # noqa: E402
from vmn_exp.ui.routes_comments import parse_target  # noqa: E402

WRONG = (7, [1], {"a": 1})


def _refused(check, body):
    with pytest.raises(HTTPException) as caught:
        check(body)
    return caught.value


@pytest.mark.parametrize("name", WRONG)
def test_workspace_name_must_be_a_str(name):
    refused = _refused(workspace_fields, {"name": name, "path": "/p"})

    assert refused.status_code == 422 and "'name'" in refused.detail


@pytest.mark.parametrize("field", ["path", "remote"])
@pytest.mark.parametrize("value", WRONG)
def test_workspace_path_and_remote_must_be_strs(field, value):
    refused = _refused(workspace_fields, {"name": "w", "path": "/p", field: value})

    assert refused.status_code == 422 and f"'{field}'" in refused.detail


def test_workspace_without_remote_needs_a_path():
    refused = _refused(workspace_fields, {"name": "w"})

    assert refused.status_code == 422 and "'path'" in refused.detail


def test_workspace_missing_name_is_422():
    assert _refused(workspace_fields, {"path": "/p"}).status_code == 422


def test_workspace_fields_of_a_clone_and_of_a_path():
    assert workspace_fields({"name": "w", "remote": "https://x/r.git"}) == (
        "w", "https://x/r.git", None)
    assert workspace_fields({"name": "w", "remote": "", "path": "/p"}) == ("w", None, "/p")


@pytest.mark.parametrize("reply_to", [7, [1], {"a": 1}])
def test_comment_reply_to_must_be_a_str(reply_to):
    refused = _refused(comment_links, {"reply_to": reply_to})

    assert refused.status_code == 400 and "reply_to" in refused.detail


@pytest.mark.parametrize("anchor", [7, [1], "a"])
def test_comment_anchor_must_be_an_object(anchor):
    refused = _refused(comment_links, {"anchor": anchor})

    assert refused.status_code == 400 and "anchor" in refused.detail


def test_comment_links_pass_through():
    assert comment_links({}) == (None, None)
    assert comment_links({"reply_to": "c1", "anchor": {"panel": "p"}}) == ("c1", {"panel": "p"})


@pytest.mark.parametrize("target", WRONG)
def test_comment_target_must_be_a_str(target):
    assert _refused(parse_target, target).status_code == 400


@pytest.mark.parametrize("name", WRONG + (None,))
def test_alias_and_model_names_must_be_strs(name):
    assert valid_alias_name(name) is False
    assert valid_model_name(name) is False


@pytest.mark.parametrize("device_code", WRONG)
def test_device_code_must_be_a_str(device_code):
    flow = DeviceFlow(SimpleNamespace(store=None, clock=None))

    with pytest.raises(DeviceFlowError) as caught:
        flow.poll(device_code)

    assert caught.value.code == "invalid_request"
