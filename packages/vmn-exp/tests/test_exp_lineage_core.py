"""Run-to-run lineage, pure parts: row outputs, the query over them, the
``vmn://`` artifact URI and upstream/downstream resolution over index rows."""
import pytest

from vmn_exp.core.fold import fold_log, fold_row
from vmn_exp.core.lineage import (
    LineageIndex,
    artifact_ref_uri,
    normalize_digest,
    parse_artifact_uri,
    resolve_lineage,
)
from vmn_exp.core.query import compile_query

HEX_A = "a" * 64
HEX_B = "b" * 64
HEX_C = "c" * 64


def _artifact(path, sha, size=10, ts="2026-01-01T00:00:00Z"):
    return {"type": "artifact", "timestamp": ts, "path": path, "sha256": sha, "size": size}


def _input(name, uri, digest=None, ts="2026-01-01T00:00:00Z"):
    return {"type": "input", "ts": ts, "name": name, "uri": uri, "digest": digest, "kind": None}


def _row(verstr, log=(), idx=1):
    meta = {"verstr": verstr, "timestamp": f"2026-01-01T00:00:0{idx}Z"}
    return fold_row(idx, meta, fold_log(list(log)))


# ---------------------------------------------------------------------------
# row["outputs"]
# ---------------------------------------------------------------------------


def test_row_outputs_from_artifact_entries():
    row = _row("r1", [_artifact("model.pkl", HEX_A, 42), _artifact("eval/report.json", HEX_B, 7)])
    assert row["outputs"] == {
        "model.pkl": {"path": "model.pkl", "digest": f"sha256:{HEX_A}", "size": 42},
        "eval/report.json": {
            "path": "eval/report.json", "digest": f"sha256:{HEX_B}", "size": 7,
        },
    }


def test_row_outputs_latest_upload_of_a_path_wins():
    row = _row("r1", [_artifact("m.pkl", HEX_A, 1), _artifact("m.pkl", HEX_B, 2, ts="2026-01-02T00:00:00Z")])
    assert row["outputs"]["m.pkl"]["digest"] == f"sha256:{HEX_B}"


def test_row_without_artifacts_has_empty_outputs():
    assert _row("r1")["outputs"] == {}


def test_query_outputs_digest_unquoted_and_quoted():
    row = dict(_row("r1", [_artifact("model", HEX_A), _artifact("model.pkl", HEX_B)]), status="succeeded")
    assert compile_query(f'outputs.model.digest = "sha256:{HEX_A}"')(row)
    assert compile_query(f'outputs."model.pkl".digest = "sha256:{HEX_B}"')(row)
    assert compile_query('outputs."model.pkl".size > 5')(row)
    assert not compile_query('outputs.missing.digest != null')(row)


def test_query_outputs_rejects_unknown_subfield():
    from vmn_exp.core.query import QueryError

    with pytest.raises(QueryError):
        compile_query('outputs.model.color = "red"')


def test_query_inputs_quoted_name_with_subfield():
    row = _row("r1", [_input("train.v2", "s3://b/t.csv", "sha256:x")])
    assert compile_query('inputs."train.v2".digest = "sha256:x"')(row)


# ---------------------------------------------------------------------------
# vmn:// URIs and digests
# ---------------------------------------------------------------------------


def test_artifact_uri_round_trips_root_apps_and_nested_paths():
    uri = artifact_ref_uri("root/svc", "0.0.1-dev.abc.def", "ckpt/model.pt")
    assert uri == "vmn://root-svc/0.0.1-dev.abc.def/ckpt/model.pt"
    assert parse_artifact_uri(uri) == ("root/svc", "0.0.1-dev.abc.def", "ckpt/model.pt")


@pytest.mark.parametrize("uri", ["s3://b/k", "vmn://app", "vmn://app/v", "vmn://app/v/", None, 3])
def test_parse_artifact_uri_rejects_other_forms(uri):
    assert parse_artifact_uri(uri) is None


def test_normalize_digest():
    assert normalize_digest(f"sha256:{HEX_A.upper()}") == HEX_A
    assert normalize_digest(HEX_A) == HEX_A
    assert normalize_digest("") is None
    assert normalize_digest(None) is None


# ---------------------------------------------------------------------------
# resolution
# ---------------------------------------------------------------------------


def _resolver(apps):
    """``index_for`` over ``{app: [rows]}``."""
    indexes = {app: LineageIndex(rows) for app, rows in apps.items()}
    return indexes.get


def _chain():
    """prep → train → evaluate, linked by digest then by vmn:// URI."""
    prep = _row("prep", [_artifact("data.parquet", HEX_A)], idx=1)
    train = _row("train", [
        _input("data", "file:///tmp/data.parquet", f"sha256:{HEX_A}"),
        _artifact("model.pkl", HEX_B),
    ], idx=2)
    evaluate = _row("eval", [
        _input("model", artifact_ref_uri("app", "train", "model.pkl"), f"sha256:{HEX_B}"),
    ], idx=3)
    other = _row("other", [_artifact("x", HEX_C)], idx=4)
    return {"app": [prep, train, evaluate, other]}


def _verstrs(nodes):
    return [(n["verstr"], n["depth"]) for n in nodes]


def test_upstream_by_digest_and_downstream_by_uri():
    result = resolve_lineage("app", "train", _resolver(_chain()))
    assert _verstrs(result["upstream"]) == [("prep", 1)]
    assert result["upstream"][0]["links"] == [
        {"input": "data", "artifact": "data.parquet", "digest": f"sha256:{HEX_A}", "via": "digest"}
    ]
    assert _verstrs(result["downstream"]) == [("eval", 1)]
    assert result["downstream"][0]["links"] == [
        {"input": "model", "artifact": "model.pkl", "digest": f"sha256:{HEX_B}", "via": "uri"}
    ]
    assert result["truncated"] is False


def test_upstream_by_uri():
    result = resolve_lineage("app", "eval", _resolver(_chain()))
    assert _verstrs(result["upstream"]) == [("train", 1)]
    assert result["upstream"][0]["found"] is True
    assert result["downstream"] == []


def test_depth_walks_further():
    index_for = _resolver(_chain())
    assert _verstrs(resolve_lineage("app", "eval", index_for, depth=1)["upstream"]) == [("train", 1)]
    assert _verstrs(resolve_lineage("app", "eval", index_for, depth=2)["upstream"]) == [
        ("train", 1), ("prep", 2),
    ]
    assert _verstrs(resolve_lineage("app", "prep", index_for, depth=5)["downstream"]) == [
        ("train", 1), ("eval", 2),
    ]


def test_no_match():
    result = resolve_lineage("app", "other", _resolver(_chain()))
    assert result["upstream"] == [] and result["downstream"] == []


def test_uri_input_is_not_matched_by_digest_to_another_producer():
    apps = _chain()
    apps["app"].append(_row("copy", [_artifact("same.pkl", HEX_B)], idx=5))
    result = resolve_lineage("app", "eval", _resolver(apps))
    assert _verstrs(result["upstream"]) == [("train", 1)]


def test_digest_consumers_of_a_duplicated_output():
    apps = _chain()
    apps["app"].append(_row("copy", [_artifact("dup.parquet", HEX_A)], idx=5))
    result = resolve_lineage("app", "train", _resolver(apps))
    assert sorted(_verstrs(result["upstream"])) == [("copy", 1), ("prep", 1)]


def test_a_run_is_never_its_own_neighbour():
    loop = _row("loop", [_input("d", "file:///d", f"sha256:{HEX_A}"), _artifact("d", HEX_A)])
    result = resolve_lineage("app", "loop", _resolver({"app": [loop]}))
    assert result["upstream"] == [] and result["downstream"] == []


def test_cross_app_uri_upstream():
    producer = _row("p1", [_artifact("feat.npz", HEX_C)])
    consumer = _row("c1", [_input("feat", artifact_ref_uri("root/feat", "p1", "feat.npz"), None)])
    result = resolve_lineage(
        "trainer", "c1", _resolver({"trainer": [consumer], "root/feat": [producer]})
    )
    assert [(n["app"], n["verstr"], n["found"]) for n in result["upstream"]] == [
        ("root/feat", "p1", True)
    ]


def test_uri_to_a_missing_run_is_reported_not_found():
    consumer = _row("c1", [_input("m", artifact_ref_uri("app", "gone", "m.pkl"), None)])
    result = resolve_lineage("app", "c1", _resolver({"app": [consumer]}))
    assert [(n["verstr"], n["found"]) for n in result["upstream"]] == [("gone", False)]


def test_limit_truncates():
    producer = _row("p", [_artifact("d", HEX_A)])
    consumers = [_row(f"c{i}", [_input("d", "file:///d", HEX_A)], idx=i + 2) for i in range(5)]
    result = resolve_lineage("app", "p", _resolver({"app": [producer] + consumers}), limit=3)
    assert len(result["downstream"]) == 3
    assert result["truncated"] is True


def test_unknown_run_raises():
    with pytest.raises(KeyError):
        resolve_lineage("app", "nope", _resolver(_chain()))


def test_status_callback_annotates_nodes():
    result = resolve_lineage(
        "app", "train", _resolver(_chain()), status_of=lambda app, v: f"st-{v}"
    )
    assert result["upstream"][0]["status"] == "st-prep"
