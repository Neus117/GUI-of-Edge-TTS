"""栅格化圆角：2× 超采样不能悄悄退化成多边形。"""

from __future__ import annotations

import unittest

import context  # noqa: F401  pylint: disable=unused-import
from gui_of_edge_tts import raster


class RoundedRectRasterTests(unittest.TestCase):
    def test_box_downsample_size_and_colour(self) -> None:
        # 4×4 纯色高分辨率图，降到 2×2；每个目标像素都应仍是该纯色。
        rows = [bytes([10, 20, 30, 255] * 4) for _ in range(4)]
        output = raster._downsample_rows(rows, 2, 2, 2, opaque=True)
        self.assertEqual(len(output), 2)
        self.assertEqual(output[0], bytes([10, 20, 30, 255] * 2))

    def test_supersampled_png_is_generated(self) -> None:
        png = raster.rounded_rect_png(
            20,
            10,
            3,
            "#ffffff",
            "#000000",
            1,
            background="#f0f0f0",
            supersample=2,
        )
        self.assertTrue(png.startswith(b"\x89PNG\r\n\x1a\n"))


if __name__ == "__main__":
    unittest.main()
