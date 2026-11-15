"""The tables of docs/vmn-exp/upgrading.md as plain rows, and the checks the
release rules of plan 43 F9 make on them. Pure functions over text and
values: the tests read the file and import the code's constants."""

_TABLES = {"## Behaviour changes": "behaviour", "## Formats": "formats"}
_EMPTY = {"", "-", "—"}
_FORMAT_COLUMNS = {"layout": "Store layout", "record_format": "Record format",
                   "records": "Index records", "derived": "Index derived"}


def parse_tables(text):
    """``{"behaviour"|"formats": [row, ...]}``, each row a dict
    keyed by its table's header cells: the first table under each heading."""
    tables, name = {}, None
    for line in text.splitlines():
        if line.startswith("#"):
            name = _TABLES.get(line.strip())
        elif name and line.startswith("|"):
            tables.setdefault(name, []).append(_cells(line))
        elif name in tables:
            name = None
    return {key: _rows(lines) for key, lines in tables.items()}


def _cells(line):
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _rows(lines):
    header, body = lines[0], lines[2:]
    return [dict(zip(header, cells)) for cells in body]


def _is_empty(cell):
    return cell.strip() in _EMPTY


def _version(cell):
    return tuple(int(part) for part in cell.strip().split("."))


def format_table_problems(rows, constants):
    """What is wrong with the Formats *rows* (newest first) against the code's
    *constants* (``layout``, ``record_format``, ``records``, ``derived``)."""
    problems = [
        f"newest Formats row has {key} {rows[0][column]}, the code {constants[key]}"
        for key, column in _FORMAT_COLUMNS.items()
        if rows and rows[0][column] != str(constants[key])
    ]
    for row, below in zip(rows, rows[1:]):
        if _needs_notice(row, below):
            problems += _notice_problems(row)
    return problems


def _needs_notice(row, below):
    return (row["Upgrade"].strip() == "reload"
            or row["Store layout"] != below["Store layout"]
            or row["Record format"] != below["Record format"])


def _notice_problems(row):
    version, announced = row["Version"], row["Announced in"]
    problems = []
    if _is_empty(row["Cost and operator steps"]):
        problems.append(f"{version}: a reload or format change names no cost")
    if _is_empty(announced) or _version(announced) >= _version(version):
        problems.append(f"{version}: not announced in an earlier release")
    return problems

