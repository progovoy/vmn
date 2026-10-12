"""Text-level rewrite of deprecated conf keys, run by ``vmn stamp``.

Edits the conf file line by line so comments and key order survive:
- top-level ``default_release_mode: optional|strict`` → ``release_mode_policy``
- ``conventional_commits.default_release_mode`` (block or flow style) → same
- the ``vmn_version_file`` entry of ``version_backends`` is dropped
"""
import re

from version_stamp.core.utils import atomic_write

POLICY_VALUES = ("optional", "strict")
VMN_VERSION_FILE = "vmn_version_file"
_CONF_LINE = re.compile(r"^conf:\s*(#.*)?$")
_KEY_LINE = re.compile(r"^(?P<ind> *)(?P<key>[A-Za-z_]\w*):(?P<rest>.*)$")
_SCALAR = re.compile(r"""^\s*(['"]?)(?P<val>[\w-]+)\1\s*(#.*)?$""")
_BLANK_OR_COMMENT = re.compile(r"^\s*(#.*)?$")
_OPENERS = {"{": "}", "[": "]"}


def rewrite_deprecated_conf_keys(path, dry_run=False):
    """Rewrite the deprecated keys of the conf file at ``path`` in place,
    keeping comments and key order. Returns whether it changes."""
    with open(path) as f:
        lines = f.readlines()
    new_lines = _rewrite_conf_child(
        lines, "conventional_commits", _move_block_policy, _move_flow_policy
    )
    new_lines = _rewrite_top_level_policy(new_lines)
    new_lines = _rewrite_conf_child(
        new_lines, "version_backends", _drop_block_backend, _drop_flow_backend
    )
    new_lines = _keep_conf_a_mapping(lines, new_lines)
    if new_lines == lines:
        return False
    if not dry_run:
        atomic_write(path, "".join(new_lines))
    return True


def _is_content(line):
    return not _BLANK_OR_COMMENT.match(line)


def _indent(line):
    return len(line) - len(line.lstrip(" "))


def _key_line(line):
    return _KEY_LINE.match(line.rstrip("\r\n"))


def _scalar(rest):
    m = _SCALAR.match(rest)
    return m["val"] if m else None


def _direct_keys(lines, start):
    """(index, indent, key, rest) of the keys directly under the line at ``start``."""
    keys = []
    child_ind = None
    for i in range(start + 1, len(lines)):
        if not _is_content(lines[i]):
            continue
        ind = _indent(lines[i])
        if ind <= _indent(lines[start]):
            break
        child_ind = ind if child_ind is None else child_ind
        m = _key_line(lines[i])
        if ind == child_ind and m:
            keys.append((i, ind, m["key"], m["rest"]))
    return keys


def _conf_line(lines):
    for i, line in enumerate(lines):
        if _CONF_LINE.match(line.rstrip()):
            return i
    return None


def _conf_keys(lines):
    i = _conf_line(lines)
    return [] if i is None else _direct_keys(lines, i)


def _block_end(lines, start):
    """Index after the last content line nested under the key at ``start``."""
    end = start + 1
    for j in range(start + 1, len(lines)):
        if not _is_content(lines[j]):
            continue
        if _indent(lines[j]) <= _indent(lines[start]):
            break
        end = j + 1
    return end


def _split_flow(rest):
    """(entries, tail) of a one-line flow mapping ``{a: 1, b: {c: 2}}  # x``,
    or None when ``rest`` is not one."""
    text = rest.strip()
    if not text.startswith("{"):
        return None
    stack, quote, start, entries = [], None, 1, []
    for pos, ch in enumerate(text):
        if quote:
            quote = None if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch in _OPENERS:
            stack.append(_OPENERS[ch])
        elif stack and ch == stack[-1]:
            stack.pop()
            if not stack:
                entries.append(text[start:pos])
                tail = text[pos + 1 :]
                return [e.strip() for e in entries if e.strip()], _tail(tail)
        elif ch == "," and len(stack) == 1:
            entries.append(text[start:pos])
            start = pos + 1
    return None


def _tail(tail):
    return f"  {tail.strip()}" if tail.strip() else ""


def _flow_key(entry):
    return entry.split(":", 1)[0].strip().strip("'\"")


def _flow_value(entry):
    return entry.split(":", 1)[1] if ":" in entry else ""


def _without_flow_key(rest, key):
    """(removed entry or None, remaining entries, tail) of a flow mapping."""
    parsed = _split_flow(rest)
    if parsed is None:
        return None, None, None
    entries, tail = parsed
    removed = next((e for e in entries if _flow_key(e) == key), None)
    return removed, [e for e in entries if e is not removed], tail


def _has_policy(keys):
    return any(key == "release_mode_policy" for _, _, key, _ in keys)


def _policy_line(ind, value, keys):
    """The ``release_mode_policy`` line a moved policy value becomes, unless the
    conf already has one."""
    if value in POLICY_VALUES and not _has_policy(keys):
        return [f"{' ' * ind}release_mode_policy: {value}\n"]
    return []


def _find_direct_key(lines, i, name):
    return next((k for k in _direct_keys(lines, i) if k[2] == name), None)


def _flow_head(ind, key, entries, tail, empty):
    """The line of a flow mapping ``key`` with ``entries``; when none are left,
    ``key: <empty>``, or no line at all when ``empty`` is None."""
    if entries:
        return [f"{' ' * ind}{key}: {{{', '.join(entries)}}}{tail}\n"]
    return [] if empty is None else [f"{' ' * ind}{key}: {empty}{tail}\n"]


def _rewrite_conf_child(lines, key, on_block, on_flow):
    """Apply ``on_block`` or ``on_flow`` (by the entry's style) to the conf's
    ``key`` entry; ``lines`` unchanged without one."""
    keys = _conf_keys(lines)
    for i, ind, name, rest in keys:
        if name == key:
            handler = on_block if _BLANK_OR_COMMENT.match(rest) else on_flow
            return handler(lines, i, ind, rest, keys)
    return lines


def _move_block_policy(lines, i, ind, rest, keys):
    found = _find_direct_key(lines, i, "default_release_mode")
    if found is None:
        return lines
    j, _, _, value_rest = found
    end = _block_end(lines, i)
    block = lines[i + 1 : j] + lines[j + 1 : end]
    head = lines[i]
    if not any(_is_content(line) for line in block):
        head = f"{' ' * ind}conventional_commits: true{rest}\n"
    insert = _policy_line(ind, _scalar(value_rest), keys)
    return lines[:i] + [head] + block + insert + lines[end:]


def _move_flow_policy(lines, i, ind, rest, keys):
    removed, entries, tail = _without_flow_key(rest, "default_release_mode")
    if removed is None:
        return lines
    head = _flow_head(ind, "conventional_commits", entries, tail, empty="true")
    insert = _policy_line(ind, _scalar(_flow_value(removed)), keys)
    return lines[:i] + head + insert + lines[i + 1 :]


def _rewrite_top_level_policy(lines):
    keys = _conf_keys(lines)
    has_policy = _has_policy(keys)
    out = list(lines)
    for i, _, key, rest in keys:
        if key != "default_release_mode" or _scalar(rest) not in POLICY_VALUES:
            continue
        if has_policy:
            out[i] = None
        else:
            out[i] = out[i].replace("default_release_mode", "release_mode_policy", 1)
            has_policy = True
    return [line for line in out if line is not None]


def _drop_block_backend(lines, i, ind, rest, keys):
    found = _find_direct_key(lines, i, VMN_VERSION_FILE)
    if found is None:
        return lines
    j = found[0]
    out = lines[:j] + lines[_block_end(lines, j) :]
    if not _direct_keys(out, i):
        out = out[:i] + out[i + 1 :]
    return out


def _drop_flow_backend(lines, i, ind, rest, keys):
    removed, entries, tail = _without_flow_key(rest, VMN_VERSION_FILE)
    if removed is None:
        return lines
    head = _flow_head(ind, "version_backends", entries, tail, empty=None)
    return lines[:i] + head + lines[i + 1 :]


def _keep_conf_a_mapping(old, new):
    """A conf whose last key was removed becomes ``conf: {}`` (a bare ``conf:``
    loads as None)."""
    i = _conf_line(new)
    if i is None or _conf_keys(new) or not _conf_keys(old):
        return new
    return new[:i] + ["conf: {}\n"] + new[i + 1 :]
