"""文案长度、语言判定与路径显示格式的单元测试。"""

import unittest

import context  # noqa: F401  pylint: disable=unused-import
from gui_of_edge_tts import text as text_mod


class DescribeLengthTests(unittest.TestCase):
    def test_chinese_counts_characters(self):
        result = text_mod.describe_length("要朗读的文字")
        self.assertIn("6 字", result)

    def test_english_counts_words(self):
        result = text_mod.describe_length("hello brave new world")
        self.assertIn("4 词", result)

    def test_estimate_grows_with_length(self):
        short = text_mod.estimate_seconds("hello")
        long = text_mod.estimate_seconds("hello " * 50)
        self.assertGreater(long, short)

    def test_empty_text_is_zero(self):
        self.assertEqual(text_mod.count_words(""), 0)


class LanguageTests(unittest.TestCase):
    """语言判定：**中文标点要能决定语言**，不能只看拉丁字母的比例。

    这里踩过一个坑：比例判断跑在中文标点检查之前，于是 `"hello。"`
    被判成英文；只有标点的文本也落进英文分支。顺序反了就会错。
    """

    def test_pure_chinese(self):
        self.assertEqual(text_mod.language_of("你好世界"), "zh")

    def test_english_with_chinese_full_stop_is_chinese(self):
        self.assertEqual(text_mod.language_of("hello。"), "zh")

    def test_pure_english(self):
        self.assertEqual(text_mod.language_of("hello world"), "en")

    def test_punctuation_only_is_not_english(self):
        self.assertNotEqual(text_mod.language_of("。。。！！"), "en")

    def test_chinese_dominant_mixed_text(self):
        """中英混排、以中文为主时算中文。"""
        self.assertEqual(text_mod.language_of("这是 hello 世界"), "zh")


class DisplayPathTests(unittest.TestCase):
    r"""`display_path`：路径**显示**格式统一成 Windows 写法（反斜杠）。

    背景（用户实测："路径格式都不统一"）：同一个状态栏里两种分隔符混着出现——

        D:/Temp/02.mp3      ← 正斜杠：来自 filedialog（tkinter 一律正斜杠）
        D:\Temp\02.srt      ← 反斜杠：来自 Path 的规范化

    对用户来说这是"同一个东西有两种写法"。所以在显示层统一。

    ⚠️ 测试里的反斜杠一律用 `chr(92)` 拼，不写字面量：`r"D:\Temp\03"`
    里的 `\0` 是稳定的，但 `r"D:\Temp\sub"` 这种**在别的组合下**很容易
    写错成真的转义字符（我第一版就把 `\03` 写成了 `\x03`，
    测试"失败"得莫名其妙）。拼出来就没有这个风险。
    """

    BS = chr(92)

    def _win(self, *parts):
        return self.BS.join(parts)

    def test_forward_slashes_become_backslashes(self):
        self.assertEqual(
            text_mod.display_path("D:/Temp/02.mp3"),
            self._win("D:", "Temp", "02.mp3"),
        )

    def test_backslashes_are_untouched(self):
        already = self._win("D:", "Temp", "02.srt")
        self.assertEqual(text_mod.display_path(already), already)

    def test_mixed_input_is_normalised(self):
        mixed = "D:/Temp" + self.BS + "sub/03.mp3"
        self.assertEqual(
            text_mod.display_path(mixed),
            self._win("D:", "Temp", "sub", "03.mp3"),
        )

    def test_empty_string_passes_through(self):
        self.assertEqual(text_mod.display_path(""), "")

    def test_result_has_no_forward_slash(self):
        """判据用"结果里不含正斜杠"，比逐字符比较更贴真实意图。"""
        for raw in ("D:/Temp/a.mp3", "C:/Users/x/y/z.srt", "D:/a" + self.BS + "b/c"):
            self.assertNotIn("/", text_mod.display_path(raw))


if __name__ == "__main__":
    unittest.main()
