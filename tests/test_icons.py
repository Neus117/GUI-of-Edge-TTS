"""图标图元的几何约束：**能画出来**，而且**不会被位图边界裁掉**。

这两条都不是"看着差不多"能判的：

* 图元坐标一旦超出 ``±ICON_BOX_SCALE/2 × size``，栅格化时会被直接切掉，
  表现为图标边缘一条**平直的口子**。太阳的光点最远到 0.52·size：
  27px 下按 ``size+2`` 开画布只剩 1 像素余量，放大渲染（160px）就会被裁。
* painter 的签名必须统一带 ``background``：齿轮的中心孔是拿按钮底色
  "盖"出来的（画中画，见规范 34.8），签名不一致会在 hover/选中态下
  露出一块不属于当前底色的色块。
"""

from __future__ import annotations

import unittest

import context  # noqa: F401  pylint: disable=unused-import
from gui_of_edge_tts import icons


def coordinates(primitive) -> list:
    """把一个图元里**所有 x/y 坐标**按顺序取出来。"""
    kind = primitive[0]
    if kind in ("rect", "ellipse", "line"):
        return list(primitive[1:5])
    if kind == "polygon":
        return list(primitive[1])
    if kind == "arc":
        cx, cy, rx, ry, _start, _extent, _width = primitive[1:8]
        return [cx - rx, cy - ry, cx + rx, cy + ry]
    raise AssertionError(f"测试没覆盖这个图元：{kind}")


class IconGeometryTests(unittest.TestCase):
    #: 这几档覆盖 96 DPI（15.36px）、175% DPI（26.88px）与放大预览（160px）。
    SIZES = (15.36, 26.88, 48.0, 160.0)

    def test_every_painter_accepts_background(self) -> None:
        for painter in list(icons.THEME_ICONS.values()) + [icons.SETTINGS_ICON]:
            parts = painter(10.0, 10.0, 20.0, "#000000", "#FFFFFF")
            self.assertTrue(parts, f"{painter.__name__} 没有画出任何图元")

    def test_primitives_fit_inside_the_bitmap(self) -> None:
        """所有坐标必须落在 ``±0.6·size`` 内——这就是位图的半边长。"""
        limit = icons.ICON_BOX_SCALE / 2.0
        for size in self.SIZES:
            for painter in list(icons.THEME_ICONS.values()) + [icons.SETTINGS_ICON]:
                for primitive in painter(0.0, 0.0, size, "#000000", "#FFFFFF"):
                    xs, ys = coordinates(primitive)[0::2], coordinates(primitive)[1::2]
                    for value in xs:
                        self.assertLessEqual(
                            abs(value), limit * size + 1e-6,
                            f"{painter.__name__} 在 size={size} 时 x={value:.2f} 超出位图",
                        )
                    for value in ys:
                        self.assertLessEqual(
                            abs(value), limit * size + 1e-6,
                            f"{painter.__name__} 在 size={size} 时 y={value:.2f} 超出位图",
                        )

    def test_sun_is_solid_not_hollow(self) -> None:
        """小尺寸下空心圆的环宽只剩 1~2 像素——太阳必须是实心圆盘。"""
        parts = icons.icon_sun(50.0, 50.0, 100.0, "#000000")
        kind, x0, y0, x1, y1, stroke, _colour, fill = parts[0]
        self.assertEqual(kind, "ellipse")
        self.assertEqual(stroke, 0, "太阳的圆心必须是实心（stroke=0）")
        self.assertIsNone(fill)
        # 八个小光点，一共 9 个图元
        self.assertEqual(len(parts), 9)

    def test_gear_hole_uses_button_background(self) -> None:
        """中心孔的颜色必须跟着按钮底色走，否则 hover/选中态会露馅。"""
        parts = icons.icon_gear(50.0, 50.0, 100.0, "#000000", "#ABCDEF")
        hole = parts[-1]
        self.assertEqual(hole[0], "ellipse")
        self.assertEqual(hole[6], "#ABCDEF")
        self.assertEqual(hole[5], 0, "孔必须是实心圆，不能是描边圆环")

    def test_moon_is_shifted_right(self) -> None:
        """月牙的视觉重心在左，整条轮廓要右移（``MOON_SHIFT_RATIO``）。

        ⚠️ 判据用**最左点**，不用所有点的平均值：多边形的点在外弧上分布
        不均匀，平均 x 会被拉偏，量不到"平移"。外圆最左点是
        ``shift - 0.45·size``；没有平移时是 ``-0.45·size``，差 0.12·size。
        """
        size = 100.0
        parts = icons.icon_moon(0.0, 0.0, size, "#000000")
        xs = list(parts[0][1])[0::2]
        expected = (icons.MOON_SHIFT_RATIO - 0.45) * size
        self.assertAlmostEqual(min(xs), expected, delta=0.01 * size)


if __name__ == "__main__":
    unittest.main()
