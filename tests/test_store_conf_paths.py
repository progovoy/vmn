"""version_stamp.store.conf_paths: the conf files vmn loads for a branch, in
precedence order, without touching the filesystem — what the experiment SDK
(which reaches vmn only through version_stamp.store) reads to pick the conf
the writer picks."""
import os

from version_stamp.core.utils import (
    branch_conf_canonical_path,
    branch_conf_flat_path,
    branch_conf_legacy_path,
)
from version_stamp.store.conf_paths import branch_conf_candidates


def test_candidates_list_the_layouts_in_precedence_order(tmp_path):
    app_dir = str(tmp_path)
    assert branch_conf_candidates(app_dir, "topic/fix") == [
        branch_conf_canonical_path(app_dir, "topic/fix"),
        branch_conf_flat_path(app_dir, "topic/fix"),
        branch_conf_legacy_path(app_dir, "topic/fix"),
        os.path.join(app_dir, "conf.yml"),
    ]


def test_candidates_of_a_root_app_end_with_root_conf(tmp_path):
    app_dir = str(tmp_path)
    assert branch_conf_candidates(app_dir, "dev", root=True)[-1] == os.path.join(
        app_dir, "root_conf.yml")


def test_without_a_branch_the_only_candidate_is_the_default_conf(tmp_path):
    app_dir = str(tmp_path)
    assert branch_conf_candidates(app_dir, None) == [os.path.join(app_dir, "conf.yml")]
