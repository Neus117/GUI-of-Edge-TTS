"""默认文件名的"提取式标题"。"""

from __future__ import annotations

import unittest

import context  # noqa: F401  pylint: disable=unused-import
from gui_of_edge_tts import text as text_mod


class SuggestTitleTests(unittest.TestCase):
    ENGLISH_NEWS = (
        "President Xi Jinping arrived in Washington on Wednesday for a state "
        "visit to the United States at the invitation of US President Donald "
        "Trump. The visit comes about four months after Trump's state visit "
        "to China in May."
    )
    CHINESE_NEWS = (
        "国家主席习近平周三抵达华盛顿，开始对美国进行国事访问。"
        "此次访问是应美国总统特朗普邀请进行的。"
    )

    def test_english_news_uses_proper_nouns(self) -> None:
        title = text_mod.suggest_title(self.ENGLISH_NEWS)
        self.assertIn("Xi", title)
        self.assertIn("Washington", title)
        # 星期这类不进入标题；称谓保留也可以（整句裁出来的自然标题）
        self.assertNotIn("Wednesday", title)
        self.assertLessEqual(len(title), text_mod.TITLE_MAX_LATIN)

    def test_chinese_news_drops_title_and_date(self) -> None:
        title = text_mod.suggest_title(self.CHINESE_NEWS)
        self.assertIn("习近平", title)
        self.assertIn("华盛顿", title)
        self.assertNotIn("国家主席", title)
        self.assertNotIn("周三", title)
        self.assertLessEqual(len(title), text_mod.TITLE_MAX_CJK)

    def test_chinese_generic_uses_first_sentence(self) -> None:
        title = text_mod.suggest_title(
            "人工智能正在改变教育行业的方方面面。越来越多的学校开始使用智能辅导系统。"
        )
        self.assertIn("人工智能", title)
        self.assertNotIn("。", title)

    def test_english_lowercase_still_gets_phrase(self) -> None:
        title = text_mod.suggest_title(
            "we are going to talk about artificial intelligence and education in this article."
        )
        lowered = title.lower()
        self.assertIn("artificial intelligence", lowered)
        self.assertNotIn("article", lowered)

    def test_empty_has_no_title(self) -> None:
        self.assertEqual(text_mod.suggest_title(""), "")
        self.assertEqual(text_mod.suggest_title("   \n\t  "), "")

    def test_no_punctuation_is_truncated(self) -> None:
        title = text_mod.suggest_title("人工智能正在改变教育行业的方方面面越来越多的学校")
        self.assertTrue(title)
        self.assertLessEqual(len(title), text_mod.TITLE_MAX_CJK)

    def test_japanese_uses_first_sentence_fallback(self) -> None:
        # 假名不能被中文路径里的"去标点"删掉
        title = text_mod.suggest_title("こんにちは、世界。今日はいい天気です。")
        self.assertIn("こんにちは", title)

    def test_decimal_point_is_not_a_sentence_break(self) -> None:
        """5.4% 不能被切成 "5." + "4%"——用户实测标题变成 "4% year on year"。"""
        title = text_mod.suggest_title(
            "Sales were up 5.4% year on year in the first quarter."
        )
        self.assertIn("5.4%", title)
        name = text_mod.suggest_filename(
            "Sales were up 5.4% year on year in the first quarter."
        )
        self.assertIn("5.4%", name)
        self.assertNotIn("5 4%", name)

    def test_parameter_suffix_goes_before_extension(self) -> None:
        self.assertEqual(
            text_mod.add_filename_suffix("A title.mp3", "_语速+20%"),
            "A title_语速+20%.mp3",
        )
        self.assertEqual(
            text_mod.add_filename_suffix("A title.mp3", ""),
            "A title.mp3",
        )

    def test_english_title_does_not_end_with_function_word(self) -> None:
        title = text_mod.suggest_title(
            "The quick brown fox jumps over the lazy dog. This sentence contains every letter."
        )
        self.assertNotIn(
            title.split()[-1].lower(),
            {"over", "the", "of", "in", "on", "and", "with", "for", "to"},
        )

    def test_english_long_article_skips_background_sentence(self) -> None:
        title = text_mod.suggest_title(
            "In recent years, artificial intelligence has spread quickly. "
            "Many companies are investing heavily in large language models. "
            "The real question is not whether AI will replace teachers, but how "
            "it will change their role in the classroom."
        )
        self.assertNotIn("Recent", title)
        self.assertIn("Teachers", title)

    def test_chinese_long_article_skips_background_sentence(self) -> None:
        title = text_mod.suggest_title(
            "近年来，随着大模型技术的快速发展，人工智能在教育领域的应用越来越广泛。"
            "很多学校开始尝试用智能辅导系统帮助学生个性化学习。"
            "专家认为，人工智能不会取代教师，但会改变教师的角色。"
        )
        self.assertNotIn("近年来", title)
        self.assertIn("教师", title)


class SuggestFilenameTests(unittest.TestCase):
    def test_returns_mp3(self) -> None:
        name = text_mod.suggest_filename("Hello world, this is a test.")
        self.assertTrue(name.endswith(".mp3"))
        self.assertTrue(name.lower().startswith("hello"))

    def test_illegal_characters_removed(self) -> None:
        name = text_mod.suggest_filename('He said "a/b:c*?" on Wednesday.')
        for illegal in '\\/:*?"<>|':
            self.assertNotIn(illegal, name)

    def test_empty_returns_empty(self) -> None:
        self.assertEqual(text_mod.suggest_filename(""), "")

    def test_windows_reserved_name_is_escaped(self) -> None:
        # 单靠内容很难构造出 "con"，直接走标题→文件名的那一步
        name = text_mod.suggest_filename("con")
        self.assertNotIn(name.lower(), {"con.mp3", "aux.mp3", "nul.mp3", "prn.mp3"})


if __name__ == "__main__":
    unittest.main()
