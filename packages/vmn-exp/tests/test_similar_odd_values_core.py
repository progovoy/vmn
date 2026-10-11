"""One run's odd value never breaks similar runs for its app: what the SDK
accepts (``log_input(uri, digest=zlib.crc32(data))``, ``name=2024``) and what
a hand-edited record holds — inputs, params, metrics, tags, commands of other
types — is read per value, kept when it can be compared and skipped when not
(vmn_exp.core.similar_profile)."""
import pytest
from similar_fixtures import FakeSnapshot, changed, run, verstrs
from vmn_exp.core.similar import similar_runs, target_from_snapshot
from vmn_exp.core.similar_profile import build_profile, profile_tokens
from vmn_exp.core.similar_score import score

ODD = [None, 0, 12345, 1.5, True, "", [], [1, "a"], {}, {"a": 1}]
FOCAL = changed(files=["loss.py"], symbols=["loss.py::focal_loss"])


def _input(name="imagenet@3", digest="sha256:1", kind="dataset"):
    return {"uri": "vmn-registry://imagenet@3", "digest": digest, "kind": kind, "name": name}


def _search(odd_row):
    """The similar runs of a target, the odd run *odd_row* among the candidates."""
    rows = [run("t", params={"lr": 0.1}, inputs={"imagenet@3": _input()}), odd_row,
            run("u", params={"lr": 0.1}, inputs={"imagenet@3": _input()})]
    snap = FakeSnapshot(rows, features={r["verstr"]: FOCAL for r in rows})
    return similar_runs(snap, target_from_snapshot(snap, "t"))


@pytest.mark.parametrize("digest", ODD)
def test_an_input_digest_of_any_type_never_raises(digest):
    odd = run("o", params={"lr": 0.1}, inputs={"imagenet@3": _input(digest=digest)})
    assert set(verstrs(_search(odd))) == {"o", "u"}


@pytest.mark.parametrize("kind", ODD)
def test_an_input_kind_of_any_type_never_raises(kind):
    odd = run("o", params={"lr": 0.1}, inputs={"imagenet@3": _input(kind=kind)})
    assert set(verstrs(_search(odd))) == {"o", "u"}


def test_an_integer_digest_matches_the_same_integer_digest():
    a = {"row": run("a", inputs={"data": _input(digest=12345)})}
    b = {"row": run("b", inputs={"data": _input(digest=12345)})}
    c = {"row": run("c", inputs={"data": _input(digest=54321)})}
    assert score(a, b)[2]["inputs"] == 1.0
    assert score(a, c)[2]["inputs"] == pytest.approx(0.6)


@pytest.mark.parametrize("name", [2024, 1.5, True, None])
def test_an_input_named_by_no_string_is_skipped(name):
    inputs = {name: _input(name=name), "imagenet@3": _input()}
    profile = build_profile(run("o", inputs=inputs))
    assert [i.name for i in profile.inputs] == ["imagenet@3"]
    odd = run("o", params={"lr": 0.1}, inputs=inputs)
    assert set(verstrs(_search(odd))) == {"o", "u"}


def test_params_and_metrics_keyed_by_no_string_are_skipped():
    odd = run("o", params={1: 0.1, "lr": 0.1, None: "x"},
              metrics={2: 1.0, "val_loss": 0.3, (1, 2): 2.0})
    profile = build_profile(odd)
    assert set(profile.params) == {"lr"} and profile.objective == {"val_loss"}
    assert {"pkey:lr", "metric:val_loss"} <= profile_tokens(profile)
    assert set(verstrs(_search(odd))) == {"o", "u"}


@pytest.mark.parametrize("tags", [{"team": {"a": 1}}, {"team": [1, None]}, {"n": 3}])
def test_tags_of_any_value_type_never_raise(tags):
    assert set(verstrs(_search(run("o", params={"lr": 0.1}, tags=tags)))) == {"o", "u"}


@pytest.mark.parametrize("command", [{"argv": "train.py"}, 7, [1, None, "train.py"], ("x",)])
def test_a_command_of_any_type_never_raises(command):
    assert set(verstrs(_search(run("o", params={"lr": 0.1}, command=command)))) == {"o", "u"}


@pytest.mark.parametrize("entrypoint", ODD)
def test_a_features_entrypoint_of_any_type_never_raises(entrypoint):
    profile = build_profile(run("o"), features={"entrypoint": entrypoint})
    profile_tokens(profile)
    score({"row": run("t"), "command": ["python", "train.py"]}, profile)


@pytest.mark.parametrize("text", [3, ["focal"], {"a": 1}])
def test_a_context_text_of_no_string_reads_as_no_text(text):
    profile = build_profile(run("t"), text=text)
    assert profile.has_intent is False and profile.length == 0
