"""Shared stamper helpers: release_tag_info and _next_root_state."""
import types
from unittest import mock

import pytest
from version_stamp.stamping import base as stamping_base
from version_stamp.stamping.base import IVersionsStamper


@pytest.fixture(autouse=True)
def _quiet_logger(monkeypatch):
    monkeypatch.setattr(stamping_base, "VMN_LOGGER", mock.Mock())


def _fake(name="root_app/svc", **attrs):
    fake = types.SimpleNamespace(name=name, hide_zero_hotfix=True, **attrs)
    fake.get_tag_name = lambda verstr: IVersionsStamper.get_tag_name(fake, verstr)
    fake._tag_info = lambda tag: IVersionsStamper._tag_info(fake, tag)
    fake.enhance_ver_info = mock.Mock()
    return fake


def test_release_tag_info_looks_up_the_base_version_tag():
    ver_infos = {"root_app-svc_1.2.3": {"ver_info": {"x": 1}}}
    backend = mock.Mock()
    backend.get_tag_version_info.return_value = ("root_app-svc_1.2.3", ver_infos)
    fake = _fake(backend=backend)

    tag, infos = IVersionsStamper.release_tag_info(fake, "1.2.3-rc.4")

    backend.get_tag_version_info.assert_called_once_with("root_app-svc_1.2.3")
    assert (tag, infos) == ("root_app-svc_1.2.3", ver_infos)
    fake.enhance_ver_info.assert_called_once_with(ver_infos)


def test_release_tag_info_hides_zero_hotfix_and_defaults_to_empty():
    backend = mock.Mock()
    backend.get_tag_version_info.return_value = ("app_1.0.0", None)
    fake = _fake(name="app", backend=backend)

    tag, infos = IVersionsStamper.release_tag_info(fake, "1.0.0.0-rc.1")

    backend.get_tag_version_info.assert_called_once_with("app_1.0.0")
    assert (tag, infos) == ("app_1.0.0", {})


def _root_fake(ver_infos, tag="root_app_4"):
    fake = _fake(root_app_name="root_app")
    fake.get_first_reachable_version_info = mock.Mock(return_value=(tag, ver_infos))
    fake.current_version_info = {"stamping": {"app": {"_version": "0.0.2"}}}
    return fake


def _root_ver_infos(version=4, services=None):
    root_app = {"version": version, "services": services or {"root_app/a": "1.0.0"}}
    return {"root_app_4": {"ver_info": {"stamping": {"root_app": root_app}}}}


def test_next_root_state_increments_and_adds_this_service():
    ver_infos = _root_ver_infos()
    fake = _root_fake(ver_infos)

    version, services = IVersionsStamper._next_root_state(fake, "some_type", False)

    fake.get_first_reachable_version_info.assert_called_once_with(
        "root_app", root_context=True, type="some_type"
    )
    assert version == 5
    assert services == {"root_app/a": "1.0.0", "root_app/svc": "0.0.2"}
    # the stored root info is not mutated
    assert ver_infos["root_app_4"]["ver_info"]["stamping"]["root_app"][
        "services"
    ] == {"root_app/a": "1.0.0"}


def test_next_root_state_override_version():
    fake = _root_fake(_root_ver_infos())
    version, _ = IVersionsStamper._next_root_state(
        fake, "t", False, override_version="9"
    )
    assert version == 10


def test_next_root_state_missing_allowed_starts_at_zero():
    fake = _root_fake({}, tag=None)
    version, services = IVersionsStamper._next_root_state(fake, "t", True)
    assert (version, services) == (0, {"root_app/svc": "0.0.2"})


def test_next_root_state_missing_not_allowed_raises():
    fake = _root_fake({}, tag=None)
    with pytest.raises(RuntimeError):
        IVersionsStamper._next_root_state(fake, "t", False)


def test_next_root_state_root_info_without_version_raises():
    ver_infos = {"root_app_4": {"ver_info": {"stamping": {"root_app": {}}}}}
    fake = _root_fake(ver_infos)
    with pytest.raises(RuntimeError):
        IVersionsStamper._next_root_state(fake, "t", False)
