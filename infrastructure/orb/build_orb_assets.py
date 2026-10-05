"""Build NOVA's orb assets from the art-direction video (1280×720, 24 fps, sphere centered at 639×350, r≈197).

    uv run --with pillow --with imageio-ffmpeg python infrastructure/orb/build_orb_assets.py path/to/orb.mp4

Outputs in apps/web/public/orb/:
* orb.mp4 — one segment per NOVA state, ping-pong loops encoded in the file (seamless loops, no reverse playback
  needed), keyframes at every segment start. Prints the frame-exact segment table to paste in nova-orb.tsx.
* <look>.webp — the 12 looks as transparent stills (small orbs, reduced motion, posters).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFilter

FPS = 24
CENTER, RADIUS, CROP_SIZE = (639, 350), 197, 420
CROP = f"crop={CROP_SIZE}:{CROP_SIZE}:{CENTER[0] - CROP_SIZE // 2}:{CENTER[1] - CROP_SIZE // 2}"
# state, first frame, end frame (exclusive), ping-pong loop
SEGMENTS = [
    ("idle", 0, 17, True),
    ("thinking", 19, 72, True),
    ("working", 72, 120, True),
    ("waiting", 19, 43, True),
    ("clarification", 142, 170, True),
    ("completed", 154, 240, False),
    ("calm", 223, 240, True),
]
LOOKS = {"veille": 0.05, "activation": 1.3, "rubans": 2.5, "tourbillon": 3.6, "concentration": 4.6, "impulsion": 5.55,
         "ondes": 6.5, "convergence": 7.0, "lumiere": 7.35, "coeur": 7.95, "eclat": 8.6, "calme": 9.6}  # fmt: skip


def main(video: str) -> None:
    ff = imageio_ffmpeg.get_ffmpeg_exe()
    out = Path(__file__).resolve().parents[2] / "apps/web/public/orb"
    out.mkdir(parents=True, exist_ok=True)
    parts, labels, table, frames = [], [], {}, 0
    for i, (name, a, b, pingpong) in enumerate(SEGMENTS):
        base = f"[0:v]trim=start_frame={a}:end_frame={b},setpts=PTS-STARTPTS,{CROP},scale=384:384:flags=lanczos,setsar=1"
        if pingpong:
            parts += [f"{base},split=2[s{i}a][s{i}b]", f"[s{i}b]reverse,setpts=PTS-STARTPTS[s{i}r]"]
            labels += [f"[s{i}a]", f"[s{i}r]"]
            n = 2 * (b - a)
        else:
            parts.append(f"{base}[s{i}a]")
            labels.append(f"[s{i}a]")
            n = b - a
        table[name] = [round(frames / FPS, 4), round((frames + n) / FPS, 4)]
        frames += n
    graph = ";".join(parts) + ";" + "".join(labels) + f"concat=n={len(labels)}:v=1:a=0,fps={FPS}[out]"
    keys = ",".join(str(v[0]) for v in table.values())
    subprocess.run(
        [ff, "-hide_banner", "-loglevel", "error", "-y", "-i", video, "-filter_complex", graph, "-map", "[out]", "-an",
         "-c:v", "libx264", "-profile:v", "main", "-pix_fmt", "yuv420p", "-crf", "24", "-preset", "slow", "-g", "12",
         "-force_key_frames", keys, "-movflags", "+faststart", str(out / "orb.mp4")],
        check=True,
    )  # fmt: skip
    for name, ts in LOOKS.items():
        tmp = out / f"_{name}.png"
        subprocess.run(
            [
                ff,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-ss",
                str(ts),
                "-i",
                video,
                "-frames:v",
                "1",
                "-vf",
                CROP,
                str(tmp),
            ],
            check=True,
        )
        image = Image.open(tmp).convert("RGBA").resize((256, 256), Image.LANCZOS)
        mask = Image.new("L", (1024, 1024), 0)
        r = RADIUS * 1024 / CROP_SIZE
        ImageDraw.Draw(mask).ellipse((512 - r, 512 - r, 512 + r, 512 + r), fill=255)
        image.putalpha(mask.resize((256, 256), Image.LANCZOS).filter(ImageFilter.GaussianBlur(0.6)))
        image.crop(image.getbbox()).save(out / f"{name}.webp", quality=88, method=6)
        os.remove(tmp)
    print(json.dumps(table, indent=2))


if __name__ == "__main__":
    main(sys.argv[1])
