#!/usr/bin/env python3
import datetime
import hashlib
import os
import re
import stat
import tempfile

import yaml

from version_stamp.core.constants import (
    BRANCH_CONF_DIR,
    ISLAND_BRANCH_PREFIX,
    JINJA_TAG_RE,
    LEGACY_TRACKING_PREFIX,
)
from version_stamp.core.logging import VMN_LOGGER

# libyaml's loader is ~10x faster than the pure-Python one, and experiment
# listings parse one metadata.yml (and one run_state.yml) per run.
_FAST_SAFE_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def yaml_safe_load(stream_or_text):
    """``yaml.safe_load`` semantics, on the C loader when libyaml is present."""
    return yaml.load(stream_or_text, Loader=_FAST_SAFE_LOADER)


def conf_mapping(data):
    """The ``conf`` mapping of a loaded conf file; ``{}`` for an empty file, a
    bare ``conf:`` or a file without the key."""
    conf = data.get("conf") if isinstance(data, dict) else None
    return conf if isinstance(conf, dict) else {}


_URL_RE = re.compile(r"\A([A-Za-z][A-Za-z0-9+.-]*)://([^/?#]*)(.*)\Z", re.S)
_SSH_SCHEMES = frozenset({"ssh", "git+ssh", "ssh+git"})


def strip_url_credentials(url):
    """*url* without its secret userinfo: an ``ssh://`` URL keeps a bare
    username (``ssh://git@host/x``), any other URL loses the whole
    ``user[:password]@`` (a username alone can be a token). scp-like
    ``git@host:path``, paths and non-strings come back unchanged."""
    match = isinstance(url, str) and _URL_RE.match(url)
    if not match or "@" not in match.group(2):
        return url
    scheme, authority, rest = match.groups()
    userinfo, _, host = authority.rpartition("@")
    user = userinfo.partition(":")[0]
    if user and scheme.lower() in _SSH_SCHEMES:
        host = f"{user}@{host}"
    return f"{scheme}://{host}{rest}"


def _redact_remote(entry):
    if isinstance(entry, dict) and "remote" in entry:
        return dict(entry, remote=strip_url_credentials(entry["remote"]))
    return entry


def redact_changesets(changesets):
    """A copy of *changesets* whose repos' ``remote`` carry no credentials."""
    return {path: _redact_remote(info) for path, info in changesets.items()}


def redact_record_remotes(metadata):
    """A copy of record *metadata* whose ``remote`` and ``changesets[*].remote``
    carry no credentials; anything but a dict comes back unchanged."""
    if not isinstance(metadata, dict):
        return metadata
    redacted = _redact_remote(metadata)
    changesets = metadata.get("changesets")
    if isinstance(changesets, dict):
        redacted = dict(redacted, changesets=redact_changesets(changesets))
    return redacted


def parse_record_metadata(raw):
    """A snapshot/experiment record's ``metadata.yml`` dict, or None; its
    remotes are redacted (:func:`redact_record_remotes`), as older records may
    still carry credentials.

    None for a missing or unparsable file and for legacy ``create_snapshots``
    verinfo files, which share the tree but carry no ``verstr``.
    """
    if not raw:
        return None
    try:
        meta = yaml_safe_load(raw)
    except yaml.YAMLError:
        return None
    if not (isinstance(meta, dict) and "verstr" in meta):
        return None
    return redact_record_remotes(meta)


_UNSAFE_IN_COMPONENT = ("/", "\\", os.sep, "\0", "..")


def valid_path_component(name):
    """Whether *name* (a verstr, artifact name, ...) stays one path component."""
    return (
        bool(name)
        and name != "."
        and not any(bad in name for bad in _UNSAFE_IN_COMPONENT)
    )


def valid_app_path(app_name):
    """Whether *app_name* is a relative path of real components (``root/svc``)."""
    return bool(app_name) and all(
        valid_path_component(part) for part in app_name.split("/")
    )


def now_iso():
    """UTC now as the ``...Z`` ISO string every vmn record is timestamped with."""
    return (
        datetime.datetime.now(datetime.timezone.utc).isoformat().replace("+00:00", "Z")
    )


def sha256_file(abs_path):
    h = hashlib.sha256()
    with open(abs_path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _current_umask():
    mask = os.umask(0)
    os.umask(mask)
    return mask


def atomic_write(path, data):
    """Replace *path* with *data* (str as UTF-8, or bytes) atomically.

    Readers see the old file or the new one. An existing file keeps its mode;
    a new one gets the mode a plain ``open()`` would give under the umask.
    """
    directory, name = os.path.split(path)
    fd, tmp = tempfile.mkstemp(dir=directory or os.curdir, prefix=f".{name}.", suffix=".tmp")
    os.close(fd)
    try:
        with open(tmp, "wb") as f:
            f.write(data.encode("utf-8") if isinstance(data, str) else data)
            f.flush()
            os.fsync(f.fileno())
        if os.path.exists(path):
            mode = stat.S_IMODE(os.stat(path).st_mode)
        else:
            mode = 0o666 & ~_current_umask()
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class MalformedBlockError(ValueError):
    """A managed marker block is unbalanced, duplicated or out of order."""


def marked_block_span(content, begin, end):
    """``(start, stop)`` of the single *begin*..*end* block, None when absent."""
    counts = (content.count(begin), content.count(end))
    if counts == (0, 0):
        return None
    if counts != (1, 1):
        raise MalformedBlockError("markers")
    start, end_start = content.index(begin), content.index(end)
    if end_start < start:
        raise MalformedBlockError("marker order")
    return start, end_start + len(end)


def upsert_marked_block(content, begin, end, block):
    """``(new_content, verb)``: *block* replaces the managed block in place, else
    is appended after a blank line (or is the whole file when it was blank)."""
    span = marked_block_span(content, begin, end)
    if span:
        new, verb = content[: span[0]] + block + content[span[1] :], "Updated"
    elif content.strip():
        new, verb = f"{content.rstrip()}\n\n{block}", "Appended"
    else:
        new, verb = block, "Wrote"
    return new.rstrip("\n") + "\n", verb


def _clean_split_result(items):
    """Remove the single empty string that split() produces from empty output."""
    if len(items) == 1 and items[0] == "":
        items.pop(0)
    return items


def comment_out_jinja(text: str) -> str:
    """
    Wrap every live tag so it survives rendering, e.g.
        {{ foo }}  →  {% raw %}{{ foo }}{% endraw %}
    """
    return JINJA_TAG_RE.sub(lambda m: "{% raw %}" + m.group(1) + "{% endraw %}", text)


def resolve_root_path():
    cwd = os.getcwd()
    if "VMN_WORKING_DIR" in os.environ:
        cwd = os.environ["VMN_WORKING_DIR"]

    root_path = os.path.realpath(os.path.expanduser(cwd))

    exist = os.path.exists(os.path.join(root_path, ".git"))
    exist = exist or os.path.exists(os.path.join(root_path, ".vmn"))
    while not exist:
        try:
            prev_path = root_path
            root_path = os.path.realpath(os.path.join(root_path, ".."))
            if prev_path == root_path:
                raise RuntimeError()

            exist = os.path.exists(os.path.join(root_path, ".git"))
            exist = exist or os.path.exists(os.path.join(root_path, ".vmn"))
        except Exception:
            VMN_LOGGER.debug("Logged exception: ", exc_info=True)
            root_path = None
            break
    if root_path is None:
        raise RuntimeError("Running from an unmanaged directory")

    return root_path


def branch_to_conf_prefix(branch_name):
    """Sanitize branch name for use in conf filenames (abc/feat → abc-feat)."""
    return branch_name.replace("/", "-")


def _conf_basename(root):
    return "root_conf.yml" if root else "conf.yml"


def is_island_branch(branch):
    """True for a private `vmn wt` branch (island/<name>/<source>)."""
    return bool(branch) and branch.startswith(ISLAND_BRANCH_PREFIX)


def is_legacy_tracking_branch(branch):
    """True for a vmn_tracking_remote__* branch older vmn created."""
    return bool(branch) and branch.startswith(LEGACY_TRACKING_PREFIX)


def legacy_tracking_branch_name(remote_ref, hexsha):
    return f"{LEGACY_TRACKING_PREFIX}{remote_ref.replace('/', '_')}__from_{hexsha[:5]}"


def one_line_reason(exc):
    """An exception's message on one line, for log messages."""
    return str(exc).replace("\n", " ").strip()


def branch_conf_canonical_path(app_dir_path, branch, root=False):
    """Canonical layout: {app_dir}/branch_conf/{branch as dirs}/(root_)conf.yml"""
    return os.path.join(
        app_dir_path,
        BRANCH_CONF_DIR,
        branch.replace("/", os.sep),
        _conf_basename(root),
    )


def branch_conf_flat_path(app_dir_path, branch, root=False):
    """Flat layout: {app_dir}/{branch-with-dashes}_(root_)conf.yml"""
    return os.path.join(
        app_dir_path,
        f"{branch_to_conf_prefix(branch)}_{_conf_basename(root)}",
    )


def branch_conf_legacy_path(app_dir_path, branch, root=False):
    """Legacy nested layout: {app_dir}/{seg0}/../{leaf}_(root_)conf.yml"""
    segments = branch.split("/")
    return os.path.join(
        app_dir_path,
        *segments[:-1],
        f"{segments[-1]}_{_conf_basename(root)}",
    )


def resolve_branch_conf_path(app_dir_path, branch, root=False):
    """Resolve a branch-specific conf file, supporting all layouts.

    Precedence: canonical > flat > legacy. Falls back to the default
    (root_)conf.yml with convention None when no branch conf exists.
    """
    if branch:
        for convention, path_fn in (
            ("canonical", branch_conf_canonical_path),
            ("flat", branch_conf_flat_path),
            ("legacy", branch_conf_legacy_path),
        ):
            path = path_fn(app_dir_path, branch, root=root)
            if os.path.isfile(path):
                return path, convention

    return os.path.join(app_dir_path, _conf_basename(root)), None


class WrongTagFormatException(Exception):
    pass
