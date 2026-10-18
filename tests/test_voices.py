"""语音目录：排序、默认项、搜索语法、兜底清单。"""

from __future__ import annotations

import unittest

import context  # noqa: F401  pylint: disable=unused-import
from gui_of_edge_tts import voices as voices_mod


RAW = [
    {
        "Name": "Microsoft Server Speech Text to Speech Voice (zh-CN, XiaoxiaoNeural)",
        "ShortName": "zh-CN-XiaoxiaoNeural",
        "Gender": "Female",
        "Locale": "zh-CN",
    },
    {
        "Name": "Microsoft Server Speech Text to Speech Voice (en-US, AriaNeural)",
        "ShortName": "en-US-AriaNeural",
        "Gender": "Female",
        "Locale": "en-US",
    },
    {
        "Name": "Microsoft Server Speech Text to Speech Voice (en-US, GuyNeural)",
        "ShortName": "en-US-GuyNeural",
        "Gender": "Male",
        "Locale": "en-US",
    },
    {
        "Name": "Microsoft Server Speech Text to Speech Voice (ja-JP, NanamiNeural)",
        "ShortName": "ja-JP-NanamiNeural",
        "Gender": "Female",
        "Locale": "ja-JP",
    },
]


class BuildCatalogTests(unittest.TestCase):
    def test_preferred_locales_come_first(self) -> None:
        catalog = voices_mod.build_catalog(RAW)
        self.assertEqual(catalog[0].short_name, "en-US-AriaNeural")
        self.assertEqual(catalog[-1].short_name, "ja-JP-NanamiNeural")

    def test_zh_dialects_stay_in_chinese_group(self) -> None:
        """zh-CN-liaoning / zh-CN-shaanxi 不能被当成"其他语言"排到末尾。"""
        raw = [
            {"ShortName": "vi-VN-NamMinhNeural", "Locale": "vi-VN", "Gender": "Male"},
            {"ShortName": "zu-ZA-ThandoNeural", "Locale": "zu-ZA", "Gender": "Female"},
            {
                "ShortName": "zh-CN-liaoning-XiaobeiNeural",
                "Locale": "zh-CN-liaoning",
                "Gender": "Female",
            },
            {
                "ShortName": "zh-CN-shaanxi-XiaoniNeural",
                "Locale": "zh-CN-shaanxi",
                "Gender": "Female",
            },
            {
                "ShortName": "zh-CN-XiaoxiaoNeural",
                "Locale": "zh-CN",
                "Gender": "Female",
            },
        ]
        names = [voice.short_name for voice in voices_mod.build_catalog(raw)]
        dialect_positions = [
            names.index("zh-CN-liaoning-XiaobeiNeural"),
            names.index("zh-CN-shaanxi-XiaoniNeural"),
        ]
        self.assertLess(
            dialect_positions[0], names.index("vi-VN-NamMinhNeural")
        )
        self.assertLess(
            dialect_positions[1], names.index("vi-VN-NamMinhNeural")
        )
        self.assertLess(
            names.index("zh-CN-XiaoxiaoNeural"), dialect_positions[0]
        )

    def test_duplicates_are_dropped(self) -> None:
        catalog = voices_mod.build_catalog(RAW + RAW)
        self.assertEqual(len(catalog), 4)

    def test_entries_without_short_name_are_dropped(self) -> None:
        catalog = voices_mod.build_catalog([{"Name": "x"}] + RAW)
        self.assertEqual(len(catalog), 4)

    def test_display_contains_short_name_and_gender(self) -> None:
        voice = voices_mod.build_catalog(RAW)[0]
        self.assertIn("en-US-AriaNeural", voice.display)
        self.assertIn("女", voice.display)

    def test_language_group(self) -> None:
        self.assertEqual(voices_mod.build_catalog(RAW)[0].language_group, "en")

    def test_chat_name_strips_neural_suffix(self) -> None:
        catalog = voices_mod.build_catalog(
            [
                {
                    "ShortName": "en-US-AndrewMultilingualNeural",
                    "Gender": "Male",
                    "Locale": "en-US",
                }
            ]
        )
        self.assertEqual(catalog[0].chat_name, "Andrew")


class CatalogQueryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.catalog = voices_mod.VoiceCatalog(voices_mod.build_catalog(RAW))

    def test_default_prefers_requested_voice(self) -> None:
        self.assertEqual(
            self.catalog.default_voice("ja-JP-NanamiNeural").short_name, "ja-JP-NanamiNeural"
        )

    def test_default_prefers_en_us(self) -> None:
        self.assertEqual(self.catalog.default_voice().language, "en-US")

    def test_default_ignores_unknown_request(self) -> None:
        self.assertEqual(self.catalog.default_voice("xx-XX-GoneNeural").language, "en-US")

    def test_find(self) -> None:
        self.assertIsNotNone(self.catalog.find("en-US-GuyNeural"))
        self.assertIsNone(self.catalog.find("en-US-NobodyNeural"))

    def test_empty_query_returns_everything(self) -> None:
        self.assertEqual(len(self.catalog.search("")), 4)
        self.assertEqual(len(self.catalog.search("   ")), 4)

    def test_search_by_language_code(self) -> None:
        result = self.catalog.search("en-US")
        self.assertEqual({v.short_name for v in result}, {"en-US-AriaNeural", "en-US-GuyNeural"})

    def test_search_by_language_prefix(self) -> None:
        self.assertEqual(len(self.catalog.search("zh")), 1)

    def test_search_by_gender_chinese(self) -> None:
        self.assertEqual([v.short_name for v in self.catalog.search("男")], ["en-US-GuyNeural"])

    def test_search_by_gender_english(self) -> None:
        self.assertEqual(len(self.catalog.search("female")), 3)

    def test_search_by_chinese_language_word(self) -> None:
        self.assertEqual(len(self.catalog.search("日语")), 1)

    def test_search_by_name(self) -> None:
        self.assertEqual(len(self.catalog.search("aria")), 1)

    def test_combined_tokens_are_anded(self) -> None:
        self.assertEqual(
            [v.short_name for v in self.catalog.search("en-US 女")], ["en-US-AriaNeural"]
        )

    def test_no_match_returns_empty(self) -> None:
        self.assertEqual(self.catalog.search("klingon"), [])

    def test_limit_is_respected(self) -> None:
        self.assertLessEqual(len(self.catalog.search("", limit=2)), 2)


class FallbackTests(unittest.TestCase):
    def test_fallback_is_not_marked_loaded(self) -> None:
        catalog = voices_mod.VoiceCatalog.fallback()
        self.assertFalse(catalog.loaded)
        self.assertGreaterEqual(len(catalog), 4)

    def test_fallback_has_default(self) -> None:
        self.assertIsNotNone(voices_mod.VoiceCatalog.fallback().default_voice())

    def test_empty_catalog_has_no_default(self) -> None:
        self.assertIsNone(voices_mod.VoiceCatalog.empty().default_voice())


if __name__ == "__main__":
    unittest.main()
