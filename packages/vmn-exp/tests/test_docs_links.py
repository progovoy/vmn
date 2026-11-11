"""Relative links in the vmn-exp docs point at files and headings that exist,
and the docs index links every vmn-exp doc (plan 43 F4)."""
import glob
import os

from doc_links import broken_links, heading_slugs, unlinked_docs
from exp_helpers import _PROJECT_ROOT

DOCS_INDEX = "docs/vmn-exp/README.md"
CHECKED_DOCS = (
    "docs/vmn-exp/*.md",
    "docs/packaging.md",
    "docs/plans/README.md",
    "packages/vmn-exp/README.md",
    "packages/vmn-exp-sdk/README.md",
)


def _read(relpath):
    with open(os.path.join(_PROJECT_ROOT, relpath), encoding="utf-8") as f:
        return f.read()


def _checked_docs():
    relpaths = []
    for pattern in CHECKED_DOCS:
        found = glob.glob(os.path.join(_PROJECT_ROOT, pattern))
        relpaths += [os.path.relpath(p, _PROJECT_ROOT) for p in found]
    return {relpath: _read(relpath) for relpath in sorted(relpaths)}


def _read_target(relpath):
    path = os.path.join(_PROJECT_ROOT, relpath)
    if not os.path.exists(path):
        return None
    return _read(relpath) if relpath.endswith(".md") else ""


def test_slug_matches_github_for_punctuation_and_backticks():
    text = (
        "## Outer & inner jobs (sweeps)\n"
        "### `similar`\n"
        "## Store / layout v2\n"
        "## Runs\n"
        "## Runs\n"
    )
    assert heading_slugs(text) == {
        "outer--inner-jobs-sweeps",
        "similar",
        "store--layout-v2",
        "runs",
        "runs-1",
    }


def test_a_link_to_a_missing_anchor_is_reported():
    docs = {
        "docs/a.md": "# A\n\nsee [b](b.md#nesting) and [ok](b.md#outer)\n",
        "docs/b.md": "# B\n\n## Outer\n",
    }
    assert broken_links(docs, docs.get) == [("docs/a.md", 3, "b.md#nesting")]


def test_a_link_to_a_missing_file_is_reported():
    docs = {"docs/a.md": "[gone](gone.md) [web](https://x.io/y.md) [self](#a)\n# A\n"}
    assert broken_links(docs, docs.get) == [("docs/a.md", 1, "gone.md")]


def test_headings_and_links_inside_code_fences_are_ignored():
    docs = {
        "docs/a.md": "```sh\n# fenced\n[x](missing.md)\n```\n[y](#fenced)\n",
    }
    assert broken_links(docs, docs.get) == [("docs/a.md", 5, "#fenced")]


def test_the_vmn_exp_docs_have_no_broken_relative_links():
    assert broken_links(_checked_docs(), _read_target) == []


def test_a_doc_missing_from_the_index_is_reported():
    index = "- [Guide](guide.md)\n| [api.md](api.md#top) | api |\n"
    names = ["README.md", "api.md", "guide.md", "new.md"]
    assert unlinked_docs(index, names) == ["new.md"]


def test_the_docs_index_links_every_vmn_exp_doc():
    names = [os.path.basename(p) for p in glob.glob(os.path.join(_PROJECT_ROOT, "docs/vmn-exp/*.md"))]
    assert unlinked_docs(_read(DOCS_INDEX), names) == []
