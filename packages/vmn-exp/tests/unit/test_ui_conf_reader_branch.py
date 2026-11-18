"""The UI's conf reader reads the conf the app loads on the checkout's
branch (its branch conf when one exists), like vmn and the SDK do."""
import os

from vmn_exp.ui.readers import config as config_reader
from vmn_exp.ui.readers import experiments as exp_reader
from vmn_exp.ui.schema_cache import MetricsSchemaCache

_APP_CONF = "conf:\n  experiment:\n    metrics: {loss: {goal: min}}\n"
_BRANCH_CONF = "conf:\n  experiment:\n    metrics: {acc: {goal: max}}\n"


def _write(path, text):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(text)


def _checkout(tmp_path, branch_conf=True):
    root = str(tmp_path)
    _write(os.path.join(root, ".git", "HEAD"), "ref: refs/heads/feat\n")
    _write(os.path.join(root, ".vmn", "app", "conf.yml"), _APP_CONF)
    if branch_conf:
        _write(os.path.join(root, ".vmn", "app", "branch_conf", "feat", "conf.yml"),
               _BRANCH_CONF)
    return root


def test_read_app_conf_reads_the_branch_conf(tmp_path):
    root = _checkout(tmp_path)
    assert config_reader.read_app_conf(root, "app")["experiment"]["metrics"] == {
        "acc": {"goal": "max"}}


def test_config_payload_shows_the_branch_conf_text(tmp_path):
    root = _checkout(tmp_path)
    payload, err = config_reader.app_conf_payload(root, "app")
    assert err is None
    assert payload["text"] == _BRANCH_CONF


def test_without_a_branch_conf_the_app_conf_is_read(tmp_path):
    root = _checkout(tmp_path, branch_conf=False)
    assert config_reader.read_app_conf(root, "app")["experiment"]["metrics"] == {
        "loss": {"goal": "min"}}


def test_metrics_schema_comes_from_the_branch_conf(tmp_path):
    root = _checkout(tmp_path)
    assert exp_reader.metrics_schema(root, "app") == {"acc": {"goal": "max"}}


def test_schema_cache_follows_an_edit_of_the_branch_conf(tmp_path):
    root = _checkout(tmp_path)
    cache = MetricsSchemaCache()
    assert cache.get(root, "app") == {"acc": {"goal": "max"}}
    _write(os.path.join(root, ".vmn", "app", "branch_conf", "feat", "conf.yml"),
           "conf:\n  experiment:\n    metrics: {f1: {goal: maximize}}\n")
    assert cache.get(root, "app") == {"f1": {"goal": "maximize"}}
