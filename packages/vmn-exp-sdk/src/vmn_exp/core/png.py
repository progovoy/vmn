#!/usr/bin/env python3
"""A tiny stdlib PNG encoder, so a numpy image can be logged without Pillow.

8-bit gray, gray+alpha, RGB or RGBA; every scanline uses filter 0 (none) and
the image data is one zlib stream. Pillow compresses better and is used by
the SDK when it is installed; this is the fallback.
"""
import struct
import zlib

SIGNATURE = b"\x89PNG\r\n\x1a\n"
_COLOR_TYPES = {1: 0, 2: 4, 3: 2, 4: 6}  # channels -> PNG colour type


def _chunk(kind, body):
    crc = zlib.crc32(kind + body) & 0xFFFFFFFF
    return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", crc)


def encode_png(pixels, width, height, channels):
    """PNG bytes of row-major 8-bit *pixels* (``height * width * channels`` bytes)."""
    if channels not in _COLOR_TYPES:
        raise ValueError(f"PNG needs 1-4 channels, got {channels}")
    stride = width * channels
    if len(pixels) != stride * height:
        raise ValueError(f"{len(pixels)} bytes is not a {width}x{height}x{channels} image")
    raw = b"".join(
        b"\x00" + bytes(pixels[row * stride : (row + 1) * stride]) for row in range(height)
    )
    header = struct.pack(">IIBBBBB", width, height, 8, _COLOR_TYPES[channels], 0, 0, 0)
    return (
        SIGNATURE
        + _chunk(b"IHDR", header)
        + _chunk(b"IDAT", zlib.compress(raw, 6))
        + _chunk(b"IEND", b"")
    )


def png_size(data):
    """``(width, height)`` from a PNG's IHDR, or None when *data* is not a PNG."""
    if len(data) < 24 or data[:8] != SIGNATURE or data[12:16] != b"IHDR":
        return None
    return struct.unpack(">II", data[16:24])


def png_file_size(path):
    with open(path, "rb") as f:
        return png_size(f.read(24))


def to_uint8(array):
    """*array* (numpy, HxW or HxWxC) as uint8: floats are taken as 0..1."""
    import numpy as np

    array = np.asarray(array)
    if array.dtype == np.uint8:
        return array
    if array.dtype == bool:
        return array.astype(np.uint8) * 255
    if array.dtype.kind == "f":
        scaled = np.nan_to_num(array.astype(np.float64), nan=0.0) * 255.0
        return np.clip(np.rint(scaled), 0, 255).astype(np.uint8)
    return np.clip(array, 0, 255).astype(np.uint8)


def image_shape(array):
    """``(height, width, channels)`` of an HxW or HxWxC (C in 1..4) array."""
    shape = tuple(array.shape)
    if len(shape) == 2:
        return shape[0], shape[1], 1
    if len(shape) == 3 and shape[2] in _COLOR_TYPES:
        return shape
    raise ValueError(f"An image is HxW or HxWxC with C in 1..4, got shape {shape}")


def array_to_png(array):
    """PNG bytes of a numpy image (see :func:`to_uint8` for the value range)."""
    height, width, channels = image_shape(array)
    pixels = to_uint8(array).tobytes()
    return encode_png(pixels, width, height, channels)
