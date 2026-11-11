"""How ``vmn-exp list`` lays its rows out (plan 39 B3)."""


def list_layout(rows):
    """``(indent, parent_label)`` per row. In storage order (ascending
    ``idx``) a row indents by its tree depth. In any other order indentation
    would say nothing, so rows are flat and a child names its parent:
    ``^[N]`` when the parent is listed, else ``^<parent verstr>``."""
    idxs = [row["idx"] for row in rows]
    if idxs == sorted(idxs):
        return [(row["meta"]["depth"], "") for row in rows]
    listed = {row["meta"]["verstr"]: row["idx"] for row in rows}
    return [(0, _parent_label(row["meta"].get("parent"), listed)) for row in rows]


def _parent_label(parent, listed):
    if not parent:
        return ""
    return f"^[{listed[parent]}]" if parent in listed else f"^{parent}"
