#!/usr/bin/env python3
"""``vmn-exp export-metrics <app> -v <ref>... [--keys k...] [-o out]
[--format parquet|csv]``: runs' metric series as one long table
``(run, writer, key, step, ts, value)`` (plan 12 §8.3).

Parquet needs pyarrow (``pip install "vmn-exp[parquet]"``); CSV needs nothing.
``ts`` is microseconds since the epoch.
"""
import csv
import os

from vmn_exp._base import VMN_LOGGER
from vmn_exp.core.fork import resolve_run
from vmn_exp.core.series_reader import SeriesReader, rewind_markers
from vmn_exp.storage.files import flatten_logs

COLUMNS = ("run", "writer", "key", "step", "ts", "value")
DEFAULT_OUTPUT = "metrics.parquet"
PYARROW_HINT = 'Parquet export needs pyarrow: pip install "vmn-exp[parquet]" (or use --format csv)'


def run_rows(storage, app_name, verstr, keys=None):
    """*verstr*'s rows: stream/index points plus v1 ``metrics`` log entries."""
    logs = storage.load_logs_by_writer(app_name, verstr)
    entries = [e for writer_entries in logs.values() for e in writer_entries or ()]
    reader = SeriesReader.from_storage(storage, app_name, verstr,
                                       rewinds=rewind_markers(entries),
                                       legacy=flatten_logs(logs))
    for row in reader.rows(keys=keys):
        yield (verstr, *row)


def _format(args, output):
    explicit = getattr(args, "metrics_format", None)
    if explicit:
        return explicit
    return "csv" if output.lower().endswith(".csv") else "parquet"


def write_csv(rows, output):
    with open(output, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(COLUMNS)
        writer.writerows(rows)


def write_parquet(rows, output, pa, pq):
    columns = list(zip(*rows)) or [()] * len(COLUMNS)
    types = (pa.string(), pa.string(), pa.string(), pa.int64(), pa.int64(), pa.float64())
    table = pa.table({name: pa.array(list(col), type=t)
                      for name, col, t in zip(COLUMNS, columns, types)})
    pq.write_table(table, output)


def _parquet_modules():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except ImportError:
        return None
    return pa, pq


def experiment_export_metrics(storage, app_name, args):
    refs = getattr(args, "version", None) or []
    if not refs:
        VMN_LOGGER.error("exp export-metrics needs run refs (-v)")
        return 1
    output = getattr(args, "output", None) or DEFAULT_OUTPUT
    fmt = _format(args, output)
    modules = _parquet_modules() if fmt == "parquet" else None
    if fmt == "parquet" and modules is None:
        VMN_LOGGER.error(PYARROW_HINT)
        return 1
    try:
        verstrs = [resolve_run(storage, app_name, ref, "export-metrics") for ref in refs]
    except ValueError as exc:
        VMN_LOGGER.error(str(exc))
        return 1
    keys = getattr(args, "keys", None)
    rows = [row for v in verstrs for row in run_rows(storage, app_name, v, keys)]
    if fmt == "csv":
        write_csv(rows, output)
    else:
        write_parquet(rows, output, *modules)
    print(f"{os.path.abspath(output)} ({len(rows)} rows)")
    return 0
