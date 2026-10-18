"""把标题栏的图标渲染成一张 PNG，**不开任何可见窗口**。

## 为什么需要它

图标是**画出来的**（`icons.py` 的图元列表，不是字体字形），所以"它长什么样"
没法用文字回答，也没法用 `cget` 读出来。用户要看一眼才能判断。

而 `capture_screenshot.py` 要在屏幕上开一扇真实窗口——用户明确要求过不要
那么做。所以这里换一条路：**直接用 `raster` 把图元栅格化**（和程序里
`FlatButton` 贴上去的是同一条代码路径），再用 Pillow 拼成一张对照图。

## 用法

    python tools/render_icons.py                     # 输出到 TEMP，160px
    python tools/render_icons.py --out icons.png --size 96 --theme dark

从左到右：跟随系统（显示器）、浅色（太阳）、深色（月亮）、设置（齿轮）。
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="")
    parser.add_argument("--size", type=int, default=160, help="每个图标的渲染边长（像素）")
    parser.add_argument("--theme", default="light", choices=["light", "dark"])
    args = parser.parse_args()

    from PIL import Image  # noqa: PLC0415 - 只有这个工具需要 Pillow，程序本身不依赖

    from gui_of_edge_tts import icons, raster  # noqa: PLC0415
    from gui_of_edge_tts.theme import Theme  # noqa: PLC0415

    theme = Theme.detect(args.theme)
    palette = theme.palette
    background = palette.background
    colour = palette.text
    painters = [
        ("跟随系统", icons.THEME_ICONS["system"]),
        ("浅色", icons.THEME_ICONS["light"]),
        ("深色", icons.THEME_ICONS["dark"]),
        ("设置", icons.SETTINGS_ICON),
    ]

    size = max(16, int(args.size))
    # 画布要比图标标称尺寸大一圈：图元可以到 ±0.57·size（见 icons 的注释）。
    box = int(round(size * icons.ICON_BOX_SCALE)) + 2
    sheet = Image.new("RGBA", (box * len(painters), box), background)
    for index, (_label, painter) in enumerate(painters):
        png = raster.rasterise(
            painter(box / 2.0, box / 2.0, size, colour, background),
            box,
            box,
            background,
        )
        icon = Image.open(io.BytesIO(png)).convert("RGBA")
        sheet.alpha_composite(icon, (index * box, 0))

    target = (
        Path(args.out)
        if args.out
        else Path(os.environ.get("TEMP", ".")) / f"etts-icons-{args.theme}.png"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    sheet.save(target)
    print(f"已保存 {target}（{sheet.size[0]}x{sheet.size[1]}，主题 {args.theme}）")
    print("从左到右：跟随系统（显示器）、浅色（太阳）、深色（月亮）、设置（齿轮）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
