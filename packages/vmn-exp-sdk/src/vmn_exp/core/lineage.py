#!/usr/bin/env python3
"""Run-to-run lineage: which runs made what a run consumed, and which consumed
what it made.

A run's ``inputs`` (``run.log_input``) and ``outputs`` (its artifacts and
logged images/tables, with their sha256) are already folded by the index —
inputs on every row, outputs beside the lean rows (``outputs_of``) — so
lineage is a join over rows: no log is read. Two kinds of edge:

* **uri** — an input whose URI is ``vmn://<app>/<verstr>/<artifact path>``
  (what ``run.use_artifact`` records) names its producer outright. ``<app>``
  is the tag form (``/`` → ``-``; app names never contain ``-``).
* **digest** — any other input whose digest equals an output's sha256.

A ``vmn-registry://<name>@<N>`` input (a reference dataset, which no run
made) is no edge: it is listed in ``datasets`` instead.

Downstream is searched within the run's own app; upstream follows ``vmn://``
URIs into other apps too.

Pure: no storage, no clock.
"""
from collections import deque

from vmn_exp.registry.names import parse_registry_uri

SCHEME = "vmn://"
DEFAULT_LIMIT = 100


def artifact_ref_uri(app_name, verstr, path):
    """``vmn://<app tag>/<verstr>/<path>`` naming artifact *path* of a run."""
    return f"{SCHEME}{app_name.replace('/', '-')}/{verstr}/{path}"


def parse_artifact_uri(uri):
    """``(app_name, verstr, path)`` of a ``vmn://`` artifact URI, else None."""
    if not isinstance(uri, str) or not uri.startswith(SCHEME):
        return None
    parts = uri[len(SCHEME):].split("/", 2)
    if len(parts) != 3 or not all(parts):
        return None
    app_tag, verstr, path = parts
    return app_tag.replace("-", "/"), verstr, path


def normalize_digest(digest):
    """A digest compared case- and ``sha256:``-prefix-insensitively; None if empty."""
    if not isinstance(digest, str) or not digest.strip():
        return None
    value = digest.strip().lower()
    return value[len("sha256:"):] if value.startswith("sha256:") else value


class LineageIndex:
    """The digest and URI maps of one app's rows. Build once per index snapshot.

    *outputs_of(verstr)* gives a row's outputs when its rows are an index
    snapshot's lean ones (``IndexSnapshot.outputs_of``); else they are read
    off the rows.
    """

    def __init__(self, rows, outputs_of=None):
        self.rows = {}
        self.outputs_of = outputs_of or (lambda verstr: self.rows[verstr].get("outputs") or {})
        self.producers = {}  # digest -> [(verstr, artifact path)]
        self.digest_consumers = {}  # digest -> [(verstr, input name, input)]
        self.uri_consumers = {}  # (app, verstr) -> [(verstr, input name, input, path)]
        for row in rows:
            self._add(row)

    def _add(self, row):
        verstr = row["verstr"]
        self.rows[verstr] = row
        for path, out in self.outputs_of(verstr).items():
            digest = normalize_digest((out or {}).get("digest"))
            if digest:
                self.producers.setdefault(digest, []).append((verstr, path))
        for name, inp in (row.get("inputs") or {}).items():
            inp = inp or {}
            ref = parse_artifact_uri(inp.get("uri"))
            if ref:
                entry = (verstr, name, inp, ref[2])
                self.uri_consumers.setdefault(ref[:2], []).append(entry)
                continue
            digest = normalize_digest(inp.get("digest"))
            if digest and not parse_registry_uri(inp.get("uri")):
                self.digest_consumers.setdefault(digest, []).append((verstr, name, inp))


def _link(name, path, digest, via):
    return {"input": name, "artifact": path, "digest": digest, "via": via}


def _upstream_edges(app_name, row, index):
    """``[((app, verstr), link)]`` of the runs *row* consumed from."""
    edges = []
    for name, inp in sorted((row.get("inputs") or {}).items()):
        inp = inp or {}
        ref = parse_artifact_uri(inp.get("uri"))
        if ref:
            edges.append((ref[:2], _link(name, ref[2], inp.get("digest"), "uri")))
            continue
        if parse_registry_uri(inp.get("uri")):
            continue
        for verstr, path in index.producers.get(normalize_digest(inp.get("digest")), ()):
            edges.append(((app_name, verstr), _link(name, path, inp.get("digest"), "digest")))
    return edges


def _downstream_edges(app_name, row, index):
    """``[((app, verstr), link)]`` of the runs that consumed *row*'s outputs."""
    edges = [
        ((app_name, verstr), _link(name, path, inp.get("digest"), "uri"))
        for verstr, name, inp, path in index.uri_consumers.get((app_name, row["verstr"]), ())
    ]
    for path, out in sorted(index.outputs_of(row["verstr"]).items()):
        digest = normalize_digest((out or {}).get("digest"))
        for verstr, name, inp in index.digest_consumers.get(digest, ()) if digest else ():
            edges.append(((app_name, verstr), _link(name, path, inp.get("digest"), "digest")))
    return edges


def _node(key, row, depth, status_of):
    app_name, verstr = key
    node = {
        "app": app_name,
        "verstr": verstr,
        "name": (row or {}).get("name"),
        "timestamp": (row or {}).get("timestamp"),
        "status": (row or {}).get("status"),
        "depth": depth,
        "found": row is not None,
        "links": [],
    }
    if row is not None and status_of is not None:
        node["status"] = status_of(app_name, verstr)
    return node


def run_node(key, index_for, depth=1, status_of=None):
    """The lineage node of run *key* = ``(app, verstr)``, ``found`` or not."""
    index = index_for(key[0])
    return _node(key, index.rows.get(key[1]) if index else None, depth, status_of)


class _Walk:
    """One direction's breadth-first walk, capped at *limit* nodes."""

    def __init__(self, start, index_for, edges_of, status_of, limit):
        self.start, self.index_for, self.edges_of = start, index_for, edges_of
        self.status_of, self.limit = status_of, limit
        self.nodes, self.truncated = {}, False

    def _row(self, key):
        index = self.index_for(key[0])
        return (index, index.rows.get(key[1])) if index else (None, None)

    def run(self, depth):
        frontier = deque([self.start])
        for level in range(1, depth + 1):
            frontier = deque(self._expand(frontier, level))
            if not frontier:
                break
        return list(self.nodes.values())

    def _expand(self, frontier, level):
        for key in frontier:
            index, row = self._row(key)
            if row is None:
                continue
            for other, link in self.edges_of(key[0], row, index):
                if other == self.start:
                    continue
                node = self.nodes.get(other)
                if node is None:
                    if len(self.nodes) >= self.limit:
                        self.truncated = True
                        continue
                    node = self.nodes[other] = _node(other, self._row(other)[1], level, self.status_of)
                    yield other
                if node["depth"] == level and link not in node["links"]:
                    node["links"].append(link)


def resolve_lineage(
    app_name, verstr, index_for, depth=1, limit=DEFAULT_LIMIT, status_of=None, registry=None
):
    """``{"upstream", "downstream", "datasets", "truncated"}`` of run *verstr*
    of *app_name*.

    *index_for(app)* returns that app's :class:`LineageIndex` (or None).
    Nodes carry ``app``, ``verstr``, ``name``, ``timestamp``, ``status``
    (from *status_of(app, verstr)* when given), ``depth`` (1 = direct),
    ``found`` (False: a ``vmn://`` URI names a run that is not there) and
    ``links`` (``{input, artifact, digest, via}``). Each direction keeps at
    most *limit* nodes. *datasets* lists the run's ``vmn-registry://`` inputs.

    *registry* (``models_of(app, verstr)`` → the live versions registered from
    a run; ``version_live(name, n)``) adds ``model``/``version``/``kind`` to
    each upstream ``uri`` link naming a registered artifact, and each
    dataset's ``found``. Raises KeyError when the run itself is unknown.
    """
    index = index_for(app_name)
    if index is None or verstr not in index.rows:
        raise KeyError(f"Experiment '{verstr}' not found for {app_name}")
    start = (app_name, verstr)
    walks = [
        _Walk(start, index_for, edges, status_of, limit)
        for edges in (_upstream_edges, _downstream_edges)
    ]
    upstream, downstream = (w.run(max(int(depth), 1)) for w in walks)
    if registry is not None:
        annotate_versions(upstream, registry.models_of)
    return {
        "upstream": upstream,
        "downstream": downstream,
        "datasets": registry_inputs(index.rows[verstr], registry),
        "truncated": any(w.truncated for w in walks),
    }


def annotate_versions(nodes, models_of):
    """Give each ``uri`` link of *nodes* the ``model``/``version``/``kind`` of
    the registered version made from its artifact: the one its input is named
    after (``<name>@<N>``, what ``use_model`` records), else the first."""
    for node in nodes:
        uri_links = [link for link in node["links"] if link["via"] == "uri"]
        versions = models_of(node["app"], node["verstr"]) if uri_links else ()
        for link in uri_links:
            match = _version_of(link, versions)
            if match:
                link.update(model=match["model"], version=match["version"], kind=match["kind"])


def _version_of(link, versions):
    made = [v for v in versions if v.get("artifact_path") == link["artifact"]]
    named = [v for v in made if f"{v['model']}@{v['version']}" == link["input"]]
    return (named or made or [None])[0]


def registry_inputs(row, registry=None):
    """``[{model, version, kind, input, digest, found}]`` of *row*'s
    ``vmn-registry://`` inputs; ``found`` is None without a *registry*."""
    datasets = []
    for name, inp in sorted((row.get("inputs") or {}).items()):
        ref = parse_registry_uri((inp or {}).get("uri"))
        if ref is None:
            continue
        datasets.append({
            "model": ref[0],
            "version": ref[1],
            "kind": inp.get("kind") or "dataset",
            "input": name,
            "digest": inp.get("digest"),
            "found": registry.version_live(*ref) if registry is not None else None,
        })
    return datasets
