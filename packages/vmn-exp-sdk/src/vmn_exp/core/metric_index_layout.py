#!/usr/bin/env python3
"""Constants of the indexed metric file layout (plan 12 §3.2)."""
import struct

MAGIC = b"VMSX"
VERSION = 1
CHUNK_POINTS = 65_536
LOD_SIZES = (64, 1024, 16384, 262144)
# footer_len, crc32(footer), MAGIC — the last bytes of the file.
TAIL = struct.Struct("<II4s")
