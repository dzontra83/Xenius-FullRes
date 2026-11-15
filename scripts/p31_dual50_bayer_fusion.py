#!/usr/bin/env python3
"""Xenius P31: two-frame Bayer RAW arithmetic fusion; NOT native GCam HDR+.

For DngCreator-generated H50 8192x6144, single-channel, uncompressed
RAW16 stored as one contiguous TIFF strip per row. Input CFA / EXIF / levels
must agree. Copies first DNG header and substitutes pixel rows by rounded
mean of two sensor captures. No exposure bracketing, alignment, or tone maps.

Usage: python3 scripts/p31_dual50_bayer_fusion.py B1.dng B2.dng output.dng
Requires pip install numpy tifffile
"""
from __future__ import annotations
import argparse, shutil
from pathlib import Path
import numpy as np
import tifffile


def describe(p: Path):
    with tifffile.TiffFile(p) as t:
        q = t.pages[0]
        ts = q.tags
        checks = ("StripOffsets", "StripByteCounts", "ImageWidth", "ImageLength",
                  "BitsPerSample", "Compression", "WhiteLevel", "CFAPattern",
                  "BlackLevel", "Orientation")
        for tag in checks:
            if tag not in ts:
                raise ValueError(f"{p}: missing {tag}")
        w, h = q.imagewidth, q.imagelength
        offsets, lengths = q.dataoffsets, q.databytecounts
        if q.compression != 1 or q.dtype != np.uint16 or q.samplesperpixel != 1:
            raise ValueError("Only uncompressed single-channel uint16 Bayer DNGs supported")
        if len(offsets) != h or set(lengths) != {w * 2}:
            raise ValueError("Expected one TIFF strip per image row")
        expected = tuple(range(offsets[0], offsets[0] + w * h * 2, w * 2))
        if tuple(offsets) != expected:
            raise ValueError("Noncontiguous strips; fusion refused")
        meta = tuple(ts[k].value for k in ("BitsPerSample", "WhiteLevel",
                                            "CFAPattern", "BlackLevel", "Orientation"))
        return w, h, int(offsets[0]), meta


def fuse(a_path: Path, b_path: Path, output: Path):
    wa, ha, oa, ma = describe(a_path)
    wb, hb, ob, mb = describe(b_path)
    if (wa, ha, ma) != (wb, hb, mb):
        raise ValueError("Inputs have different dimensions/CFA/levels/orientation")
    if output.resolve() in (a_path.resolve(), b_path.resolve()):
        raise ValueError("Refusing to overwrite an input DNG")
    if wa != 8192 or ha != 6144 or ma[1] != 1023 or ma[2] != b"\x00\x01\x01\x02":
        raise ValueError("This proof is strictly for validated H35/H85 50MP RGGB")
    shutil.copyfile(a_path, output)
    a = np.memmap(a_path, dtype="<u2", mode="r", offset=oa, shape=(ha, wa))
    b = np.memmap(b_path, dtype="<u2", mode="r", offset=ob, shape=(hb, wb))
    out = np.memmap(output, dtype="<u2", mode="r+", offset=oa, shape=(ha, wa))
    # Measured P30 values are 10-bit 0..1023; ushort addition cannot overflow.
    for y in range(0, ha, 64):
        sl = slice(y, min(ha, y + 64))
        block_a = a[sl]
        block_b = b[sl]
        if block_a.max() > 1023 or block_b.max() > 1023:
            raise ValueError("Unsupported raw values >1023; refusing to merge")
        out[sl] = ((block_a + block_b + 1) // 2).astype("<u2")
    out.flush()
    del a, b, out
    if describe(output) != (wa, ha, oa, ma):
        raise ValueError("Output DNG metadata validation failed")
    print("P31_FUSION_VALIDATED", output, f"{wa}x{ha}", "RGBA_Bayer_unmodified")


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("b1", type=Path)
    p.add_argument("b2", type=Path)
    p.add_argument("output", type=Path)
    args = p.parse_args()
    fuse(args.b1, args.b2, args.output)
