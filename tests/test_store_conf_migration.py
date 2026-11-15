"""Conf ``experiment.storage`` -> top-level ``store`` (plan 45 P4c).

Loading only flags the legacy section (the store resolver reads both);
``vmn stamp`` rewrites the conf file text, keeping comments and key order.
"""
import yaml
from version_stamp.compat.store_conf import has_legacy_storage, move_storage_lines
from version_stamp.core.models import VMN_DEFAULT_CONF, AppConf


def _moved(text):
    return "".join(move_storage_lines(text.splitlines(keepends=True)))


# ── AppConf ──────────────────────────────────────────────────────────


def test_app_conf_has_a_store_field_next_to_experiment():
    names = list(AppConf.conf_key_to_attr())
    assert names[names.index("experiment") + 1] == "store"
    assert VMN_DEFAULT_CONF["store"] == {}


def test_the_config_tui_describes_store_as_a_nested_dict():
    desc = AppConf.config_descriptions()["store"]
    assert desc["type"] == "nested_dict"
    assert desc["nested_key"] == "store"
    assert "uri" in desc["description"]


# ── has_legacy_storage ───────────────────────────────────────────────


def test_legacy_storage_without_store_needs_the_move():
    assert has_legacy_storage({"experiment": {"storage": {"uri": "s3://b/p"}}})


def test_an_empty_store_does_not_block_the_move():
    conf = {"store": {}, "experiment": {"storage": {"uri": "s3://b/p"}}}
    assert has_legacy_storage(conf)


def test_a_set_store_keeps_the_legacy_section_alone():
    conf = {"store": {"uri": "s3://new"}, "experiment": {"storage": {"uri": "s3://b"}}}
    assert not has_legacy_storage(conf)


def test_no_legacy_storage_needs_nothing():
    assert not has_legacy_storage({})
    assert not has_legacy_storage({"experiment": None})
    assert not has_legacy_storage({"experiment": {"metrics": {}}})
    assert not has_legacy_storage({"experiment": {"storage": {}}})


# ── move_storage_lines ───────────────────────────────────────────────

BLOCK = """\
# top comment
conf:
  template: '[{major}]'
  experiment:
    metrics:
      loss: {type: float}
    # where runs go
    storage:
      uri: s3://b/p  # the bucket
      endpoint_url: http://minio:9000
  extra_info: false
"""


def test_block_storage_moves_to_a_top_level_store():
    assert _moved(BLOCK) == """\
# top comment
conf:
  template: '[{major}]'
  experiment:
    metrics:
      loss: {type: float}
    # where runs go
  store:
    uri: s3://b/p  # the bucket
    endpoint_url: http://minio:9000
  extra_info: false
"""


def test_the_moved_conf_loads_as_the_dict_move():
    data = yaml.safe_load(_moved(BLOCK))["conf"]
    assert data["store"] == {"uri": "s3://b/p", "endpoint_url": "http://minio:9000"}
    assert data["experiment"] == {"metrics": {"loss": {"type": "float"}}}


def test_an_experiment_holding_only_storage_is_dropped():
    text = "conf:\n  experiment:\n    storage:\n      bucket: b\n  template: x\n"
    assert _moved(text) == "conf:\n  store:\n    bucket: b\n  template: x\n"


def test_comments_of_a_dropped_experiment_move_out_with_it():
    text = "conf:\n  experiment:\n    # shared\n    storage:\n      bucket: b\n"
    assert _moved(text) == "conf:\n  # shared\n  store:\n    bucket: b\n"


def test_vmn_exp_only_storage_keys_stay_in_experiment_storage():
    text = (
        "conf:\n  experiment:\n    storage:\n      uri: gs://b/t\n"
        "      writer_id: ci  # w\n      experiment_dir: /runs\n"
    )
    assert _moved(text) == (
        "conf:\n  experiment:\n    storage:\n"
        "      writer_id: ci  # w\n      experiment_dir: /runs\n"
        "  store:\n    uri: gs://b/t\n"
    )


def test_vmn_exp_only_storage_keys_stay_in_flow_storage():
    text = "conf:\n  experiment:\n    storage: {bucket: b, writer_id: ci}\n"
    assert _moved(text) == (
        "conf:\n  experiment:\n    storage: {writer_id: ci}\n  store: {bucket: b}\n"
    )


def test_a_storage_without_store_keys_is_unchanged():
    text = "conf:\n  experiment:\n    storage:\n      writer_id: ci\n"
    assert not has_legacy_storage({"experiment": {"storage": {"writer_id": "ci"}}})
    assert _moved(text) == text


def test_flow_storage_in_a_block_experiment():
    text = "conf:\n  experiment:\n    metrics: {}\n    storage: {uri: 's3://b/p'}  # s\n"
    assert _moved(text) == (
        "conf:\n  experiment:\n    metrics: {}\n  store: {uri: 's3://b/p'}  # s\n"
    )


def test_flow_experiment():
    text = "conf:\n  experiment: {metrics: {}, storage: {bucket: b}}  # e\n"
    assert _moved(text) == (
        "conf:\n  experiment: {metrics: {}}  # e\n  store: {bucket: b}\n"
    )


def test_flow_experiment_with_only_storage_is_dropped():
    text = "conf:\n  experiment: {storage: {bucket: b}}\n  template: x\n"
    assert _moved(text) == "conf:\n  store: {bucket: b}\n  template: x\n"


def test_an_empty_store_line_is_replaced():
    text = (
        "conf:\n  experiment:\n    storage:\n      uri: s3://b\n"
        "  store: {}\n  template: x\n"
    )
    assert _moved(text) == "conf:\n  store:\n    uri: s3://b\n  template: x\n"


def test_a_set_store_leaves_the_lines_unchanged():
    text = "conf:\n  experiment:\n    storage: {uri: s3://old}\n  store: {uri: s3://new}\n"
    assert _moved(text) == text


def test_a_conf_without_storage_is_unchanged():
    text = "conf:\n  experiment:\n    metrics: {}\n  template: x\n"
    assert _moved(text) == text
    assert _moved("conf: {}\n") == "conf: {}\n"


# ── wiring into the deprecated-keys path ────────────────────────────


def test_loading_flags_legacy_storage_but_keeps_it_in_memory():
    from version_stamp.compat.config_keys import migrate_config_keys

    conf = {"experiment": {"storage": {"uri": "s3://b/p"}}}
    assert migrate_config_keys(conf, "conf.yml")
    assert conf == {"experiment": {"storage": {"uri": "s3://b/p"}}}


def test_loading_a_conf_without_storage_flags_nothing():
    from version_stamp.compat.config_keys import migrate_config_keys

    assert not migrate_config_keys({"experiment": {"metrics": {}}}, "conf.yml")


def test_rewrite_moves_storage_in_the_file(tmp_path):
    from version_stamp.compat.conf_rewrite import rewrite_deprecated_conf_keys

    path = tmp_path / "conf.yml"
    path.write_text(BLOCK)
    assert rewrite_deprecated_conf_keys(str(path))
    assert path.read_text() == _moved(BLOCK)


def test_rewrite_leaves_a_conf_without_store_untouched(tmp_path):
    from version_stamp.compat.conf_rewrite import rewrite_deprecated_conf_keys

    text = "conf:\n  experiment:\n    metrics: {}\n"
    path = tmp_path / "conf.yml"
    path.write_text(text)
    assert not rewrite_deprecated_conf_keys(str(path))
    assert path.read_text() == text
