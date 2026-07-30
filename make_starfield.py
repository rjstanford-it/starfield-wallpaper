#!/usr/bin/env python3
"""
Render a seamlessly-looping dark starfield as a sequence of PNG frames.

Intended for OLED displays, where the design goals are specific:

  * The background is PURE black (0,0,0). On OLED those pixels are genuinely
    off -- no light emitted, no wear accumulated, no power drawn. It also keeps
    the average picture level near zero, so a panel's automatic brightness
    limiter has no reason to dim the rest of the screen.

  * Motion is sinusoidal wobble plus brightness twinkle, NOT linear drift.
    A drifting field only loops seamlessly if it wraps a whole screen width per
    cycle, which forces either a very long file or uncomfortably fast motion.
    Sinusoids at integer harmonics return exactly to their starting state, so
    the loop is perfect at any frame count while the motion stays slow.

  * Nothing bright stays still. Every lit pixel moves and varies, so panel wear
    is spread rather than concentrated -- the entire reason to prefer an
    animated wallpaper over a static one.

Encode the frames with encode_webp.py.
"""
import argparse
import os
import sys

import numpy as np
from PIL import Image


def build_layers(args, rng):
    """
    Three parallax layers: many faint distant stars, fewer bright near ones.

    Returns a list of (count, (bright_lo, bright_hi), radius, wobble_px).
    """
    n = args.stars
    return [
        (int(n * 0.68), (0.06, 0.20), 0.7, 2.0 * args.wobble),
        (int(n * 0.25), (0.20, 0.48), 1.1, 4.5 * args.wobble),
        (int(n * 0.07), (0.50, 0.92), 1.7, 7.0 * args.wobble),
    ]


def build_stars(args, rng):
    stars = []
    for count, (blo, bhi), radius, wobble in build_layers(args, rng):
        for _ in range(count):
            # Mostly neutral with a few cool/warm stars. Kept desaturated so
            # nothing reads as a coloured blob against black.
            t = rng.random()
            if t < 0.72:
                tint = (1.0, 1.0, 1.0)
            elif t < 0.88:
                tint = (0.72, 0.82, 1.0)
            else:
                tint = (1.0, 0.88, 0.74)

            stars.append({
                "x": rng.random() * args.width,
                "y": rng.random() * args.height,
                "b": rng.uniform(blo, bhi),
                "r": radius * rng.uniform(0.8, 1.35),
                "tint": tint,
                # Integer harmonics give an exact period over `frames`, which is
                # what makes the loop seamless. See --speed in the CLI help for
                # how these interact with loop length.
                "th": int(rng.integers(args.twinkle_lo, args.twinkle_hi)),
                "tp": rng.random() * 2 * np.pi,
                "ta": rng.uniform(0.25, 0.65),
                "wh": int(rng.integers(args.wobble_lo, args.wobble_hi)),
                "wp": rng.random() * 2 * np.pi,
                "wob": wobble,
            })
    return stars


def splat(buf, cx, cy, radius, rgb, W, H):
    """Additively draw one soft round star into the RGB float buffer."""
    rad = max(1, int(np.ceil(radius * 3)))
    x0, x1 = int(cx) - rad, int(cx) + rad + 1
    y0, y1 = int(cy) - rad, int(cy) + rad + 1
    x0c, x1c = max(0, x0), min(W, x1)
    y0c, y1c = max(0, y0), min(H, y1)
    if x0c >= x1c or y0c >= y1c:
        return
    ys = np.arange(y0c, y1c)[:, None]
    xs = np.arange(x0c, x1c)[None, :]
    g = np.exp(-((xs - cx) ** 2 + (ys - cy) ** 2) / (2.0 * radius * radius))
    for ch in range(3):
        if rgb[ch] > 0:
            buf[y0c:y1c, x0c:x1c, ch] += g * rgb[ch]


def main():
    p = argparse.ArgumentParser(
        description="Render a seamlessly-looping dark starfield as PNG frames.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
speed note:
  Apparent motion is proportional to (harmonic / loop length). Lengthening the
  loop therefore slows everything down on its own. If you raise --frames and
  want to keep the original speed, scale the harmonic ranges up by the same
  factor. For example going from 180 to 500 frames (2.78x) while wanting only
  40%% slower motion means multiplying the harmonics by about 1.5x.
""")
    p.add_argument("outdir", help="directory to write PNG frames into")
    p.add_argument("--width", type=int, default=2560)
    p.add_argument("--height", type=int, default=1440)
    p.add_argument("--frames", type=int, default=500,
                   help="frame count; at 15 fps, 500 gives a 33 s loop")
    p.add_argument("--stars", type=int, default=768)
    p.add_argument("--seed", type=int, default=20260728)
    p.add_argument("--wobble", type=float, default=1.0,
                   help="multiplier on positional wobble amplitude")
    p.add_argument("--twinkle-lo", type=int, default=2)
    p.add_argument("--twinkle-hi", type=int, default=7)
    p.add_argument("--wobble-lo", type=int, default=2)
    p.add_argument("--wobble-hi", type=int, default=4)
    p.add_argument("--gamma", type=float, default=1.15,
                   help="keeps faint stars visible without lifting the black floor")
    args = p.parse_args()

    rng = np.random.default_rng(args.seed)
    os.makedirs(args.outdir, exist_ok=True)

    W, H = args.width, args.height
    stars = build_stars(args, rng)
    print(f"{len(stars)} stars, {args.frames} frames at {W}x{H}", flush=True)

    buf = np.zeros((H, W, 3), dtype=np.float32)

    for f in range(args.frames):
        u = f / args.frames                      # 0..1 across the loop
        buf.fill(0.0)

        for s in stars:
            tw = 1.0 + s["ta"] * np.sin(2 * np.pi * s["th"] * u + s["tp"])
            b = s["b"] * max(0.0, tw)
            if b <= 0.004:
                continue
            ang = 2 * np.pi * s["wh"] * u + s["wp"]
            cx = s["x"] + np.cos(ang) * s["wob"]
            cy = s["y"] + np.sin(ang) * s["wob"] * 0.6
            splat(buf, cx, cy,
                  s["r"], (b * s["tint"][0], b * s["tint"][1], b * s["tint"][2]),
                  W, H)

        out = np.clip(buf, 0.0, 1.0) ** (1.0 / args.gamma)
        img = Image.fromarray((out * 255.0 + 0.5).astype(np.uint8), "RGB")
        img.save(os.path.join(args.outdir, f"f{f:04d}.png"), compress_level=1)

        if f % 50 == 0:
            print(f"  frame {f}/{args.frames}", flush=True)

    print(f"frames written to {args.outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
