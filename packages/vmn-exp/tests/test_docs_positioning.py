"""The vmn-exp docs state the architecture rule, not the old absolute "no
server, no database" headline: a team server with a cache exists, it is just
never required (plan 43 F1). Scale is stated as measured facts with their
cost, never as a speed promise at a run count, and the MLflow comparison
matches the storage code (plan 43 F2)."""
import glob
import os
import re

from exp_helpers import _PROJECT_ROOT
from vmn_exp.core.record_format import RECORD_FORMAT_VERSION
from vmn_exp.storage.registry import ENTRY_POINT_GROUP, STORAGE_EXTRAS
from vmn_exp.storage.store_marker import LAYOUT

DOCS_INDEX = "docs/vmn-exp/README.md"
STORAGE_RULE = "storage is the source of truth; training never depends on a server"
ABSOLUTE_CLAIMS = (
    r"no server, no database",
    r"there is no server and no database",
)

RUN_COUNT = r"~?[\d.,]+k? runs"
SPEED_PROMISES = (
    rf"stays? fast at {RUN_COUNT}",
    rf"even at {RUN_COUNT}",
    rf"in milliseconds at {RUN_COUNT}",
)
MLFLOW_COMPARISON = "docs/vmn-exp/vmn-vs-mlflow.md"
OBJECT_STORE_PRODUCTS = {"s3": "S3", "gs": "GCS", "az": "Azure"}
PACKAGING = "docs/packaging.md"


def _flat(text):
    return re.sub(r"\s+", " ", text).lower()


def absolute_claims(text):
    flat = _flat(text)
    return [claim for claim in ABSOLUTE_CLAIMS if re.search(claim, flat)]


def scale_promises(text):
    flat = _flat(text)
    return [promise for promise in SPEED_PROMISES if re.search(promise, flat)]


def _read(relpath):
    with open(os.path.join(_PROJECT_ROOT, relpath), encoding="utf-8") as f:
        return f.read()


def _paragraph_with(text, needle):
    flat_paragraphs = (re.sub(r"\s+", " ", p) for p in text.split("\n\n"))
    return next((p for p in flat_paragraphs if needle in p.lower()), "")


def test_absolute_no_server_claims_are_reported():
    assert absolute_claims("Plain files.\nNo server, no\ndatabase.")
    assert absolute_claims("There is no server and no database; storage is files")
    for true_sentence in (
        "No server or database is required to record runs.",
        "Tracking works without a server.",
        "They have no database: they survive a cache drop.",
    ):
        assert absolute_claims(true_sentence) == []


def _vmn_exp_docs_offending(check):
    docs = glob.glob(os.path.join(_PROJECT_ROOT, "docs/vmn-exp/*.md"))
    return {
        os.path.relpath(path, _PROJECT_ROOT): found
        for path in sorted(docs)
        if (found := check(_read(os.path.relpath(path, _PROJECT_ROOT))))
    }


def test_no_vmn_exp_doc_makes_the_absolute_claim():
    assert _vmn_exp_docs_offending(absolute_claims) == {}


def test_the_docs_index_links_server_md_beside_the_storage_rule():
    paragraph = _paragraph_with(_read(DOCS_INDEX), STORAGE_RULE)
    assert STORAGE_RULE in paragraph.lower()
    assert "(server.md)" in paragraph


def test_a_speed_promise_at_a_run_count_is_reported():
    assert scale_promises("the UI stays fast at ~100k runs per app")
    assert scale_promises("the leaderboard answers from memory even at\n100k runs")
    assert scale_promises("keeps dashboard reads in milliseconds at ~100k runs")
    for measured in (
        "Decoding the records is the cost: about a minute per 100k runs.",
        "Watched apps can be large: measured at 100k runs in the load harness.",
    ):
        assert scale_promises(measured) == []


def test_no_vmn_exp_doc_promises_speed_at_a_run_count():
    assert _vmn_exp_docs_offending(scale_promises) == {}


def test_the_mlflow_comparison_names_every_built_in_object_store():
    overview = _paragraph_with(
        _read(MLFLOW_COMPARISON), "approaches tracking from the versioning side"
    )
    missing = [
        OBJECT_STORE_PRODUCTS[scheme]
        for scheme in STORAGE_EXTRAS
        if OBJECT_STORE_PRODUCTS[scheme] not in overview
    ]
    assert missing == []


def test_the_mlflow_comparison_names_the_storage_entry_point_group():
    assert ENTRY_POINT_GROUP in _read(MLFLOW_COMPARISON)


def _section(text, heading):
    start = text.index(f"\n{heading}\n")
    end = text.find("\n## ", start + 1)
    return text[start:] if end < 0 else text[start:end]


def test_packaging_md_compatibility_names_the_current_layout_and_record_format():
    section = _flat(_section(_read(PACKAGING), "## Compatibility"))
    assert f"store layout {LAYOUT}" in section
    assert f"record format {RECORD_FORMAT_VERSION}" in section
