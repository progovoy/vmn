"""The client guide (docs/vmn-exp/client-guide.md) shows a first run before it
explains concepts, its table of contents follows its sections, and its Terms
table links each piece of jargon to the section that defines it (plan 38 A8)."""
import os
import re

from doc_links import heading_slugs
from exp_helpers import _PROJECT_ROOT

GUIDE = "docs/vmn-exp/client-guide.md"
QUICKSTART = "docs/vmn-exp/README.md"
GLOSSARY_TERMS = ("verstr", "ref", "outer", "inner", "single", "store",
                  "writer id", "git mode", "git-free", "tree_status")

_SECTION = re.compile(r"^## (.+)$", re.M)
_TOC_ENTRY = re.compile(r"^- \[([^\]]+)\]\(#([^)]+)\)$", re.M)
_LINK = re.compile(r"\]\(((?:experiments|sdk)\.md)#([^)]+)\)")
_PYTHON = re.compile(r"^```python\n(.*?)^```$", re.M | re.S)


def _read(relpath):
    with open(os.path.join(_PROJECT_ROOT, relpath), encoding="utf-8") as f:
        return f.read()


def _sections(text):
    return _SECTION.findall(text)


def _section_body(text, heading):
    return text.split(f"\n## {heading}\n", 1)[1].split("\n## ", 1)[0]


def _glossary_rows(text):
    body = _section_body(text, "Terms")
    return [line for line in body.splitlines()
            if line.startswith("| ") and not line.startswith("| Term")]


def test_first_run_section_comes_before_the_five_ideas():
    sections = _sections(_read(GUIDE))
    order = ["1. Install", "Your first run", "The five ideas you need",
             "2. Choose where runs live"]
    assert [s for s in sections if s in order] == order


def test_the_first_run_shows_the_quickstarts_train_py():
    first_run = _section_body(_read(GUIDE), "Your first run")
    assert "(README.md#quickstart)" in first_run
    assert _PYTHON.findall(first_run) == _PYTHON.findall(_read(QUICKSTART))[:1]
    assert "vmn-exp show my_app --latest" in first_run


def test_every_glossary_term_links_to_an_existing_anchor():
    rows = _glossary_rows(_read(GUIDE))
    for term in GLOSSARY_TERMS:
        assert any(term in row.split("|")[1] for row in rows), term
    for row in rows:
        links = _LINK.findall(row)
        assert links, row
        for target, anchor in links:
            assert anchor in heading_slugs(_read(f"docs/vmn-exp/{target}")), row


def test_table_of_contents_matches_the_section_headings():
    text = _read(GUIDE)
    toc = _TOC_ENTRY.findall(text.split("\n---\n", 1)[0])
    sections = _sections(text)
    assert [title for title, _ in toc] == sections
    assert [{anchor} for _, anchor in toc] == [heading_slugs(f"## {s}") for s in sections]
