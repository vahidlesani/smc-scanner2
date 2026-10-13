"""Contact-sheet builder for render review rounds (Viva 10-13).

Usage:  python tools/make_sheet.py <glob-dir> <out.png>
Lays every spot_*/perp_* PNG in the dir onto a labelled 3-col grid.
"""
import glob
import sys

from PIL import Image, ImageDraw


def main() -> None:
    d = sys.argv[1] if len(sys.argv) > 1 else "renders_r74"
    out = sys.argv[2] if len(sys.argv) > 2 else d.rstrip("/") + "/SHEET.png"
    files = sorted(glob.glob(d + "/spot_*.png")) + sorted(glob.glob(d + "/perp_*.png"))
    cols, tw, th = 3, 800, 450
    rows = (len(files) + cols - 1) // cols
    sheet = Image.new("RGB", (cols * tw, rows * (th + 26)), "#20242A")
    dr = ImageDraw.Draw(sheet)
    for i, f in enumerate(files):
        im = Image.open(f).convert("RGB").resize((tw, th))
        x, y = (i % cols) * tw, (i // cols) * (th + 26)
        sheet.paste(im, (x, y + 26))
        dr.text((x + 8, y + 7), f.split("/")[-1].replace(".png", ""), fill="#FDF49F")
    sheet.save(out)
    print(f"sheet {out}: {len(files)} panels")


if __name__ == "__main__":
    main()
