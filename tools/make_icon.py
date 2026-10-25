"""生成应用图标 assets/app.ico（纯矢量绘制，无需美术素材）。

用法：python tools/make_icon.py
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "assets" / "app.ico"

BG = (29, 32, 38, 255)
GRID = (62, 72, 86, 255)
BOLT = (232, 180, 60, 255)
BOLT_HI = (255, 226, 130, 255)
TOWER = (150, 200, 230, 255)


def draw(size: int = 256) -> Image.Image:
    s = size
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = int(s * 0.18)
    d.rounded_rectangle([0, 0, s - 1, s - 1], radius=r, fill=BG)

    # 网格底纹（格子地图的暗示）
    step = s / 5
    for i in range(1, 5):
        d.line([(i * step, s * 0.10), (i * step, s * 0.90)], fill=GRID, width=max(1, s // 90))
        d.line([(s * 0.10, i * step), (s * 0.90, i * step)], fill=GRID, width=max(1, s // 90))

    # 铁塔
    tx = s * 0.30
    d.line([(tx, s * 0.80), (tx + s * 0.03, s * 0.36)], fill=TOWER, width=max(2, s // 34))
    d.line([(tx + s * 0.16, s * 0.80), (tx + s * 0.07, s * 0.36)], fill=TOWER, width=max(2, s // 34))
    d.line([(tx + s * 0.01, s * 0.46), (tx + s * 0.10, s * 0.46)], fill=TOWER, width=max(2, s // 40))
    d.line([(tx + s * 0.02, s * 0.58), (tx + s * 0.11, s * 0.58)], fill=TOWER, width=max(2, s // 40))

    # 闪电
    bolt = [
        (s * 0.66, s * 0.14), (s * 0.40, s * 0.55), (s * 0.56, s * 0.55),
        (s * 0.44, s * 0.88), (s * 0.78, s * 0.42), (s * 0.60, s * 0.42),
    ]
    d.polygon(bolt, fill=BOLT)
    d.line([bolt[0], bolt[1]], fill=BOLT_HI, width=max(2, s // 48))

    # 底部价格柱（股价/财报的暗示）
    bars = [(0.13, 0.22), (0.19, 0.30), (0.25, 0.26)]
    return img


def main() -> None:
    OUT.parent.mkdir(exist_ok=True)
    base = draw(256)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    base.save(OUT, format="ICO", sizes=sizes)
    print(f"已生成 {OUT} ({OUT.stat().st_size / 1024:.1f} KB)")


if __name__ == "__main__":
    main()
