"""界面语言：检测顺序、持久化取值与 L() 的双语并排。"""

from __future__ import annotations

import unittest

import context  # noqa: F401  pylint: disable=unused-import
from gui_of_edge_tts import lang


class LanguageTests(unittest.TestCase):
    def tearDown(self) -> None:
        lang.apply("zh")

    def test_explicit_english_and_chinese(self) -> None:
        lang.apply("en")
        self.assertFalse(lang.is_chinese())
        self.assertEqual(lang.L("中文", "English"), "English")
        self.assertEqual(lang.current_preference(), "en")
        lang.apply("zh")
        self.assertTrue(lang.is_chinese())
        self.assertEqual(lang.L("中文", "English"), "中文")

    def test_empty_preference_falls_back_to_detection(self) -> None:
        lang.apply("")
        self.assertEqual(lang.current_preference(), lang.preference(lang.is_chinese()))

    def test_invalid_preference_falls_back_to_detection(self) -> None:
        lang.apply("xx")
        self.assertEqual(lang.current_preference(), lang.preference(lang.is_chinese()))


if __name__ == "__main__":
    unittest.main()
