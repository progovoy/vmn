"""The metrics step of ``vmn-exp migrate`` (docs/plans/12-columnar-metrics.md §9).

A v1 run logged its metrics as ``{"type": "metrics", ...}`` JSONL entries.
:func:`convert_metrics` takes them out of every ``log/<w>[@seq].jsonl`` and
writes each writer's points as its compacted ``metrics/<w>.vmx``, the file a
finished v2 writer leaves. Rewind markers stay in the log; the points they
hide are dropped from the file, as compaction does.
"""
from vmn_exp.core.logfiles import group_log_names, is_log_file, parse_json_line
from vmn_exp.core.metric_columns import Columns
from vmn_exp.core.metric_entries import is_metric_entry
from vmn_exp.core.metric_files import indexed_name
from vmn_exp.core.metric_index_file import build_index
from vmn_exp.core.metric_stream import inherited_twin, stepless_twin
from vmn_exp.core.metric_time import iso_to_us
from vmn_exp.core.rewind import entry_step
from vmn_exp.core.series_reader import hidden, rewind_markers


def _split_log(text):
    """``(metric entries, the other lines)`` of a JSONL log's *text*."""
    metrics, kept = [], []
    for line in text.splitlines():
        entry = parse_json_line(line)
        if is_metric_entry(entry):
            metrics.append(entry)
        elif line.strip():
            kept.append(line)
    return metrics, kept


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def _points(entries):
    """``(inherited, key, step, ts_us, value)`` of *entries*, in log order."""
    ts_us = 0
    for entry in entries:
        ts_us = iso_to_us(entry.get("timestamp")) or ts_us
        step = entry_step(entry)
        step = None if step is None else int(step)
        for key, value in (entry.get("values") or {}).items():
            value = _number(value)
            if value is not None:
                yield bool(entry.get("inherited")), key, step, ts_us, value


def _stream_name(inherited, key, step, stepped):
    name = stepless_twin(key) if step is None and (inherited, key) in stepped else key
    return inherited_twin(name) if inherited else name


def writer_keys(entries, rewinds=()):
    """``{stream key: Columns}`` of one writer's metric *entries*, less what
    *rewinds* hide."""
    points = [p for p in _points(entries) if not hidden(rewinds, p[3], p[2])]
    stepped = {(p[0], p[1]) for p in points if p[2] is not None}
    by_name = {}
    for inherited, key, step, ts_us, value in points:
        by_name.setdefault(_stream_name(inherited, key, step, stepped), []).append(
            (ts_us, step, value))
    keys = {}
    for name, pts in by_name.items():
        pts.sort(key=lambda p: p[0])
        steps = None if pts[0][1] is None else [p[1] for p in pts]
        keys[name] = Columns(steps, [p[0] for p in pts], [p[2] for p in pts])
    return keys


def convert_metrics(files, read):
    """Move the ``metrics`` entries of every log file into ``metrics/<w>.vmx``
    (log files a compacted one supersedes are dropped)."""
    groups = group_log_names(files)
    visible = {n for names in groups.values() for n in names}
    out = {n: s for n, s in files.items() if not is_log_file(n) or n in visible}
    per_writer, others = {}, []
    for writer, names in sorted(groups.items()):
        for name in names:
            metrics, kept = _split_log(read(files[name]).decode())
            others += [parse_json_line(line) for line in kept]
            if not metrics:
                continue
            per_writer.setdefault(writer, []).extend(metrics)
            if kept:
                out[name] = "".join(line + "\n" for line in kept).encode()
            else:
                del out[name]
    rewinds = rewind_markers([e for e in others if e])
    for writer, entries in per_writer.items():
        keys = writer_keys(entries, rewinds)
        if keys:
            out[indexed_name(writer)] = build_index(writer, keys, rewinds_applied=bool(rewinds))
    return out
