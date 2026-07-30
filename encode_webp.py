#!/usr/bin/env python3
"""
Encode rendered starfield frames into a looping animated WebP.

Two things here are deliberate and both were arrived at by measurement rather
than preference:

1. LOSSLESS by default.
   A 1-3px bright star on pure black is the pathological case for a lossy block
   transform: it cannot represent that much local contrast, so the error smears
   across the block as a visible cross/halo around every bright star. Measured
   against the source frames on a 2560x1440 starfield:

       config        MB/500f   dirty black px   max error
       lossy q72        5.1         1.38%          37
       lossy q90        7.1         0.55%          26
       lossy q98       12.0         0.17%          20
       lossless        14.5         0.00%           0

   "dirty black px" is the share of should-be-black pixels that decoded to
   non-zero. That column matters twice over on OLED: those pixels are visible
   artefacts AND they are emitting light, defeating the whole reason for a pure
   black background. Lossless costs ~3x the bytes and is worth it for a file
   that is loaded once and displayed permanently.

2. Pillow rather than ffmpeg.
   ffmpeg's libwebp_anim muxer produces a structurally valid animation but does
   not write per-frame durations, which leaves playback speed to whatever the
   viewer guesses. Pillow writes ANMF durations correctly.

   Note that Pillow *reports* frame durations as None when reading WebP even
   when they are present, so verifying the output requires parsing the RIFF
   container -- see verify_webp.py.
"""
import argparse
import glob
import os
import sys

from PIL import Image


def main():
    p = argparse.ArgumentParser(description="Encode PNG frames into a looping animated WebP.")
    p.add_argument("srcdir", help="directory containing f0000.png, f0001.png, ...")
    p.add_argument("output", help="path to write the .webp to")
    p.add_argument("--fps", type=int, default=15)
    p.add_argument("--lossy", action="store_true",
                   help="use lossy encoding (smaller, but rings around stars -- not advised)")
    p.add_argument("--quality", type=int, default=100)
    p.add_argument("--method", type=int, default=4,
                   help="0=fast .. 6=slowest/smallest; 6 measured no smaller than 4 here")
    args = p.parse_args()

    paths = sorted(glob.glob(os.path.join(args.srcdir, "f*.png")))
    if not paths:
        sys.exit(f"no frames matching f*.png found in {args.srcdir}")

    duration_ms = round(1000 / args.fps)
    mode = "lossy" if args.lossy else "lossless"
    print(f"encoding {len(paths)} frames, {mode}, {args.fps} fps ({duration_ms} ms/frame)")

    first = Image.open(paths[0]).convert("RGB")

    def rest():
        for path in paths[1:]:
            yield Image.open(path).convert("RGB")

    first.save(
        args.output,
        format="WEBP",
        save_all=True,
        append_images=rest(),
        duration=duration_ms,
        loop=0,                       # 0 = loop forever
        lossless=not args.lossy,
        quality=args.quality,
        method=args.method,
        minimize_size=True,
    )

    size = os.path.getsize(args.output)
    total = len(paths) * duration_ms / 1000
    print(f"wrote {args.output}  ({size/1024/1024:.1f} MB, {total:.2f} s loop)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
