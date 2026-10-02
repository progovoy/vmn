"""Per-record converters of ``vmn-exp migrate`` (docs/plans/14-store-layout.md §4).

A record's files are ``{v2 name: source}``, a source being the v1 file name
(copied or moved as is) or the new bytes. Each converter maps that dict to the
next one; ``read(source)`` returns a source's bytes. Plan 12's metrics
conversion is one more entry of :data:`RECORD_CONVERTERS`.
"""
import json

import yaml

from vmn_exp.core.logfiles import LEGACY_LOG_FILE, LOG_DIR, is_log_file

LEGACY_WRITER = "v1"
_OUTPUT_MOVES = {"artifacts/output.log": "outputs/output.log",
                 "artifacts/media/": "outputs/media/",
                 "artifacts/tables/": "outputs/tables/"}
_MEDIA_TYPES = ("image", "table")


def move_logs(files, read):
    """``log.<w>[@seq].jsonl`` -> ``log/<w>[@seq].jsonl``."""
    def renamed(name):
        if name.startswith("log.") and name.endswith(".jsonl") and "/" not in name:
            return f"{LOG_DIR}/{name[4:]}"
        return name

    return {renamed(n): s for n, s in files.items()}


def convert_legacy_log(files, read):
    """``log.yml`` (a YAML list) -> ``log/v1.jsonl``."""
    if LEGACY_LOG_FILE not in files:
        return files
    files = dict(files)
    entries = yaml.safe_load(read(files.pop(LEGACY_LOG_FILE))) or []
    lines = "".join(json.dumps(e, default=str) + "\n" for e in entries if isinstance(e, dict))
    files[f"{LOG_DIR}/{LEGACY_WRITER}.jsonl"] = lines.encode()
    return files


def move_outputs(files, read):
    """vmn's own outputs leave ``artifacts/`` for ``outputs/``."""
    def renamed(name):
        for old, new in _OUTPUT_MOVES.items():
            if name == old or (old.endswith("/") and name.startswith(old)):
                return new + name[len(old):]
        return name

    return {renamed(n): s for n, s in files.items()}


def _fixed_line(line):
    try:
        entry = json.loads(line)
    except ValueError:
        return line
    if not isinstance(entry, dict) or entry.get("type") not in _MEDIA_TYPES:
        return line
    path = entry.get("path")
    if not (isinstance(path, str) and path.startswith(("media/", "tables/"))):
        return line
    entry["path"] = "outputs/" + path
    return json.dumps(entry)


def fix_media_paths(files, read):
    """Image/table log entries point at their file's ``outputs/`` path."""
    out = dict(files)
    for name, source in files.items():
        if not is_log_file(name):
            continue
        text = read(source).decode()
        fixed = "".join(_fixed_line(l.rstrip("\n")) + "\n" for l in text.splitlines())
        if fixed != text:
            out[name] = fixed.encode()
    return out


RECORD_CONVERTERS = [move_logs, convert_legacy_log, move_outputs, fix_media_paths]


def convert_record(names, read):
    """``{v2 name: source}`` of a record whose v1 files are *names*."""
    files = {n: n for n in names}
    for converter in RECORD_CONVERTERS:
        files = converter(files, read)
    return files
