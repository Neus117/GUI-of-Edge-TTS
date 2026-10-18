"""文本预处理、字数统计与请求切分。"""

from __future__ import annotations

import unittest

import context  # noqa: F401  pylint: disable=unused-import
from gui_of_edge_tts import text as text_mod


class PreprocessTests(unittest.TestCase):
    def test_chinese_punctuation_becomes_halfwidth(self) -> None:
        self.assertEqual(text_mod.preprocess_text("你好，世界！"), "你好,世界!")

    def test_all_mapped_marks(self) -> None:
        source = "。？！，；：、（ ）【】《》“”‘’—…"
        result = text_mod.preprocess_text(source)
        for chinese in ("。", "？", "！", "，", "；", "：", "、", "【", "】", "《", "》", "“", "”", "…"):
            self.assertNotIn(chinese, result)

    def test_blank_lines_collapse(self) -> None:
        self.assertEqual(text_mod.preprocess_text("a\n\n\n\n\nb"), "a\n\nb")

    def test_carriage_returns_normalised(self) -> None:
        self.assertEqual(text_mod.preprocess_text("a\r\nb\rc"), "a\nb\nc")

    def test_control_characters_become_spaces(self) -> None:
        self.assertNotIn("\x0b", text_mod.preprocess_text("a\x0bb"))

    def test_surrounding_whitespace_removed(self) -> None:
        self.assertEqual(text_mod.preprocess_text("   hello   "), "hello")

    def test_empty_input(self) -> None:
        self.assertEqual(text_mod.preprocess_text(""), "")
        self.assertEqual(text_mod.preprocess_text("   \n  "), "")

    def test_idempotent(self) -> None:
        once = text_mod.preprocess_text("你好，世界！\r\n\r\n\r\nHello.")
        self.assertEqual(text_mod.preprocess_text(once), once)


class CountTests(unittest.TestCase):
    def test_english_words(self) -> None:
        self.assertEqual(text_mod.count_words("hello world foo"), 3)

    def test_contractions_count_once(self) -> None:
        self.assertEqual(text_mod.count_words("don't stop"), 2)

    def test_chinese_characters_count_individually(self) -> None:
        self.assertEqual(text_mod.count_words("你好世界"), 4)

    def test_empty(self) -> None:
        self.assertEqual(text_mod.count_words(""), 0)

    def test_mixed(self) -> None:
        # 4 个汉字 + 2 个英文词
        self.assertEqual(text_mod.count_words("你好世界 hello world"), 6)


class RequestPartsTests(unittest.TestCase):
    def test_short_text_is_one_part(self) -> None:
        self.assertEqual(text_mod.request_parts("hello"), 1)

    def test_empty_is_zero(self) -> None:
        self.assertEqual(text_mod.request_parts(""), 0)

    def test_long_text_splits(self) -> None:
        # 5000 个 ASCII 字符 = 5000 字节 > 4096
        self.assertGreater(text_mod.request_parts("a" * 5000), 1)

    def test_multibyte_counts_bytes_not_characters(self) -> None:
        # 2000 个汉字 = 6000 字节 > 4096，应按字节切分
        self.assertGreater(text_mod.request_parts("汉" * 2000), 1)


if __name__ == "__main__":
    unittest.main()
