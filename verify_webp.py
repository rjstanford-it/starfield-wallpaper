#!/usr/bin/env python3
"""
Verify an animated WebP: frame count, real per-frame durations, loop flag, and
how black the black actually is.

This exists because the obvious checks lie:

  * Pillow reports per-frame durations as None when READING WebP, even when the
    file contains them correctly. The only trustworthy way to read them is to
    walk the RIFF chunks and pull the duration field out of each ANMF header.

  * ffmpeg's native WebP decoder returns zero frames for animated files, so
    `ffprobe` is no help either.

Optionally pass --frames <dir> to compare the encoded output against the source
PNGs, which is how you catch lossy ringing around bright stars.
"""
import argparse
import glob
import os
import struct
import sys

import numpy as np
from PIL import Image


def read_chunks(path):
    data = open(path, "rb").read()
    if data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        sys.exit(f"{path} is not a WebP file")
    off, durations, loop = 12, [], None
    while off + 8 <= len(data):
        fourcc = data[off:off + 4]
        size = struct.unpack("<I", data[off + 4:off + 8])[0]
        payload = data[off + 8:off + 8 + size]
        if fourcc == b"ANIM" and len(payload) >= 6:
            loop = struct.unpack("<H", payload[4:6])[0]
        elif fourcc == b"ANMF" and len(payload) >= 16:
            # ANMF header: 3B x, 3B y, 3B w-1, 3B h-1, 3B duration, 1B flags
            durations.append(payload[12] | (payload[13] << 8) | (payload[14] << 16))
        off += 8 + size + (size & 1)
    return durations, loop


def main():
    p = argparse.ArgumentParser(description="Verify an animated WebP.")
    p.add_argument("webp")
    p.add_argument("--frames", help="source PNG dir, to check for encoding artefacts")
    args = p.parse_args()

    durations, loop = read_chunks(args.webp)
    if not durations:
        sys.exit("no ANMF chunks found -- this is not an animated WebP")

    total = sum(durations) / 1000.0
    print(f"frames        : {len(durations)}")
    print(f"duration      : {durations[0]} ms/frame, uniform: {len(set(durations)) == 1}")
    print(f"loop length   : {total:.2f} s  ({len(durations)/total:.1f} fps)")
    print(f"loop count    : {loop}  ({'infinite' if loop == 0 else 'finite'})")

    im = Image.open(args.webp)
    print(f"dimensions    : {im.size[0]}x{im.size[1]}")

    im.seek(0)
    a0 = np.asarray(im.convert("RGB")).astype(int)
    im.seek(im.n_frames - 1)
    al = np.asarray(im.convert("RGB")).astype(int)
    print(f"pure black    : {100 * (a0.sum(axis=2) == 0).mean():.1f}% of pixels")
    print(f"mean bright   : {a0.mean():.2f} / 255")
    print(f"loop seam     : {np.abs(a0 - al).mean():.4f} / 255  (lower = smoother wrap)")

    if args.frames:
        src = sorted(glob.glob(os.path.join(args.frames, "f*.png")))
        if not src:
            sys.exit(f"no source frames found in {args.frames}")
        worst_err, worst_dirty = 0, 0.0
        for i in {0, len(src) // 4, len(src) // 2, 3 * len(src) // 4, len(src) - 1}:
            if i >= im.n_frames or i >= len(src):
                continue
            ref = np.asarray(Image.open(src[i]).convert("RGB")).astype(np.int16)
            im.seek(i)
            dec = np.asarray(im.convert("RGB")).astype(np.int16)
            mask = ref.sum(axis=2) == 0
            worst_err = max(worst_err, int(np.abs(dec - ref).max()))
            worst_dirty = max(worst_dirty, 100.0 * (dec.sum(axis=2)[mask] > 0).mean())
        print()
        print(f"max px error  : {worst_err}  (0 = lossless, intact)")
        print(f"dirty black   : {worst_dirty:.3f}%  (light leaked into should-be-off pixels)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
