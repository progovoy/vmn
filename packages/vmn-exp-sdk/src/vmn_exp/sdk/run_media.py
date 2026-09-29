#!/usr/bin/env python3
"""Rich logging of an SDK run: tables, images and histograms.

* ``log_table(name, data, columns=None, step=None)`` stores a columnar JSON
  artifact ``tables/<name>/<step>.json`` (see :mod:`vmn_exp.core.tables`) and
  logs ``{"type": "table", "name", "step", "path", "rows", "columns",
  "sha256", "size"}``.
* ``log_image(name, image, step=None, caption=None)`` stores
  ``media/<name>/<step>.png`` and logs ``{"type": "image", "name", "step",
  "path", "caption", "width", "height", "sha256", "size"}``.
* ``log_histogram(name, values, step=None, bins=64)`` bins the finite values
  here and logs ``{"type": "histogram", "name", "step", "bins", "counts"}``;
  *values* may instead be a precomputed ``{"bins": edges, "counts": counts}``
  (``len(bins) == len(counts) + 1``).

An image or table entry is also the run's record of its file as an output
(like an ``artifact`` entry: ``row["outputs"]``, lineage, ``use_artifact``);
``sha256``/``size`` are of the encoded bytes, hashed here before the
background upload (:mod:`vmn_exp.sdk.media_uploads`) stores exactly them.
The entry is built (and timestamped) here but logged only once its file is
stored; a file that fails to store is never logged.

*step* defaults to one past the name's last logged step (0 at first). numpy, Pillow and pandas
are optional and imported only when an input needs them.
"""
import hashlib
import json
import logging
import os
import shutil
from collections.abc import Mapping

from vmn_exp.core.histogram import histogram, precomputed
from vmn_exp.core.png import array_to_png, png_size, to_uint8
from vmn_exp.core.tables import MAX_TABLE_ROWS, table_document
from vmn_exp.core.writer import create_log_entry
from vmn_exp.sdk.media_uploads import staging_dir
from vmn_exp.sdk.run_artifacts import checked_artifact_name

_LOGGER = logging.getLogger("vmn_exp.sdk")


def _pil_image():
    try:
        from PIL import Image
    except ImportError:
        return None
    return Image


def _write_path_image(src, dest):
    """Copy a PNG; convert anything else with Pillow (or keep its format)."""
    ext = os.path.splitext(src)[1].lower()
    image_mod = _pil_image() if ext != ".png" else None
    if image_mod is None and ext != ".png":
        dest = os.path.splitext(dest)[0] + ext
        shutil.copyfile(src, dest)
        return dest
    if image_mod is None:
        shutil.copyfile(src, dest)
    else:
        with image_mod.open(src) as img:
            img.save(dest, format="PNG")
    return dest


def _write_array_image(array, dest):
    image_mod = _pil_image()
    if image_mod is None:
        with open(dest, "wb") as f:
            f.write(array_to_png(array))
        return dest
    pixels = to_uint8(array)
    if pixels.ndim == 3 and pixels.shape[2] == 1:
        pixels = pixels[:, :, 0]
    image_mod.fromarray(pixels).save(dest, format="PNG")
    return dest


def write_image(image, dest):
    """Write *image* as the PNG *dest*; returns the path written (a non-PNG
    file logged without Pillow keeps its own extension)."""
    if isinstance(image, (str, os.PathLike)):
        return _write_path_image(os.fspath(image), dest)
    if hasattr(image, "savefig"):  # matplotlib figure
        image.savefig(dest, format="png")
        return dest
    if hasattr(image, "save") and hasattr(image, "mode"):  # PIL image
        image.save(dest, format="PNG")
        return dest
    if hasattr(image, "shape") and hasattr(image, "dtype"):  # numpy array
        return _write_array_image(image, dest)
    raise TypeError(f"Cannot log a {type(image).__name__} as an image")


class RunMedia:
    """Mixed into :class:`~vmn_exp.sdk.run.Run`; needs ``_media_uploads`` (a
    :class:`~vmn_exp.sdk.media_uploads.MediaUploads`) and ``_append``.

    Media files are stored as artifacts without an ``artifact`` log entry of
    their own: the table/image entry is their record, as media and as an
    output. The uploader appends it once the file is stored.
    """

    def _media_step(self, kind, name, step):
        """*step*, checked, or the next free auto step of (*kind*, *name*)."""
        if step is None:
            return getattr(self, "_media_steps", {}).get((kind, name), 0)
        if not isinstance(step, int) or isinstance(step, bool) or step < 0:
            raise ValueError(f"step must be a non-negative integer, got {step!r}")
        return step

    def _step_taken(self, kind, name, step):
        """Later auto steps of (*kind*, *name*) follow *step*."""
        if not hasattr(self, "_media_steps"):
            self._media_steps = {}
        key = (kind, name)
        self._media_steps[key] = max(self._media_steps.get(key, 0), step + 1)

    def _close_media_uploads(self, timeout):
        """Wait for the queued files, whose entries are appended as they land."""
        if not self._media_uploads.close(timeout):
            _LOGGER.warning(f"vmn: the final media files of run {self.id} are still uploading")

    def _store(self, kind, name, step, path, produce, **fields):
        """Queue the file *produce(tmp path)* writes for storing as artifact
        *path* (its name may take the written file's extension); its *kind*
        entry is appended once it is stored. ``(width, height)`` of a PNG goes
        into the entry, with the stored bytes' ``sha256`` and ``size``."""
        tmp = staging_dir()
        try:
            written = produce(os.path.join(tmp, os.path.basename(path)))
            stored = checked_artifact_name(
                path[: -len(os.path.basename(path))] + os.path.basename(written)
            )
            with open(written, "rb") as f:
                data = f.read()
            if kind == "image":
                fields["width"], fields["height"] = png_size(data) or (None, None)
            entry = create_log_entry(
                kind, name=name, step=step, path=stored,
                sha256=hashlib.sha256(data).hexdigest(), size=len(data), **fields,
            )
            self._step_taken(kind, name, step)
        except BaseException:
            shutil.rmtree(tmp, ignore_errors=True)
            raise
        self._media_uploads.submit(tmp, written, stored, lambda: self._append(entry))

    def log_table(self, name, data, columns=None, step=None):
        doc, total = table_document(data, columns=columns)
        step = self._media_step("table", name, step)
        path = checked_artifact_name(f"tables/{name}/{step}.json")
        if doc["truncated"]:
            _LOGGER.warning(
                "Table %r has %d rows: truncated to the first %d", name, total, MAX_TABLE_ROWS
            )

        def produce(dest):
            with open(dest, "w", encoding="utf-8") as f:
                json.dump(doc, f, allow_nan=False)
            return dest

        extra = {"total_rows": total} if doc["truncated"] else {}
        self._store(
            "table", name, step, path, produce,
            rows=doc["rows"], columns=[c["name"] for c in doc["columns"]], **extra,
        )

    def log_image(self, name, image, step=None, caption=None):
        step = self._media_step("image", name, step)
        path = checked_artifact_name(f"media/{name}/{step}.png")
        self._store(
            "image", name, step, path, lambda dest: write_image(image, dest), caption=caption,
        )

    def log_histogram(self, name, values, step=None, bins=64):
        binned = precomputed(values) if isinstance(values, Mapping) else histogram(values, bins)
        if binned is None:
            _LOGGER.warning("Histogram %r has no finite values: not logged", name)
            return
        step = self._media_step("histogram", name, step)
        entry = create_log_entry("histogram", name=name, step=step, **binned)
        self._step_taken("histogram", name, step)
        self._append(entry)
