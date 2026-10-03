"""Metric objects (plan 12) for ``vmn exp push``.

Each local writer's visible objects (its ``.vmx``, else its sealed parts and
stream) go when missing remotely or of another size. A ``.vmx`` or part goes
through ``put_indexed``, which drops the remote stream objects it supersedes,
so a stream pushed before the run compacted never lingers beside its ``.vmx``.
"""
import os

from vmn_exp.core.metric_files import is_part_file, is_stream_file, part_writer_and_k


def push_metrics(local, target, app_name, verstr):
    """Upload the local metric objects the remote lacks or holds at another size."""
    objects = local.metric_objects(app_name, verstr)
    if not objects:
        return
    remote = {name: size for names in target.metric_objects(app_name, verstr).values()
              for name, size in names}
    record_dir = local.local_record_dir(app_name, verstr)
    for writer, names in objects.items():
        for name, size in names:
            if remote.get(name) != size:
                _upload(target, app_name, verstr, writer, name,
                        os.path.join(record_dir, name))


def _upload(target, app_name, verstr, writer, name, path):
    if is_stream_file(name):
        with open(path, "rb") as f:
            target.save_file(app_name, verstr, name, f.read())
        return
    part = part_writer_and_k(name)[1] if is_part_file(name) else None
    target.put_indexed(app_name, verstr, writer, path, part=part, replace=True)
