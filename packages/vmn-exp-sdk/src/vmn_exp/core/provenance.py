"""Provenance helpers: no-code detection, env diff, inputs diff.

Pure functions; no I/O, no storage, no clock.
"""
from vmn_exp.core.code_store import CODE_MISSING


def no_code_reason(meta):
    """Return None if the run has a code snapshot; else a human-readable message.

    The structural gate is ``base_commit`` absence — that is what
    ``_materialize_workdir`` requires.  ``imported_from`` enriches the message
    when present (MLflow imports carry a ``source_commit`` hint). A run whose
    code object is gone or incomplete (see :mod:`vmn_exp.core.code_store`) has
    no usable code either.
    """
    if meta.get(CODE_MISSING):
        return f"code snapshot {meta.get('code')} is missing from the store"
    if meta.get("base_commit"):
        return None
    imported_from = meta.get("imported_from")
    if imported_from:
        tool = imported_from.get("tool") or "unknown"
        run_id = imported_from.get("run_id") or "?"
        source_commit = imported_from.get("source_commit")
        msg = f"imported from {tool} run {run_id}; no code snapshot"
        if source_commit:
            msg += f" — source commit {source_commit}"
        return msg
    return "no code snapshot"


# ---------------------------------------------------------------------------
# env diff
# ---------------------------------------------------------------------------

def _pkg_lines(env_a, env_b):
    """Yield change lines for package differences between two full env dicts."""
    pkgs_a = env_a.get("packages") or {}
    pkgs_b = env_b.get("packages") or {}
    all_keys = sorted(set(pkgs_a) | set(pkgs_b))
    for name in all_keys:
        va = pkgs_a.get(name)
        vb = pkgs_b.get(name)
        if va == vb:
            continue
        if va is None:
            yield f"+ {name} {vb}"
        elif vb is None:
            yield f"- {name} {va}"
        else:
            yield f"{name} {va} -> {vb}"


def _python_lines(env_a, env_b):
    """Yield change lines for python/platform/cuda top-level differences."""
    def _ver(e):
        py = e.get("python") or {}
        return py.get("version") if isinstance(py, dict) else py

    def _plat(e):
        pl = e.get("platform") or {}
        if isinstance(pl, dict):
            sys = pl.get("system") or ""
            mach = pl.get("machine") or ""
            return f"{sys}/{mach}" if sys or mach else None
        return pl or None

    def _cuda(e):
        c = e.get("cuda") or {}
        return c.get("torch_cuda") if isinstance(c, dict) else None

    py_a, py_b = _ver(env_a), _ver(env_b)
    if py_a and py_b and py_a != py_b:
        yield f"python {py_a} -> {py_b}"

    plat_a, plat_b = _plat(env_a), _plat(env_b)
    if plat_a and plat_b and plat_a != plat_b:
        yield f"platform {plat_a} -> {plat_b}"

    cuda_a, cuda_b = _cuda(env_a), _cuda(env_b)
    if cuda_a != cuda_b:
        if cuda_a is not None and cuda_b is not None:
            yield f"cuda {cuda_a} -> {cuda_b}"
        elif cuda_a is not None:
            yield f"- cuda {cuda_a}"
        elif cuda_b is not None:
            yield f"+ cuda {cuda_b}"


def env_diff(env_a, env_b, cap=30):
    """Return a list of diff lines comparing two full env dicts.

    Lines describe python/platform/cuda changes followed by package changes.
    ``hostname`` is intentionally ignored.  When the total number of changes
    exceeds *cap*, only the first *cap* lines are returned and a trailer line
    ``"... N more"`` is appended.

    Each line has one of these forms::

        python 3.10.0 -> 3.11.2
        platform Linux/x86_64 -> Darwin/arm64
        + numpy 1.26.4
        - pandas 2.1.0
        torch 2.2.1 -> 2.3.1
    """
    lines = list(_python_lines(env_a, env_b)) + list(_pkg_lines(env_a, env_b))
    if len(lines) <= cap:
        return lines
    remaining = len(lines) - cap
    return lines[:cap] + [f"... {remaining} more"]


# ---------------------------------------------------------------------------
# inputs diff
# ---------------------------------------------------------------------------

def inputs_diff(inputs_a, inputs_b):
    """Return a list of diff lines comparing two inputs dicts.

    *inputs_a* and *inputs_b* are ``{name: {uri, digest, kind}}`` dicts as
    returned by :func:`~version_stamp.core.experiment_fold.fold_inputs_dict`.

    Each line has one of::

        + added  s3://bucket/new.csv
        - removed  s3://bucket/old.csv
        ~ train  s3://v1.csv -> s3://v2.csv
    """
    lines = []
    all_names = sorted(set(inputs_a) | set(inputs_b))
    for name in all_names:
        ia = inputs_a.get(name)
        ib = inputs_b.get(name)
        if ia == ib:
            continue
        if ia is None:
            uri = (ib or {}).get("uri") or ""
            lines.append(f"+ {name}  {uri}")
        elif ib is None:
            uri = (ia or {}).get("uri") or ""
            lines.append(f"- {name}  {uri}")
        else:
            uri_a = ia.get("uri") or ""
            uri_b = ib.get("uri") or ""
            dig_a = ia.get("digest")
            dig_b = ib.get("digest")
            if uri_a != uri_b:
                lines.append(f"~ {name}  {uri_a} -> {uri_b}")
            elif dig_a != dig_b:
                lines.append(f"~ {name}  digest {dig_a} -> {dig_b}")
    return lines
