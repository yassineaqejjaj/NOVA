"""Build NOVA's orb assets from the art-direction video (1280×720, 24 fps, sphere centered at 639×350, r≈197).

    uv run --with pillow --with imageio-ffmpeg python infrastructure/orb/build_orb_assets.py path/to/orb.mp4

Outputs in apps/web/public/orb/:
* orb.mp4 — one segment per NOVA state. Loops always play *forward*: the last ``D`` seconds of each loop are
  crossfaded into its first ``D`` seconds, so jumping from the end back to the start is invisible (no reverse
  playback, no cut). Calm states are slowed down with motion interpolation (no stutter). Keyframes at every
  segment start. Prints the frame-exact segment table to paste in ``nova-orb.tsx``.
* <look>.webp — the 12 looks as transparent stills (small orbs, reduced motion, posters).
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFilter

FPS = 24
CENTER, RADIUS, CROP_SIZE = (639, 350), 197, 420
CROP = (
    f"crop={CROP_SIZE}:{CROP_SIZE}:{CENTER[0] - CROP_SIZE // 2}:{CENTER[1] - CROP_SIZE // 2},scale=384:384:flags=lanczos,setsar=1"
)
INTERPOLATE = "minterpolate=fps=24:mi_mode=mci:mc_mode=aobmc:me_mode=bidir:vsbmc=1"
# state, first frame, end frame (exclusive), slow-down factor, loop crossfade seconds (None = played once)
SEGMENTS = [
    ("idle", 0, 19, 2.5, 0.5),
    ("thinking", 19, 72, 1.25, 0.5),
    ("working", 72, 120, 1.0, 0.45),
    ("waiting", 19, 43, 2.0, 0.5),
    ("clarification", 142, 170, 1.75, 0.5),
    ("completed", 154, 240, 1.0, None),
    ("calm", 219, 240, 2.5, 0.5),
]
LOOKS = {"veille": 0.05, "activation": 1.3, "rubans": 2.5, "tourbillon": 3.6, "concentration": 4.6, "impulsion": 5.55,
         "ondes": 6.5, "convergence": 7.0, "lumiere": 7.35, "coeur": 7.95, "eclat": 8.6, "calme": 9.6}  # fmt: skip


def run(ff: str, *args: str) -> str:
    result = subprocess.run([ff, "-hide_banner", "-y", *args], capture_output=True, text=True)
    if result.returncode:
        raise RuntimeError(f"ffmpeg failed: {result.stderr.strip()[-600:]}")
    return result.stderr


def frames(ff: str, path: Path) -> int:
    log = subprocess.run(
        [ff, "-hide_banner", "-i", str(path), "-map", "0:v", "-f", "null", "-"], capture_output=True, text=True
    ).stderr
    return int(re.findall(r"frame=\s*(\d+)", log)[-1])


def segment(ff: str, video: str, tmp: Path, name: str, first: int, end: int, slow: float, crossfade: float | None) -> Path:
    raw = tmp / f"{name}_raw.mp4"
    chain = f"trim=start_frame={first}:end_frame={end},setpts=PTS-STARTPTS,{CROP}"
    if slow > 1:
        chain += f",setpts={slow}*PTS,{INTERPOLATE}"
    run(
        ff,
        "-i",
        video,
        "-filter_complex",
        f"[0:v]{chain},format=yuv420p[v]",
        "-map",
        "[v]",
        "-c:v",
        "libx264",
        "-crf",
        "10",
        str(raw),
    )
    if crossfade is None:
        return raw
    n = frames(ff, raw)
    d = round(crossfade * FPS)
    length = n - d  # the loop: tail (length..n) fades into head (0..d), then body (d..length)
    looped = tmp / f"{name}.mp4"
    graph = (
        f"[0:v]split=3[a][b][c];"
        f"[a]trim=start_frame={length}:end_frame={n},setpts=PTS-STARTPTS,fps={FPS},settb=1/{FPS}[tail];"
        f"[b]trim=start_frame=0:end_frame={d},setpts=PTS-STARTPTS,fps={FPS},settb=1/{FPS}[head];"
        f"[c]trim=start_frame={d}:end_frame={length},setpts=PTS-STARTPTS,fps={FPS},settb=1/{FPS}[body];"
        # frame k of the mix = tail·(1 - k/d) + head·(k/d): starts exactly on raw[length], the frame after the loop end
        f"[tail][head]blend=all_expr='A*(1-N/{d})+B*(N/{d})'[mix];"
        f"[mix][body]concat=n=2:v=1:a=0,fps={FPS},format=yuv420p[v]"
    )
    run(ff, "-i", str(raw), "-filter_complex", graph, "-map", "[v]", "-c:v", "libx264", "-crf", "10", str(looped))
    return looped


def main(video: str) -> None:
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    out = Path(__file__).resolve().parents[2] / "apps/web/public/orb"
    out.mkdir(parents=True, exist_ok=True)
    table: dict[str, list[float]] = {}
    with tempfile.TemporaryDirectory() as tmp_dir:
        tmp = Path(tmp_dir)
        pieces, start = [], 0
        for name, first, end, slow, crossfade in SEGMENTS:
            piece = segment(ff, video, tmp, name, first, end, slow, crossfade)
            n = frames(ff, piece)
            table[name] = [round(start / FPS, 4), round((start + n) / FPS, 4)]
            pieces.append(piece)
            start += n
        listing = tmp / "list.txt"
        listing.write_text("".join(f"file '{p}'\n" for p in pieces))
        keys = ",".join(str(v[0]) for v in table.values())
        run(ff, "-f", "concat", "-safe", "0", "-i", str(listing), "-an", "-c:v", "libx264", "-profile:v", "main", "-pix_fmt", "yuv420p",
            "-crf", "23", "-preset", "slow", "-g", "12", "-force_key_frames", keys, "-movflags", "+faststart", str(out / "orb.mp4"))  # fmt: skip
    for name, ts in LOOKS.items():
        tmp_png = out / f"_{name}.png"
        run(ff, "-ss", str(ts), "-i", video, "-frames:v", "1", "-vf", CROP.split(",scale")[0], str(tmp_png))
        image = Image.open(tmp_png).convert("RGBA").resize((256, 256), Image.LANCZOS)
        mask = Image.new("L", (1024, 1024), 0)
        r = RADIUS * 1024 / CROP_SIZE
        ImageDraw.Draw(mask).ellipse((512 - r, 512 - r, 512 + r, 512 + r), fill=255)
        image.putalpha(mask.resize((256, 256), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.6)))
        image.crop(image.getbbox()).save(out / f"{name}.webp", quality=88, method=6)
        os.remove(tmp_png)
    print(json.dumps(table, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
