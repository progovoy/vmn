"""Compatibility for deprecated/renamed configuration keys.

Handles:
1. ``create_verinfo_files`` → ``create_snapshots`` rename
2. ``conventional_commits.default_release_mode`` (nested dict) → top-level ``release_mode_policy``
3. Top-level ``default_release_mode`` with policy values → ``release_mode_policy``
4. ``vmn_version_file`` backend (warn and skip)

Loading migrates in memory (debug log only); ``vmn stamp`` rewrites the
release-mode keys in the conf file via ``rewrite_deprecated_conf_keys``.

Safe to remove when: all conf.yml files have gone through at least one stamp
cycle that rewrites them.
"""
import re

from version_stamp.core.logging import VMN_LOGGER

_POLICY_VALUES = ("optional", "strict")
_CONF_LINE = re.compile(r"^conf:\s*(#.*)?$")
_KEY_LINE = re.compile(r"^(?P<ind> *)(?P<key>[A-Za-z_]\w*):(?P<rest>.*)$")
_SCALAR = re.compile(r"""^\s*(['"]?)(?P<val>[\w-]+)\1\s*(#.*)?$""")
_BLANK_OR_COMMENT = re.compile(r"^\s*(#.*)?$")


def migrate_config_keys(data_conf, app_conf_path):
    """Mutate ``data_conf`` dict in place, migrating deprecated keys.

    Returns the (possibly mutated) dict for chaining.
    """
    _migrate_create_verinfo_files(data_conf, app_conf_path)
    _migrate_nested_release_mode_policy(data_conf, app_conf_path)
    _migrate_top_level_release_mode_policy(data_conf, app_conf_path)
    return data_conf


def warn_vmn_version_file_backend(backend_name):
    """Log a warning if the deprecated vmn_version_file backend is used. Returns True if deprecated."""
    if backend_name == "vmn_version_file":
        VMN_LOGGER.warning(
            "Remove vmn_version_file version backend from the configuration"
        )
        return True
    return False


def _migrate_create_verinfo_files(data_conf, app_conf_path):
    if "create_verinfo_files" in data_conf and "create_snapshots" not in data_conf:
        data_conf["create_snapshots"] = data_conf["create_verinfo_files"]
        VMN_LOGGER.debug(
            "Migrating deprecated config key 'create_verinfo_files' "
            "to 'create_snapshots' in %s. "
            "Remove 'create_verinfo_files' from your conf.yml to silence this.",
            app_conf_path,
        )


def _migrate_nested_release_mode_policy(data_conf, app_conf_path):
    cc = data_conf.get("conventional_commits")
    if isinstance(cc, dict) and "default_release_mode" in cc:
        val = cc.pop("default_release_mode")
        if val in ("optional", "strict"):
            data_conf.setdefault("release_mode_policy", val)
        if not cc:
            data_conf["conventional_commits"] = True
        VMN_LOGGER.debug(
            "Migrating 'conventional_commits.default_release_mode' "
            "to top-level 'release_mode_policy' in %s.",
            app_conf_path,
        )


def _migrate_top_level_release_mode_policy(data_conf, app_conf_path):
    drm = data_conf.get("default_release_mode")
    if drm in ("optional", "strict"):
        data_conf.setdefault("release_mode_policy", drm)
        data_conf["default_release_mode"] = ""
        VMN_LOGGER.debug(
            "Migrating top-level 'default_release_mode: %s' "
            "to 'release_mode_policy' in %s.",
            drm,
            app_conf_path,
        )


def rewrite_deprecated_conf_keys(path, dry_run=False):
    """Rewrite the deprecated release-mode keys of the conf file at ``path``
    in place, keeping comments and key order. Returns whether it changes."""
    with open(path) as f:
        lines = f.readlines()
    new_lines = _rewrite_top_level_policy(_rewrite_nested_policy(lines))
    if new_lines == lines:
        return False
    if not dry_run:
        with open(path, "w") as f:
            f.writelines(new_lines)
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


def _conf_keys(lines):
    for i, line in enumerate(lines):
        if _CONF_LINE.match(line.rstrip()):
            return _direct_keys(lines, i)
    return []


def _has_policy(keys):
    return any(key == "release_mode_policy" for _, _, key, _ in keys)


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


def _rewrite_nested_policy(lines):
    keys = _conf_keys(lines)
    for i, ind, key, rest in keys:
        if key == "conventional_commits" and _BLANK_OR_COMMENT.match(rest):
            return _move_nested_policy(lines, i, ind, rest, _has_policy(keys))
    return lines


def _move_nested_policy(lines, i, ind, rest, has_policy):
    nested = [k for k in _direct_keys(lines, i) if k[2] == "default_release_mode"]
    if not nested:
        return lines
    j, _, _, value_rest = nested[0]
    end = _block_end(lines, i)
    block = lines[i + 1 : j] + lines[j + 1 : end]
    head = lines[i]
    if not any(_is_content(line) for line in block):
        head = f"{' ' * ind}conventional_commits: true{rest}\n"
    value = _scalar(value_rest)
    insert = []
    if value in _POLICY_VALUES and not has_policy:
        insert = [f"{' ' * ind}release_mode_policy: {value}\n"]
    return lines[:i] + [head] + block + insert + lines[end:]


def _rewrite_top_level_policy(lines):
    keys = _conf_keys(lines)
    has_policy = _has_policy(keys)
    out = list(lines)
    for i, _, key, rest in keys:
        if key != "default_release_mode" or _scalar(rest) not in _POLICY_VALUES:
            continue
        if has_policy:
            out[i] = None
        else:
            out[i] = out[i].replace("default_release_mode", "release_mode_policy", 1)
            has_policy = True
    return [line for line in out if line is not None]
