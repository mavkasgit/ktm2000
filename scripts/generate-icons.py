"""Generate KTM-2000 brand icons from a single design (128 viewBox).

Run from repo root:
  python scripts/generate-icons.py

Writes into frontend/public/ (favicon, logo, apple-touch, android sizes).
"""
from __future__ import annotations

import struct
from io import BytesIO
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent / "frontend" / "public"

SVG = """\
<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 128 128" role="img" aria-label="KTM-2000">
  <rect width="128" height="128" rx="28" fill="#0f172a"/>
  <rect x="16" y="16" width="96" height="96" rx="20" fill="none" stroke="#2dd4bf" stroke-width="8" stroke-linejoin="round"/>
  <path d="M 78 36 L 48 64 L 78 92 L 66 92 L 36 64 L 66 36 Z" fill="#2dd4bf" stroke="#2dd4bf" stroke-width="6" stroke-linejoin="round"/>
</svg>
"""

BG = (15, 23, 42, 255)  # #0f172a
TEAL = (45, 212, 191, 255)  # #2dd4bf
CHEVRON = [(78, 36), (48, 64), (78, 92), (66, 92), (36, 64), (66, 36)]


def make_logo(size: int) -> Image.Image:
    """Rasterize brand mark from design space 128 with optional supersampling."""
    ss = 4 if size >= 48 else (2 if size >= 24 else 1)
    canvas = size * ss
    sc = canvas / 128.0
    img = Image.new("RGBA", (canvas, canvas), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    r_bg = max(1, int(round(28 * sc)))
    draw.rounded_rectangle([0, 0, canvas - 1, canvas - 1], radius=r_bg, fill=BG)

    stroke = max(1, int(round(8 * sc)))
    pad = int(round(16 * sc))
    r_in = max(1, int(round(20 * sc)))
    draw.rounded_rectangle(
        [pad, pad, canvas - 1 - pad, canvas - 1 - pad],
        radius=r_in,
        outline=TEAL,
        width=stroke,
    )

    pts = [(int(round(x * sc)), int(round(y * sc))) for x, y in CHEVRON]
    draw.polygon(pts, fill=TEAL)

    if ss > 1:
        img = img.resize((size, size), Image.Resampling.LANCZOS)
    return img


def png_bytes(img: Image.Image) -> bytes:
    buf = BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def write_ico(path: Path, sizes: list[int]) -> None:
    """Multi-size ICO with embedded PNG payloads (Windows Vista+ / modern browsers)."""
    pngs = [png_bytes(make_logo(sz)) for sz in sizes]
    count = len(sizes)
    offset = 6 + 16 * count
    parts: list[bytes] = [struct.pack("<HHH", 0, 1, count)]
    blobs: list[bytes] = []
    for sz, png in zip(sizes, pngs):
        w = 0 if sz >= 256 else sz
        h = 0 if sz >= 256 else sz
        parts.append(struct.pack("<BBBBHHII", w, h, 0, 0, 1, 32, len(png), offset))
        blobs.append(png)
        offset += len(png)
    path.write_bytes(b"".join(parts) + b"".join(blobs))


def main() -> None:
    (ROOT / "favicon.svg").write_text(SVG, encoding="utf-8", newline="\n")
    (ROOT / "logo.svg").write_text(SVG, encoding="utf-8", newline="\n")

    write_ico(ROOT / "favicon.ico", [16, 32, 48])
    make_logo(180).save(ROOT / "apple-touch-icon.png", format="PNG", optimize=True)
    make_logo(192).save(ROOT / "icon-192.png", format="PNG", optimize=True)
    make_logo(512).save(ROOT / "icon-512.png", format="PNG", optimize=True)

    for p in sorted(ROOT.iterdir()):
        if p.is_file() and not p.name.startswith("_"):
            print(f"{p.name:24} {p.stat().st_size:7} B")

    data = (ROOT / "favicon.ico").read_bytes()
    count = struct.unpack_from("<H", data, 4)[0]
    print(f"ICO entries: {count}")
    off = 6
    for _ in range(count):
        w, h, _, _, _, _, size, _ = struct.unpack_from("<BBBBHHII", data, off)
        w = 256 if w == 0 else w
        h = 256 if h == 0 else h
        print(f"  {w}x{h} payload={size}")
        off += 16


if __name__ == "__main__":
    main()
