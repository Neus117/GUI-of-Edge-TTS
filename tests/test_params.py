"""合成参数的解析、校验与归一化。"""

from __future__ import annotations

import unittest

import context  # noqa: F401  pylint: disable=unused-import
from gui_of_edge_tts import params


class RateTests(unittest.TestCase):
    def test_plain_number(self) -> None:
        self.assertEqual(params.parse_rate("20"), "+20%")
        self.assertEqual(params.parse_rate("-20"), "-20%")

    def test_with_percent_sign(self) -> None:
        self.assertEqual(params.parse_rate("+30%"), "+30%")
        self.assertEqual(params.parse_rate("30 %"), "+30%")

    def test_multiplier(self) -> None:
        self.assertEqual(params.parse_rate("1.2x"), "+20%")
        self.assertEqual(params.parse_rate("0.5x"), "-50%")

    def test_empty_and_zero(self) -> None:
        self.assertEqual(params.parse_rate(""), "+0%")
        self.assertEqual(params.parse_rate("   "), "+0%")
        self.assertEqual(params.parse_rate("0"), "+0%")

    def test_rounding(self) -> None:
        self.assertEqual(params.parse_rate("20.6"), "+21%")

    def test_rejects_garbage(self) -> None:
        with self.assertRaises(params.ParameterError):
            params.parse_rate("fast")

    def test_rejects_out_of_range(self) -> None:
        with self.assertRaises(params.ParameterError):
            params.parse_rate("900")
        with self.assertRaises(params.ParameterError):
            params.parse_rate("-500")

    def test_rejects_infinity_and_overflow(self) -> None:
        """`inf` / `1e400` 能过 `float()`，但 `round()` 抛 `OverflowError`。

        回归判据：这三种写法都必须变成**用户看得懂的 ParameterError**，
        不能把 `OverflowError` 冒到界面外（冻结态下就是"点了没反应"）。
        """
        for raw in ("inf", "-inf", "nan", "1e400", "1e309%"):
            with self.assertRaises(params.ParameterError):
                params.parse_rate(raw)
            with self.assertRaises(params.ParameterError):
                params.parse_volume(raw)
            with self.assertRaises(params.ParameterError):
                params.parse_pitch(raw)
        with self.assertRaises(params.ParameterError):
            params.parse_rate("infx")

    def test_error_names_the_field(self) -> None:
        try:
            params.parse_rate("nope")
        except params.ParameterError as exc:
            self.assertEqual(exc.field, "rate")
            self.assertTrue(exc.message)
        else:  # pragma: no cover - 上面必然抛
            self.fail("应当抛出 ParameterError")


class VolumePitchTests(unittest.TestCase):
    def test_volume(self) -> None:
        self.assertEqual(params.parse_volume("50"), "+50%")
        self.assertEqual(params.parse_volume("-100"), "-100%")

    def test_volume_range(self) -> None:
        with self.assertRaises(params.ParameterError):
            params.parse_volume("150")

    def test_pitch_unit(self) -> None:
        self.assertEqual(params.parse_pitch("20"), "+20Hz")
        self.assertEqual(params.parse_pitch("-10hz"), "-10Hz")
        self.assertEqual(params.parse_pitch("10 Hz"), "+10Hz")

    def test_pitch_empty(self) -> None:
        self.assertEqual(params.parse_pitch(""), "+0Hz")


class ParseAllTests(unittest.TestCase):
    def test_all_valid(self) -> None:
        self.assertEqual(params.parse_all("10", "0", "-5"), ("+10%", "+0%", "-5Hz"))

    def test_first_error_wins_and_nothing_is_used(self) -> None:
        """任何一项不合法，整组都不返回——不允许"半个参数"流到服务端。"""
        with self.assertRaises(params.ParameterError) as caught:
            params.parse_all("10", "bad", "bad")
        self.assertEqual(caught.exception.field, "volume")


class DescribeTests(unittest.TestCase):
    def test_defaults_have_no_description(self) -> None:
        self.assertIsNone(params.describe("+0%", "+0%", "+0Hz"))

    def test_lists_only_changed_fields(self) -> None:
        description = params.describe("+20%", "+0%", "-5Hz")
        self.assertIn("语速", description)
        self.assertIn("音调", description)
        self.assertNotIn("音量", description)


class FilenameSuffixTests(unittest.TestCase):
    def test_defaults_have_no_suffix(self) -> None:
        self.assertEqual(params.filename_suffix("+0%", "+0%", "+0Hz"), "")

    def test_only_changed_fields(self) -> None:
        self.assertEqual(
            params.filename_suffix("+20%", "+0%", "+0Hz"),
            "_语速+20%",
        )

    def test_all_three_in_order(self) -> None:
        self.assertEqual(
            params.filename_suffix("+20%", "+100%", "-10Hz"),
            "_语速+20%_音量+100%_音调-10Hz",
        )

    def test_voice_suffix(self) -> None:
        # 普通神经模型：去掉结尾的 Neural
        self.assertEqual(params.voice_suffix("en-US-AriaNeural"), "_en-US-Aria")
        # 多语言神经模型：去掉 MultilingualNeural，再补 -multi
        self.assertEqual(
            params.voice_suffix("en-US-EmmaMultilingualNeural"), "_en-US-Emma-multi"
        )
        # 带方言段的 locale：只裁模型名
        self.assertEqual(
            params.voice_suffix("zh-CN-liaoning-XiaobeiNeural"), "_zh-CN-liaoning-Xiaobei"
        )
        # 不认识的命名原样保留
        self.assertEqual(params.voice_suffix("en-US-Foo"), "_en-US-Foo")
        self.assertEqual(params.voice_suffix(""), "")
        self.assertEqual(params.voice_suffix("  "), "")

    def test_voice_suffix_comes_before_parameter_suffix(self) -> None:
        """用户 2026-10-18 定稿：语音后缀在参数后缀**前面**。"""
        from gui_of_edge_tts import text as text_mod

        suffix = params.voice_suffix("en-US-AriaNeural") + params.filename_suffix(
            "+20%", "+100%", "-10Hz"
        )
        name = text_mod.add_filename_suffix("标题.mp3", suffix)
        self.assertEqual(
            name,
            "标题_en-US-Aria_语速+20%_音量+100%_音调-10Hz.mp3",
        )


if __name__ == "__main__":
    unittest.main()
