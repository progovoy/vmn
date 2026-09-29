"""Per-writer log shipping for ``vmn exp push``.

A writer's local log is one ``log.<writer>.jsonl``; its remote copy is the
base object plus segments. The remote copy must be a prefix of the local one.
Push ships the complete local lines past the remote's size as one conditional
segment (``put_log_segment``, ``If-None-Match``). When the remote size is not
what the ledger says this host shipped (no ledger, an orphan leaked by an
older vmn, another host), the remote bytes are compared with the local
prefix first; a mismatch fails loudly and never starts over, because the
remote bytes are someone else's.
"""
from vmn_exp.storage.files import log_object_name, log_writer_and_seq
from vmn_exp.storage.s3_base import parallel_map


class LogPrefixMismatch(RuntimeError):
    """The remote log of a writer is not a prefix of the local one."""


def push_logs(local, target, app_name, verstr, shipped=None, finished=False):
    """Ship each local writer's new complete lines; returns ``{writer: bytes
    the remote now holds}`` (the ledger's ``log_bytes``). *shipped* is the
    previous ``log_bytes``. With *finished*, a writer's remote objects are
    compacted into one. The legacy ``log.yml`` is a plain file, not shipped
    here. Raises :class:`LogPrefixMismatch`."""
    shipped = shipped or {}
    sizes = {}
    for writer in sorted(local.log_sizes(app_name, verstr)):
        if writer == "":
            continue
        pusher = _WriterLog(local, target, app_name, verstr, writer)
        sizes[writer] = pusher.push(shipped.get(writer), finished)
    return sizes


class _WriterLog:
    def __init__(self, local, target, app_name, verstr, writer):
        self._local, self._target = local, target
        self._at = (app_name, verstr)
        self._writer = writer

    def push(self, shipped, finished):
        objects = list(self._target.log_objects(*self._at, self._writer))
        remote_size = sum(size for _, size in objects)
        if remote_size and remote_size != shipped:
            local = self._local_bytes(0)
            self._verify_prefix(objects, remote_size, local[:remote_size])
            chunk = _complete_lines(local[remote_size:])
        else:
            chunk = _complete_lines(self._local_bytes(remote_size))
        if chunk:
            seqs = [log_writer_and_seq(name)[1] for name, _ in objects]
            seq = max(seqs) + 1 if seqs else 0
            self._target.put_log_segment(*self._at, self._writer, seq, chunk)
        if finished and len(objects) + bool(chunk) > 1:
            self._target.compact_log_segments(*self._at, self._writer)
        return remote_size + len(chunk)

    def _local_bytes(self, offset):
        name = log_object_name(self._writer)
        return self._local.read_file_from(*self._at, name, offset) or b""

    def _verify_prefix(self, objects, remote_size, local):
        bodies = parallel_map(
            lambda name: self._target.load_file(*self._at, name) or b"",
            [name for name, _ in objects],
        )
        remote = b"".join(bodies)
        if len(remote) != remote_size or remote != local:
            raise LogPrefixMismatch(
                f"{self._at[1]}: the remote log of writer {self._writer!r} is not "
                "a prefix of the local one (another host with the same writer "
                "id?). Not pushing it; set a unique VMN_WRITER_ID per host."
            )


def _complete_lines(data):
    """*data* up to its last newline: a partial line waits for the next push."""
    return data[: data.rfind(b"\n") + 1]
