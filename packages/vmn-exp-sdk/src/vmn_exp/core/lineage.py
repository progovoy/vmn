#!/usr/bin/env python3
"""Run-to-run lineage: which runs made what a run consumed, and which consumed
what it made.

A run's ``inputs`` (``run.log_input``) and ``outputs`` (its artifacts and
logged images/tables, with their sha256) are already folded by the index —
inputs on every row, outputs beside the lean rows (``outputs_of``) — so
lineage is a join over rows: no log is read. Two kinds of edge:

* **uri** — an input whose URI is ``vmn://<app>/<verstr>/<path>`` (what
  ``run.use_artifact`` records) names its producer outright. ``<path>`` is
  record-relative and explicit: ``artifacts/…`` for a user artifact,
  ``outputs/…`` for vmn's own (``output.log``, media, tables) — the same
  paths ``outputs`` rows are keyed by. ``<app>`` is the tag form (``/`` →
  ``-``; app names never contain ``-``).
* **digest** — any other input whose digest equals an output's sha256.

A ``vmn-registry://<name>@<N>`` input (a reference dataset, which no run
made) is no edge: it is listed in ``datasets`` instead.

Downstream is searched within the run's own app; upstream follows ``vmn://``
URIs into other apps too.

A digest shared by thousands of runs (a dataset every trial of a sweep
consumes) still links them all, but a walk keeps its first *limit* runs in
row order and says ``truncated``: its cost is the limit, never the fan-out.

Pure: no storage, no clock.
"""
from vmn_exp.core.lineage_index import (  # noqa: F401 (re-exported)
    LineageIndex,
    artifact_ref_uri,
    normalize_digest,
    parse_artifact_uri,
)
from vmn_exp.registry.names import parse_registry_uri

DEFAULT_LIMIT = 100


def _upstream_groups(app_name, row, index):
    """``(group, context, edges)`` of the runs *row* consumed from; *edges*
    yields ``((app, verstr), link)`` lazily. *group* (None: never repeats)
    and *context* determine the links, see :meth:`_Walk._walked`."""
    for name, inp in sorted((row.get("inputs") or {}).items()):
        inp = inp or {}
        ref = parse_artifact_uri(inp.get("uri"))
        if ref:
            yield None, None, [(ref[:2], (name, ref[2], inp.get("digest"), "uri"))]
        elif not parse_registry_uri(inp.get("uri")):
            digest = normalize_digest(inp.get("digest"))
            producers = index.producers.get(digest, ())
            yield ("producers", digest), (name, inp.get("digest")), (
                ((app_name, verstr), (name, path, inp.get("digest"), "digest"))
                for verstr, path in producers
            )


def _downstream_groups(app_name, row, index):
    """``(group, context, edges)`` of the runs that consumed *row*'s outputs."""
    yield None, None, (
        ((app_name, verstr), (name, path, digest, "uri"))
        for verstr, name, digest, path in index.uri_consumers.get((app_name, row["verstr"]), ())
    )
    for path, out in sorted(index.outputs_of(row["verstr"]).items()):
        digest = normalize_digest((out or {}).get("digest"))
        consumers = index.digest_consumers.get(digest, ()) if digest else ()
        yield ("consumers", digest), path, (
            ((app_name, verstr), (name, path, logged, "digest"))
            for verstr, name, logged in consumers
        )


def _link(name, path, digest, via):
    return {"input": name, "artifact": path, "digest": digest, "via": via}


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
    """One direction's breadth-first walk, capped at *limit* nodes.

    It costs about its node limit, however many runs share a digest: edges
    are consumed lazily and the walk ends (``truncated``) at the first run
    past the limit, so a dataset 300k trials consumed contributes its first
    *limit* consumers; a digest group walked at an earlier level is not
    walked again (all its runs are nodes by then, at no deeper level)."""

    def __init__(self, start, index_for, edges_of, status_of, limit):
        self.start, self.index_for, self.edges_of = start, index_for, edges_of
        self.status_of, self.limit = status_of, limit
        self.nodes, self.truncated = {}, False
        self._links = {}  # node key -> its links as tuples
        self._groups = {}  # group -> (level first walked, contexts walked at it)

    def _row(self, key):
        index = self.index_for(key[0])
        return (index, index.rows.get(key[1])) if index else (None, None)

    def run(self, depth):
        frontier = [self.start]
        for level in range(1, depth + 1):
            frontier = self._expand(frontier, level)
            if not frontier or self.truncated:
                break
        return list(self.nodes.values())

    def _expand(self, frontier, level):
        """The nodes *frontier* reaches first; stops at the first past the limit."""
        found = []
        for key in frontier:
            index, row = self._row(key)
            if row is None:
                continue
            for group, context, edges in self.edges_of(key[0], row, index):
                if self._walked(group, context, level):
                    continue
                for other, link in edges:
                    if other == self.start:
                        continue
                    if other not in self.nodes:
                        if len(self.nodes) >= self.limit:
                            self.truncated = True
                            return found
                        self._add(other, level)
                        found.append(other)
                    self._attach(other, link, level)
        return found

    def _walked(self, group, context, level):
        """Whether *group*'s edges add nothing new: it was walked at an
        earlier level, or at this one with the same *context* (same links)."""
        if group is None:
            return False
        first, contexts = self._groups.setdefault(group, (level, set()))
        if first < level or context in contexts:
            return True
        contexts.add(context)
        return False

    def _add(self, key, level):
        self.nodes[key] = _node(key, self._row(key)[1], level, self.status_of)
        self._links[key] = set()

    def _attach(self, key, link, level):
        node, seen = self.nodes[key], self._links[key]
        if node["depth"] == level and link not in seen:
            seen.add(link)
            node["links"].append(_link(*link))


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
        for edges in (_upstream_groups, _downstream_groups)
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
