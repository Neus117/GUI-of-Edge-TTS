"""把标题栏那五颗按钮的真实外观合成成一张图，**不开任何可见窗口**。

## 为什么需要它

按钮外形与图标现在都是**栅格化位图**（`raster.py` + `icons.py`），所以
"它长什么样"没法用文字回答，也没法用 `cget` 读出来——用户必须看一眼。

而 `capture_screenshot.py` 要在屏幕上开一扇真实窗口，用户明确要求过不要那样做。
所以这里换一条路：**用和 `FlatButton._paint` 完全相同的代码路径**生成每个按钮的
位图（同一套 `raster` 调用、同一套主题色、同一套尺寸公式），再拼成一张对照图。

它验证的是"形状与配色对不对"，不是"整窗排版对不对"——后者由
`ui_layout_probe.py` 用真实控件几何来验。

## 用法

    python tools/render_titlebar.py                 # 深浅两套都出
    python tools/render_titlebar.py --theme dark --scale 8
"""

from __future__ import annotations

import argparse
import io
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))
sys.path.insert(0, str(REPO / "tools"))


def compose(theme_name: str, scale: int):
    from PIL import Image, ImageDraw, ImageFont  # noqa: PLC0415

    from gui_of_edge_tts import icons, raster  # noqa: PLC0415
    from gui_of_edge_tts.theme import FONT_BODY_PT, Theme  # noqa: PLC0415

    theme = Theme.detect(theme_name)
    palette = theme.palette
    side = theme.px(32)                      # SQUARE_ICON_BUTTON 的物理像素
    pad = 6
    radius = theme.px(6)
    stroke = max(1, theme.px(1))

    def button(fill: str, border: str, painter, foreground: str, label: str = ""):
        png = raster.rounded_rect_png(side, side, radius, fill, border, stroke)
        image = Image.open(io.BytesIO(png)).convert("RGBA")
        if painter is not None:
            icon_size = side * 0.48
            # 位图要比标称尺寸大一圈：图元可到 ±0.57·size（见 icons 的注释）
            box = int(round(icon_size * icons.ICON_BOX_SCALE)) + 2
            # **painters 的 background 必须传按钮填充色**：齿轮的中心孔是
            # 用底色"盖"出来的（画中画，见规范 34.8）。
            primitives = painter(box / 2.0, box / 2.0, icon_size, foreground, fill)
            icon_png = raster.rasterise(primitives, box, box, fill)
            icon = Image.open(io.BytesIO(icon_png)).convert("RGBA")
            offset = (side - box) // 2
            image.alpha_composite(icon, (offset, offset))
        if label:
            # "?" 是纯 ASCII，字体一定有字形——按程序里的字号/粗体画出来。
            # 这里只是预览工具，用 Pillow 画文字不影响程序里的渲染路径。
            draw = ImageDraw.Draw(image)
            size_px = max(9, int(round((FONT_BODY_PT + 3) * theme.dpi / 72.0)))
            font = None
            for face in ("msyhbd.ttc", "msyh.ttc", "segoeuib.ttf"):
                try:
                    font = ImageFont.truetype(face, size_px)
                    break
                except OSError:
                    continue
            if font is not None:
                draw.text((side / 2.0, side / 2.0), label, fill=foreground,
                          font=font, anchor="mm")
        return image

    cells = []
    for index, painter in enumerate(icons.THEME_ICONS.values()):
        if index == 0:
            cells.append(button(palette.accent, palette.accent, painter, palette.accent_text))
        else:
            cells.append(button(palette.surface, palette.border_strong, painter, palette.text))
    cells.append(button(palette.surface, palette.border_strong, icons.SETTINGS_ICON, palette.text))
    cells.append(button(palette.surface, palette.border_strong, None, palette.text, label="?"))

    width = len(cells) * (side + 2 * pad)
    height = side + 2 * pad
    sheet = Image.new("RGBA", (width, height), tuple(raster.parse_colour(palette.background)))
    for index, cell in enumerate(cells):
        sheet.alpha_composite(cell, (pad + index * (side + 2 * pad), pad))
    return sheet.convert("RGB").resize((width * scale, height * scale), Image.NEAREST)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", default="", choices=["", "light", "dark"])
    parser.add_argument("--scale", type=int, default=6)
    parser.add_argument("--out", default="")
    args = parser.parse_args()

    modes = [args.theme] if args.theme else ["light", "dark"]
    for mode in modes:
        image = compose(mode, args.scale)
        if args.out:
            target = Path(args.out)
        else:
            target = Path(os.environ.get("TEMP", ".")) / f"etts-titlebar-{mode}.png"
        target.parent.mkdir(parents=True, exist_ok=True)
        image.save(target)
        print(f"已保存 {target}（{image.size[0]}x{image.size[1]}，放大 {args.scale} 倍）")
    print("从左到右：跟随系统（显示器）/ 浅色（太阳）/ 深色（月亮）/ 设置（齿轮）/ 提示（问号）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
