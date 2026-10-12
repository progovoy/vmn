"""``similar_search.find`` — what ``vmn-exp similar``, ``similar_runs`` and
``run.similar()`` share — takes a ready *target* in place of run *ref* (the
CLI's working tree) and lets archived runs be candidates with
*include_archived*; ``conf_schema_of(root)`` reads each app's conf schema."""
import os

import pytest
import yaml
from similar_seed import TRAIN_STEP, features, seed, verstr
from vmn_exp.core.similar_search import conf_schema_of, find
from vmn_exp.snapshot import open_storage

APP = "trainer"
CHANGES = features(["train.py"], [TRAIN_STEP])


@pytest.fixture
def storage(tmp_path):
    return open_storage(root=str(tmp_path / "store"), area="runs")


def _verstrs(items):
    return [item["verstr"] for item in items]


def test_a_given_target_replaces_the_runs(storage):
    seed(storage, APP, verstr(1), changes=features(["data.py"]))
    like = seed(storage, APP, verstr(2), changes=CHANGES, ts="2026-01-02T00:00:00Z")
    target = {"row": {"code_verstr": verstr(9)}, "features": dict(CHANGES), "text_only": False}

    assert _verstrs(find(storage, APP, None, {}, target=target)) == [like, verstr(1)]


def test_archived_runs_are_candidates_only_when_included(storage):
    target = seed(storage, APP, verstr(1), changes=CHANGES)
    archived = seed(storage, APP, verstr(2), changes=CHANGES, archived=True)

    assert _verstrs(find(storage, APP, target, {})) == []
    assert _verstrs(find(storage, APP, target, {}, include_archived=True)) == [archived]


def test_conf_schema_of_reads_an_apps_conf_metrics(tmp_path):
    conf_dir = tmp_path / ".vmn" / "other"
    os.makedirs(conf_dir)
    conf = {"conf": {"experiment": {"metrics": {"loss": {"goal": "min"}}}}}
    (conf_dir / "conf.yml").write_text(yaml.safe_dump(conf))

    schema_of = conf_schema_of(str(tmp_path))
    assert schema_of("other") == {"loss": {"goal": "min"}}
    assert schema_of("missing") == {}
