"""Generate the ReportFlow logo assets (placeholder — swap the files to rebrand).

Draws a blue rounded-square "document" with three report lines and a green flow arrow,
then writes:

    assets/reportflow.png   (512x512, used by the UI window/header)
    assets/reportflow.ico   (multi-size, used by the exes and installer)

Run with:  uv run python packaging/make_logo.py
Requires Pillow (in the dev extra). The generated files are committed so normal builds
don't need Pillow.
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ASSETS = Path(__file__).resolve().parents[1] / "assets"

BLUE = (37, 99, 235, 255)  # matches ui.style ACCENT
BLUE_DARK = (30, 64, 175, 255)
GREEN = (22, 163, 74, 255)
WHITE = (255, 255, 255, 255)


def draw_logo(size: int = 512) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    s = size / 512  # scale factor

    # Rounded-square background.
    d.rounded_rectangle(
        [24 * s, 24 * s, 488 * s, 488 * s],
        radius=96 * s,
        fill=BLUE,
        outline=BLUE_DARK,
        width=int(8 * s),
    )

    # Document "report lines".
    line_x0, line_x1 = 120 * s, 392 * s
    for i, y in enumerate((150, 230, 310)):
        width = line_x1 if i == 0 else line_x1 - 60 * s * i
        d.rounded_rectangle([line_x0, y * s, width, (y + 44) * s], radius=22 * s, fill=WHITE)

    # Green flow arrow (bottom-right): shaft + head.
    d.rounded_rectangle([150 * s, 384 * s, 320 * s, 428 * s], radius=22 * s, fill=GREEN)
    d.polygon(
        [(320 * s, 356 * s), (410 * s, 406 * s), (320 * s, 456 * s)],
        fill=GREEN,
    )
    return img


def main() -> None:
    ASSETS.mkdir(parents=True, exist_ok=True)
    logo = draw_logo(512)
    png_path = ASSETS / "reportflow.png"
    logo.save(png_path)

    ico_path = ASSETS / "reportflow.ico"
    logo.save(ico_path, sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (256, 256)])

    print(f"Wrote {png_path}")
    print(f"Wrote {ico_path}")


if __name__ == "__main__":
    main()
