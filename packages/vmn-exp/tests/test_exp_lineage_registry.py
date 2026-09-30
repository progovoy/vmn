"""Run lineage joined with the registry, pure parts: ``vmn://`` links to a
registered version's artifact gain ``model``/``version``/``kind``, and
``vmn-registry://`` inputs (reference datasets) are listed in ``datasets``
rather than as run nodes."""
from vmn_exp.core.fold import fold_log, fold_row
from vmn_exp.core.lineage import LineageIndex, artifact_ref_uri, resolve_lineage
from vmn_exp.registry.names import registry_uri

HEX_A = "a" * 64
HEX_B = "b" * 64
TS = "2026-01-01T00:00:00Z"


def _artifact(path, sha):
    return {"type": "artifact", "timestamp": TS, "path": path, "sha256": sha, "size": 1}


def _input(name, uri, digest=None, kind=None):
    return {"type": "input", "ts": TS, "name": name, "uri": uri, "digest": digest, "kind": kind}


def _row(verstr, log=(), idx=1):
    return fold_row(idx, {"verstr": verstr, "timestamp": TS}, fold_log(list(log)))


def _resolver(apps):
    indexes = {app: LineageIndex(rows) for app, rows in apps.items()}
    return indexes.get


def _version(model, n, artifact_path="model.pkl", kind="model"):
    return {"model": model, "kind": kind, "version": n, "aliases": [],
            "status": "active", "artifact_path": artifact_path}


class FakeRegistry:
    """``models_of(app, verstr)`` / ``version_live(name, n)`` over dicts."""

    def __init__(self, models=None, live=()):
        self.models, self.live = models or {}, set(live)

    def models_of(self, app, verstr):
        return self.models.get((app, verstr), [])

    def version_live(self, name, n):
        return (name, n) in self.live


def _cross_app(input_name):
    producer = _row("p1", [_artifact("model.pkl", HEX_A)])
    uri = artifact_ref_uri("trainer", "p1", "model.pkl")
    consumer = _row("c1", [_input(input_name, uri, f"sha256:{HEX_A}", "model")])
    return _resolver({"trainer": [producer], "serving": [consumer]})


def test_used_model_is_uri_edge_to_producer_run_cross_app():
    result = resolve_lineage("serving", "c1", _cross_app("clf@1"))
    assert [(n["app"], n["verstr"], n["found"]) for n in result["upstream"]] == [
        ("trainer", "p1", True)
    ]
    assert result["upstream"][0]["links"][0]["via"] == "uri"


def test_uri_link_annotated_with_model_version_kind():
    registry = FakeRegistry({("trainer", "p1"): [_version("clf", 1), _version("clf", 2)]})
    result = resolve_lineage("serving", "c1", _cross_app("clf@2"), registry=registry)
    link = result["upstream"][0]["links"][0]
    assert (link["model"], link["version"], link["kind"]) == ("clf", 2, "model")


def test_plain_use_artifact_link_takes_the_first_version_of_that_artifact():
    registry = FakeRegistry({("trainer", "p1"): [_version("clf", 1), _version("clf", 2)]})
    result = resolve_lineage("serving", "c1", _cross_app("model"), registry=registry)
    assert result["upstream"][0]["links"][0]["version"] == 1


def test_uri_link_to_an_unregistered_artifact_is_not_annotated():
    registry = FakeRegistry({("trainer", "p1"): [_version("clf", 1, artifact_path="other")]})
    result = resolve_lineage("serving", "c1", _cross_app("clf@1"), registry=registry)
    assert set(result["upstream"][0]["links"][0]) == {"input", "artifact", "digest", "via"}


def _dataset_apps():
    """A reference-dataset consumer next to a run whose output has the same digest."""
    lookalike = _row("prep", [_artifact("data.csv", HEX_B)], idx=1)
    consumer = _row("train", [
        _input("ds@3", registry_uri("ds", 3), f"sha256:{HEX_B}", "dataset"),
    ], idx=2)
    return _resolver({"app": [lookalike, consumer]})


def test_registry_uri_input_listed_in_datasets_not_as_node():
    index_for = _dataset_apps()
    result = resolve_lineage("app", "train", index_for, registry=FakeRegistry(live=[("ds", 3)]))
    assert result["upstream"] == []
    assert result["datasets"] == [{
        "model": "ds", "version": 3, "kind": "dataset", "input": "ds@3",
        "digest": f"sha256:{HEX_B}", "found": True,
    }]
    assert resolve_lineage("app", "prep", index_for)["downstream"] == []


def test_dataset_of_a_deleted_or_unknown_version_is_not_found():
    result = resolve_lineage("app", "train", _dataset_apps(), registry=FakeRegistry())
    assert result["datasets"][0]["found"] is False


def test_lineage_payload_keys_unchanged_plus_datasets():
    result = resolve_lineage("serving", "c1", _cross_app("clf@1"))
    assert set(result) == {"upstream", "downstream", "truncated", "datasets"}
    assert result["datasets"] == []
