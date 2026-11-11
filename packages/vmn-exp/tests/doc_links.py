"""Pure checks over markdown text: heading slugs the way GitHub makes them,
relative links whose file or ``#anchor`` is missing, and docs an index does
not link. No markdown parser: fenced blocks and inline code are skipped,
absolute URLs are never followed."""
import posixpath
import re

_LINK = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
_HEADING = re.compile(r"#{1,6} +(.+?)\s*#*\s*$")
_HTML_ANCHOR = re.compile(r"<a\s+(?:id|name)=\"([^\"]+)\"")
_INLINE_CODE = re.compile(r"`[^`]*`")
_ABSOLUTE = re.compile(r"^(?:[a-z][a-z0-9+.-]*:|/)", re.IGNORECASE)


def _unfenced_lines(text):
    """(line number, line) for every line outside a fenced code block."""
    fenced = False
    for number, line in enumerate(text.splitlines(), start=1):
        if line.lstrip().startswith("```"):
            fenced = not fenced
        elif not fenced:
            yield number, line


def _slug(heading):
    heading = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", heading)
    heading = re.sub(r"[^\w\- ]", "", heading.lower().replace("`", ""))
    return heading.replace(" ", "-")


def heading_slugs(text):
    """Every anchor *text* defines: heading slugs (a repeated one gets
    ``-1``, ``-2``, ...) and explicit ``<a id=...>`` anchors."""
    slugs, seen = set(), {}
    for _, line in _unfenced_lines(text):
        slugs.update(_HTML_ANCHOR.findall(line))
        match = _HEADING.match(line)
        if not match:
            continue
        slug = _slug(match.group(1))
        count = seen.get(slug, 0)
        seen[slug] = count + 1
        slugs.add(f"{slug}-{count}" if count else slug)
    return slugs


def _relative_links(text):
    for number, line in _unfenced_lines(text):
        for target in _LINK.findall(_INLINE_CODE.sub("", line)):
            if not _ABSOLUTE.match(target):
                yield number, target


def _is_broken(source, target, read_target):
    path, _, anchor = target.partition("#")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(source), path)) if path else source
    text = read_target(resolved)
    if text is None:
        return True
    return bool(anchor) and resolved.endswith(".md") and anchor not in heading_slugs(text)


def broken_links(docs, read_target):
    """(source, line, target) for each relative link in *docs* (path -> text)
    whose file or anchor is missing. *read_target(path)* returns a linked
    file's text, ``""`` for a non-markdown file, ``None`` when it is missing."""
    return [
        (source, number, target)
        for source, text in docs.items()
        for number, target in _relative_links(text)
        if _is_broken(source, target, read_target)
    ]


def unlinked_docs(index_text, filenames):
    """The *filenames* (siblings of the index) that *index_text* never links;
    the index itself, ``README.md``, is left out."""
    linked = {target.partition("#")[0] for _, target in _relative_links(index_text)}
    return [name for name in sorted(filenames) if name != "README.md" and name not in linked]
