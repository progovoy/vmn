"""Argument-order traps of the SDK: a swapped ``log_*`` call fails with a
TypeError that names the order, and ``get_metric_history`` takes ``app_name``
and ``ref`` only by keyword. Fakes only: no store, no git, no pandas."""
import inspect

import pytest

from vmn_exp.sdk.reader import get_metric_history
from vmn_exp.sdk.run_artifacts import RunArtifacts
from vmn_exp.sdk.run_media import RunMedia


class _FakeArtifacts(RunArtifacts):
    def __init__(self):
        self.produced = []

    def _log_produced(self, name, produce):
        self.produced.append(name)


class _FakeMedia(RunMedia):
    def __init__(self):
        self.stored = []
        self.appended = []

    def _store(self, kind, name, step, path, produce, **fields):
        self.stored.append((kind, name, step))

    def _append(self, entry):
        self.appended.append(entry)


def _assert_swapped(excinfo, call):
    message = str(excinfo.value)
    assert message.startswith(call)
    assert "swapped" in message


def test_log_dict_with_name_first_raises_type_error_naming_the_order():
    run = _FakeArtifacts()
    with pytest.raises(TypeError) as excinfo:
        run.log_dict("cfg.json", {"lr": 0.1})
    _assert_swapped(excinfo, "log_dict(obj, name)")
    assert "got dict" in str(excinfo.value)
    assert run.produced == []


def test_log_figure_with_name_first_raises():
    run = _FakeArtifacts()
    with pytest.raises(TypeError) as excinfo:
        run.log_figure("plot.png", object())
    _assert_swapped(excinfo, "log_figure(figure, name)")
    assert run.produced == []


def test_log_text_with_a_non_string_text_raises():
    run = _FakeArtifacts()
    with pytest.raises(TypeError) as excinfo:
        run.log_text(["line"], "notes.txt")
    _assert_swapped(excinfo, "log_text(text, name)")
    assert run.produced == []


def test_log_table_with_data_first_raises_before_anything_is_stored():
    run = _FakeMedia()
    with pytest.raises(TypeError) as excinfo:
        run.log_table([{"a": 1}], "scores")
    _assert_swapped(excinfo, "log_table(name, data)")
    assert run.stored == []


def test_log_image_with_image_first_raises():
    run = _FakeMedia()
    with pytest.raises(TypeError) as excinfo:
        run.log_image(b"\x89PNG", "sample")
    _assert_swapped(excinfo, "log_image(name, image)")
    assert run.stored == []


def test_log_histogram_with_values_first_raises():
    run = _FakeMedia()
    with pytest.raises(TypeError) as excinfo:
        run.log_histogram([1.0, 2.0], "weights")
    _assert_swapped(excinfo, "log_histogram(name, values)")
    assert run.appended == []


def test_get_metric_history_positional_app_name_raises_type_error():
    with pytest.raises(TypeError):
        get_metric_history("loss", "my_app", "@3")


def test_get_metric_history_takes_app_name_and_ref_by_keyword_only():
    params = inspect.signature(get_metric_history).parameters
    assert params["app_name"].kind is inspect.Parameter.KEYWORD_ONLY
    assert params["ref"].kind is inspect.Parameter.KEYWORD_ONLY


def test_correct_orders_still_reach_the_store():
    artifacts = _FakeArtifacts()
    artifacts.log_dict({"lr": 0.1}, "cfg.json")
    artifacts.log_text("hello", "notes.txt")
    artifacts.log_figure(object(), "plot.png")
    assert artifacts.produced == ["cfg.json", "notes.txt", "plot.png"]

    media = _FakeMedia()
    media.log_table("scores", [{"a": 1}])
    media.log_image("sample", b"\x89PNG")
    media.log_histogram("weights", [1.0, 2.0])
    assert [(kind, name) for kind, name, _ in media.stored] == [
        ("table", "scores"), ("image", "sample"),
    ]
    assert [e["name"] for e in media.appended] == ["weights"]
