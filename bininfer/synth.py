"""Synthetic corpus generator used by the tests and the demo.

It emits blobs that follow the profile grammar in ``profiles/e903-demo.json``
so the inference engine can be validated against known ground truth.
"""
from __future__ import annotations

import json
import os
import random
import struct

SIZE_POOL = (4, 8, 12, 16, 24, 32)


def _entry(name: str, tag: int, value: bytes) -> bytes:
    raw = name.encode("ascii")
    return struct.pack("<I", len(raw)) + raw + struct.pack("<I", tag) + value


def _value(rng: random.Random, size: int) -> bytes:
    if size == 4:
        return struct.pack("<I", rng.getrandbits(32))
    if size == 8:
        return struct.pack("<Q", rng.getrandbits(64))
    if size == 12:
        return struct.pack("<3f", *(rng.uniform(-100, 100) for _ in range(3)))
    return bytes(rng.getrandbits(8) for _ in range(size))


def generate(outdir: str, files: int = 40, tags: int = 6, fields: int = 8,
             seed: int = 42, tail_bytes: int = 0) -> dict:
    """Write ``files`` blobs plus ``truth.json`` into ``outdir``."""
    os.makedirs(outdir, exist_ok=True)
    rng = random.Random(seed)
    tag_list = [rng.getrandbits(32) for _ in range(tags)]
    tag_sizes = {tag: rng.choice(SIZE_POOL) for tag in tag_list}
    pairs = [(f"field_{i}", tag_list[i % tags]) for i in range(fields)]

    for index in range(files):
        body = bytearray()
        body += struct.pack("<I", 0x03E9)
        body += struct.pack("<I", 0)  # patched below with the real total length
        body += struct.pack("<Q", 0)
        strings = ["corpus", "synthetic"]
        body += struct.pack("<I", len(strings))
        for i, text in enumerate(strings):
            raw = text.encode("utf-8")
            body += struct.pack("<I", len(raw)) + raw + struct.pack("<I", i)
        body += struct.pack("<I", len(pairs))
        for name, tag in pairs:
            body += _entry(name, tag, _value(rng, tag_sizes[tag]))
        if tail_bytes:
            body += bytes(rng.getrandbits(8) for _ in range(tail_bytes))
        struct.pack_into("<I", body, 4, len(body))
        with open(os.path.join(outdir, f"{index:04d}.bin"), "wb") as fh:
            fh.write(body)

    truth = {
        "tag_sizes": {f"0x{tag:08x}": size for tag, size in tag_sizes.items()},
        "fields": [[name, f"0x{tag:08x}", tag_sizes[tag]] for name, tag in pairs],
        "files": files,
        "seed": seed,
    }
    with open(os.path.join(outdir, "truth.json"), "w", encoding="utf-8") as fh:
        json.dump(truth, fh, indent=2)
        fh.write("\n")
    return truth
