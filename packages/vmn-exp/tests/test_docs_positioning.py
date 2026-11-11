"""The vmn-exp docs state the architecture rule, not the old absolute "no
server, no database" headline: a team server with a cache exists, it is just
never required (plan 43 F1)."""
import glob
import os
import re

from exp_helpers import _PROJECT_ROOT

DOCS_INDEX = "docs/vmn-exp/README.md"
STORAGE_RULE = "storage is the source of truth; training never depends on a server"
ABSOLUTE_CLAIMS = (
    r"no server, no database",
    r"there is no server and no database",
)


def absolute_claims(text):
    flat = re.sub(r"\s+", " ", text).lower()
    return [claim for claim in ABSOLUTE_CLAIMS if re.search(claim, flat)]


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


def test_no_vmn_exp_doc_makes_the_absolute_claim():
    docs = glob.glob(os.path.join(_PROJECT_ROOT, "docs/vmn-exp/*.md"))
    offenders = {
        os.path.relpath(path, _PROJECT_ROOT): claims
        for path in sorted(docs)
        if (claims := absolute_claims(_read(os.path.relpath(path, _PROJECT_ROOT))))
    }
    assert offenders == {}


def test_the_docs_index_links_server_md_beside_the_storage_rule():
    paragraph = _paragraph_with(_read(DOCS_INDEX), STORAGE_RULE)
    assert STORAGE_RULE in paragraph.lower()
    assert "(server.md)" in paragraph
