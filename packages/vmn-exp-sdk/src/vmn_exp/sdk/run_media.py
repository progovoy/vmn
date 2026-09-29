#!/usr/bin/env python3
"""Rich logging of an SDK run: tables, images and histograms.

* ``log_table(name, data, columns=None, step=None)`` stores a columnar JSON
  artifact ``tables/<name>/<step>.json`` (see :mod:`vmn_exp.core.tables`) and
  logs ``{"type": "table", "name", "step", "path", "rows", "columns"}``.
* ``log_image(name, image, step=None, caption=None)`` stores
  ``media/<name>/<step>.png`` and logs ``{"type": "image", "name", "step",
  "path", "caption", "width", "height"}``.
* ``log_histogram(name, values, step=None, bins=64)`` bins the finite values
  here and logs ``{"type": "histogram", "name", "step", "bins", "counts"}``.

*step* defaults to one past the name's last logged step (0 at first). numpy, Pillow and pandas
are optional and imported only when an input needs them.
"""
import json
import logging
import os
import shutil
import tempfile

from vmn_exp.core.histogram import histogram
from vmn_exp.core.png import array_to_png, png_file_size, to_uint8
from vmn_exp.core.tables import MAX_TABLE_ROWS, table_document
from vmn_exp.core.writer import create_log_entry
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
    """Mixed into :class:`~vmn_exp.sdk.run.Run`; needs ``_save_artifact_file``
    and ``_append``."""

    def _media_step(self, kind, name, step):
        """*step*, checked, or the next free auto step of (*kind*, *name*)."""
        if step is None:
            return getattr(self, "_media_steps", {}).get((kind, name), 0)
        if not isinstance(step, int) or isinstance(step, bool) or step < 0:
            raise ValueError(f"step must be a non-negative integer, got {step!r}")
        return step

    def _logged(self, kind, name, step, entry):
        """Append *entry*; later auto steps of (*kind*, *name*) follow *step*."""
        if not hasattr(self, "_media_steps"):
            self._media_steps = {}
        key = (kind, name)
        self._media_steps[key] = max(self._media_steps.get(key, 0), step + 1)
        self._append(entry)

    def _store(self, name, produce):
        """Save the file *produce(tmp path)* writes as artifact *name*; returns
        ``(artifact name stored under, (width, height) of a PNG or None)``."""
        with tempfile.TemporaryDirectory(prefix="vmn-media-") as tmp:
            written = produce(os.path.join(tmp, os.path.basename(name)))
            stored = name[: -len(os.path.basename(name))] + os.path.basename(written)
            self._save_artifact_file(written, checked_artifact_name(stored))
            return stored, png_file_size(written) if stored.endswith(".png") else None

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

        self._store(path, produce)
        entry = create_log_entry(
            "table", name=name, step=step, path=path, rows=doc["rows"],
            columns=[c["name"] for c in doc["columns"]],
        )
        if doc["truncated"]:
            entry["total_rows"] = total
        self._logged("table", name, step, entry)

    def log_image(self, name, image, step=None, caption=None):
        step = self._media_step("image", name, step)
        path, size = self._store(
            checked_artifact_name(f"media/{name}/{step}.png"),
            lambda dest: write_image(image, dest),
        )
        width, height = size or (None, None)
        entry = create_log_entry(
            "image", name=name, step=step, path=path, caption=caption,
            width=width, height=height,
        )
        self._logged("image", name, step, entry)

    def log_histogram(self, name, values, step=None, bins=64):
        binned = histogram(values, bins=bins)
        if binned is None:
            _LOGGER.warning("Histogram %r has no finite values: not logged", name)
            return
        step = self._media_step("histogram", name, step)
        entry = create_log_entry("histogram", name=name, step=step, **binned)
        self._logged("histogram", name, step, entry)
