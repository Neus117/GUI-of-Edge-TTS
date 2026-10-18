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

    def test_utf8_bom_is_read_not_discarded(self) -> None:
        """带 BOM 的 UTF-8 是**正确**的配置，不能当成坏文件扔掉。

        回归判据：读完设置还在，而且没有产生 `.bad`。
        """
        payload = json.dumps({"voice": "zh-CN-YunxiNeural"}, ensure_ascii=False)
        self.path.write_bytes(b"\xef\xbb\xbf" + payload.encode("utf-8"))
        loaded = settings_mod.Settings.load(self.path)
        self.assertEqual(loaded.voice, "zh-CN-YunxiNeural")
        self.assertFalse(self.path.with_suffix(".json.bad").exists())

    def test_utf16_file_is_read(self) -> None:
        """PowerShell 5.1 的 `Out-File` 默认写 UTF-16LE（带 BOM）。"""
        payload = json.dumps({"voice": "en-US-AndrewNeural"})
        self.path.write_bytes(payload.encode("utf-16"))
        loaded = settings_mod.Settings.load(self.path)
        self.assertEqual(loaded.voice, "en-US-AndrewNeural")

    def test_undecodable_file_is_archived_not_lost(self) -> None:
        """既不是 UTF-8 也不是 UTF-16 的内容：留档，不原地丢掉。"""
        self.path.write_bytes(b"\x80\x81\x82\x83")
        loaded = settings_mod.Settings.load(self.path)
        self.assertEqual(loaded.voice, "")
        self.assertFalse(self.path.exists())
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

    def test_environment_overrides_are_not_persisted(self) -> None:
        """`ETTS_THEME` 是给截图/探针用的临时覆盖，不能写进用户配置。"""
        previous_theme = os.environ.get("ETTS_THEME")
        os.environ["ETTS_THEME"] = "dark"
        try:
            settings = settings_mod.Settings().with_environment_overrides()
            self.assertEqual(settings.theme, "dark")
            settings.save(self.path)
            stored = json.loads(self.path.read_text(encoding="utf-8"))
            # 运行时是 dark，落盘必须是原来的 system
            self.assertEqual(settings.theme, "dark")
            self.assertEqual(stored["theme"], settings_mod.THEME_SYSTEM)
        finally:
            if previous_theme is None:
                os.environ.pop("ETTS_THEME", None)
            else:
                os.environ["ETTS_THEME"] = previous_theme

    def test_unencodable_setting_cleans_up_temp_file(self) -> None:
        """孤立代理项写不进 UTF-8：要报错，但不能留下 `.settings-*.tmp`。"""
        settings = settings_mod.Settings()
        settings.voice = "\ud800"
        with self.assertRaises(UnicodeError):
            settings.save(self.path)
        leftovers = [
            p.name for p in Path(self._folder.name).iterdir() if p.name.startswith(".settings-")
        ]
        self.assertEqual(leftovers, [])


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
