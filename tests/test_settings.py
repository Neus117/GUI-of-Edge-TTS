"""设置的读写、容错与目录解析。"""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path

import context  # noqa: F401  pylint: disable=unused-import
from gui_of_edge_tts import settings as settings_mod


class RoundTripTests(unittest.TestCase):
    def setUp(self) -> None:
        self._folder = tempfile.TemporaryDirectory()
        self.path = Path(self._folder.name) / "settings.json"

    def tearDown(self) -> None:
        self._folder.cleanup()

    def test_defaults_are_valid(self) -> None:
        defaults = settings_mod.Settings()
        defaults.validate()
        self.assertEqual(defaults.theme, settings_mod.THEME_SYSTEM)
        self.assertTrue(defaults.output_dir)

    def test_save_then_load(self) -> None:
        original = settings_mod.Settings(voice="zh-CN-XiaoxiaoNeural", rate="20")
        original.save(self.path)
        loaded = settings_mod.Settings.load(self.path)
        self.assertEqual(loaded.voice, "zh-CN-XiaoxiaoNeural")
        self.assertEqual(loaded.rate, "20")

    def test_missing_file_gives_defaults(self) -> None:
        loaded = settings_mod.Settings.load(Path(self._folder.name) / "nope.json")
        self.assertEqual(loaded.voice, "")

    def test_unknown_keys_are_ignored(self) -> None:
        self.path.write_text(
            json.dumps({"voice": "en-US-AriaNeural", "legacy_option": 1}), encoding="utf-8"
        )
        loaded = settings_mod.Settings.load(self.path)
        self.assertEqual(loaded.voice, "en-US-AriaNeural")
        self.assertFalse(hasattr(loaded, "legacy_option"))

    def test_broken_json_degrades_and_keeps_a_copy(self) -> None:
        self.path.write_text("{ not json", encoding="utf-8")
        loaded = settings_mod.Settings.load(self.path)
        self.assertEqual(loaded.voice, "")
        self.assertTrue(self.path.with_suffix(".json.bad").exists())

    def test_non_dict_json_degrades(self) -> None:
        self.path.write_text("[1, 2, 3]", encoding="utf-8")
        self.assertEqual(settings_mod.Settings.load(self.path).voice, "")

    def test_bad_theme_falls_back_to_system(self) -> None:
        self.path.write_text(json.dumps({"theme": "neon"}), encoding="utf-8")
        self.assertEqual(settings_mod.Settings.load(self.path).theme, settings_mod.THEME_SYSTEM)

    def test_numeric_rate_is_stringified(self) -> None:
        self.path.write_text(json.dumps({"rate": 20}), encoding="utf-8")
        self.assertEqual(settings_mod.Settings.load(self.path).rate, "20")

    def test_save_is_atomic_leaving_no_temp_files(self) -> None:
        for _ in range(3):
            settings_mod.Settings().save(self.path)
        leftovers = [p.name for p in Path(self._folder.name).iterdir() if p.name.startswith(".settings-")]
        self.assertEqual(leftovers, [])

    def test_save_creates_missing_directory(self) -> None:
        nested = Path(self._folder.name) / "a" / "b" / "settings.json"
        settings_mod.Settings().save(nested)
        self.assertTrue(nested.exists())


class OutputDirTests(unittest.TestCase):
    def test_existing_directory_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config = settings_mod.Settings(output_dir=folder)
            self.assertEqual(config.resolved_output_dir(), folder)

    def test_removed_directory_falls_back(self) -> None:
        config = settings_mod.Settings(output_dir=str(Path(tempfile.gettempdir()) / "definitely-gone-xyz"))
        self.assertTrue(Path(config.resolved_output_dir()).is_dir())

    def test_blank_output_dir_falls_back(self) -> None:
        config = settings_mod.Settings(output_dir="")
        config.validate()
        self.assertTrue(Path(config.resolved_output_dir()).is_dir())


class ProxyTests(unittest.TestCase):
    def test_blank_proxy_is_none(self) -> None:
        self.assertIsNone(settings_mod.Settings(proxy="  ").proxy_or_none())

    def test_proxy_is_trimmed(self) -> None:
        self.assertEqual(
            settings_mod.Settings(proxy=" http://127.0.0.1:7897 ").proxy_or_none(),
            "http://127.0.0.1:7897",
        )

    def test_proxy_without_scheme_gets_http(self) -> None:
        self.assertEqual(
            settings_mod.Settings(proxy="127.0.0.1:7897").proxy_or_none(),
            "http://127.0.0.1:7897",
        )


class ConfigPathTests(unittest.TestCase):
    def test_path_ends_with_settings_json(self) -> None:
        self.assertEqual(settings_mod.config_path().name, "settings.json")

    def test_honours_appdata(self) -> None:
        previous = os.environ.get("APPDATA")
        os.environ["APPDATA"] = r"C:\fake"
        try:
            self.assertEqual(
                str(settings_mod.config_dir()), os.path.join(r"C:\fake", settings_mod.APP_DIR_NAME)
            )
        finally:
            if previous is None:
                os.environ.pop("APPDATA", None)
            else:
                os.environ["APPDATA"] = previous


if __name__ == "__main__":
    unittest.main()
