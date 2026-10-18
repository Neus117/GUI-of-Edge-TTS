"""合成引擎中"不联网也能验"的部分。

真实的网络合成由 ``tools/e2e_smoke.py`` 跑（归档里那条"代理指标不算验证"：
**单测通过不代表用户走的那条路通**）。
"""

from __future__ import annotations

import asyncio
import sys
import tempfile
import threading
import types
import unittest
from pathlib import Path

import context  # noqa: F401  pylint: disable=unused-import
from gui_of_edge_tts import engine


class SrtPathTests(unittest.TestCase):
    def test_plain_name(self) -> None:
        self.assertEqual(engine.srt_path_for(r"D:\a\speech.mp3"), r"D:\a\speech.srt")

    def test_uppercase_extension(self) -> None:
        self.assertEqual(engine.srt_path_for(r"D:\a\Speech.MP3"), r"D:\a\Speech.srt")

    def test_directory_containing_dot_mp3_is_not_touched(self) -> None:
        """``replace('.mp3', '.srt')`` 会把路径里的目录名也换掉——这里必须不换。"""
        self.assertEqual(
            engine.srt_path_for(r"D:\my.mp3 backup\speech.mp3"),
            r"D:\my.mp3 backup\speech.srt",
        )

    def test_no_extension_gets_one(self) -> None:
        self.assertEqual(engine.srt_path_for(r"D:\a\speech"), r"D:\a\speech.srt")


class ValidationTests(unittest.TestCase):
    def test_empty_text_is_rejected_before_anything_else(self) -> None:
        with self.assertRaises(engine.SynthesisError):
            engine.synthesize("   ", "en-US-AriaNeural", r"D:\nope\a.mp3")

    def test_empty_voice_is_rejected(self) -> None:
        with self.assertRaises(engine.SynthesisError):
            engine.synthesize("hello", "   ", r"D:\nope\a.mp3")

    def test_validation_happens_before_the_output_path_is_touched(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "sub" / "out.mp3"
            with self.assertRaises(engine.SynthesisError):
                engine.synthesize("", "en-US-AriaNeural", str(target))
            self.assertFalse(target.exists())


class CancelTests(unittest.TestCase):
    def test_preset_cancel_leaves_no_files(self) -> None:
        """取消的判据是**输出目录里什么都没留下**，不是"函数抛了异常"。"""
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "out.mp3"
            cancel = asyncio.Event()
            cancel.set()
            with self.assertRaises(engine.SynthesisCancelled):
                engine.synthesize(
                    "hello world",
                    "en-US-AriaNeural",
                    str(target),
                    cancel=cancel,
                )
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_threading_event_is_not_an_asyncio_event(self) -> None:
        """界面侧用的是 ``threading.Event``；引擎要求 ``asyncio.Event``。

        这条用例把这个边界写下来：两者不通用，混用会在生成中期才发现。
        """
        self.assertFalse(hasattr(threading.Event(), "is_set_asyncio_only"))
        self.assertTrue(hasattr(asyncio.Event(), "set"))


class HumanizeTests(unittest.TestCase):
    def test_no_audio_message_explains_what_to_do(self) -> None:
        message = engine._humanize(RuntimeError("No audio was received."))  # pylint: disable=protected-access
        self.assertIn("网络", message)
        self.assertIn("语音", message)

    def test_403_is_explained(self) -> None:
        message = engine._humanize(RuntimeError("403, message='Forbidden'"))  # pylint: disable=protected-access
        self.assertIn("403", message)

    def test_oserror_is_about_writing_files(self) -> None:
        # 带文件名的 OSError 才是"写文件失败"（open/write/os.replace 都会带）
        error = OSError(28, "No space left on device", r"D:\out\speech.mp3")
        message = engine._humanize(error)  # pylint: disable=protected-access
        self.assertIn("文件", message)

    def test_network_oserror_is_not_reported_as_a_file_error(self) -> None:
        """`ConnectionResetError` 也是 OSError，但它不是写文件失败。

        回归判据：报错里**不能**出现"文件"——否则用户会去查磁盘和权限，
        而他真正该查的是网络/代理。
        """
        for error in (
            ConnectionResetError(10054, "Connection reset by peer"),
            OSError(10051, "Network is unreachable"),
        ):
            message = engine._humanize(error)  # pylint: disable=protected-access
            self.assertNotIn("文件", message)

    def test_unknown_error_keeps_the_type_name(self) -> None:
        class WeirdError(Exception):
            pass

        message = engine._humanize(WeirdError("boom"))  # pylint: disable=protected-access
        self.assertIn("WeirdError", message)


class FakeCommunicate:
    """假的 ``edge_tts.Communicate``：不联网，行为可编排。

    **它替换的是上游对象，不是被测代码**——所以这里验的是"我们的循环与
    收尾按预期工作"，而不是"上游能连通"。后者由 e2e 冒烟脚本负责。
    """

    def __init__(self, chunks, script) -> None:
        self._chunks = chunks
        self._script = script
        self.calls: list = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self

    async def stream(self):
        for chunk in self._chunks:
            if callable(chunk):
                chunk = chunk(self._script)
            if chunk is None:
                return
            yield chunk


class SynthesisFlowTests(unittest.TestCase):
    """走一遍引擎的完整流程，用假的上游。"""

    def setUp(self) -> None:
        self._saved = sys.modules.get("edge_tts")

    def tearDown(self) -> None:
        if self._saved is None:
            sys.modules.pop("edge_tts", None)
        else:
            sys.modules["edge_tts"] = self._saved

    def _install(self, chunks, script=None):
        script = script if script is not None else {}
        fake = types.ModuleType("edge_tts")
        fake.Communicate = FakeCommunicate(chunks, script)  # type: ignore[attr-defined]
        sys.modules["edge_tts"] = fake
        return fake.Communicate  # type: ignore[attr-defined]

    def test_success_writes_audio_and_subtitles(self) -> None:
        def boundary(index):
            return {
                "type": "WordBoundary",
                "offset": index * 5_000_000,
                "duration": 4_000_000,
                "text": f"w{index}",
            }

        chunks = [{"type": "audio", "data": b"x" * 6000}]
        chunks += [boundary(i) for i in range(6)]
        chunks.append({"type": "audio", "data": b"y" * 600})
        communicate = self._install(chunks)

        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "out.mp3"
            seen = []
            result = engine.synthesize(
                "hello world",
                "en-US-AriaNeural",
                str(target),
                on_progress=seen.append,
            )
            self.assertTrue(target.exists())
            self.assertEqual(target.stat().st_size, 6600)
            self.assertTrue(result.subtitle_path)
            self.assertEqual(result.cue_count, 2)
            self.assertIn("w0 w1 w2 w3 w4", Path(result.subtitle_path).read_text(encoding="utf-8"))
            self.assertTrue(seen)
            self.assertTrue(seen[-1].finished)

        # 参数确实是按用户填的传下去的
        _args, kwargs = communicate.calls[0]
        self.assertEqual(kwargs["rate"], "+0%")
        self.assertEqual(kwargs["boundary"], "WordBoundary")

    def test_cancel_mid_stream_keeps_nothing(self) -> None:
        cancel = threading.Event()
        chunks = [
            {"type": "audio", "data": b"a" * 10},
            lambda _script: cancel.set() or {"type": "audio", "data": b"b" * 10},
            {"type": "audio", "data": b"c" * 10},
        ]
        self._install(chunks)

        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "out.mp3"
            with self.assertRaises(engine.SynthesisCancelled):
                engine.synthesize("hi", "en-US-AriaNeural", str(target), cancel=cancel)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_zero_audio_raises_and_cleans_up(self) -> None:
        self._install([{"type": "WordBoundary", "offset": 0, "duration": 10, "text": "hi"}])
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "out.mp3"
            with self.assertRaises(engine.SynthesisError):
                engine.synthesize("hi", "en-US-AriaNeural", str(target))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_no_word_boundaries_still_writes_audio_without_srt(self) -> None:
        self._install([{"type": "audio", "data": b"z" * 4800}])
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "out.mp3"
            result = engine.synthesize("hi", "en-US-AriaNeural", str(target))
            self.assertTrue(target.exists())
            self.assertIsNone(result.subtitle_path)
            self.assertFalse(Path(engine.srt_path_for(str(target))).exists())
            self.assertFalse(result.stale_subtitle_removed)

    def test_no_word_boundaries_removes_stale_srt(self) -> None:
        """没有词边界时，同名的旧字幕必须清掉。

        否则播放器会自动加载上一次的字幕，配到这次的新音频上——比没有字幕更糟。
        """
        self._install([{"type": "audio", "data": b"z" * 4800}])
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "out.mp3"
            stale = Path(engine.srt_path_for(str(target)))
            stale.write_text("1\n00:00:00,000 --> 00:00:01,000\nOLD\n", encoding="utf-8")
            result = engine.synthesize("hi", "en-US-AriaNeural", str(target))
            self.assertTrue(target.exists())
            self.assertFalse(stale.exists())
            self.assertTrue(result.stale_subtitle_removed)

    def test_success_leaves_no_temp_files(self) -> None:
        def boundary(index):
            return {
                "type": "WordBoundary",
                "offset": index * 5_000_000,
                "duration": 4_000_000,
                "text": f"w{index}",
            }

        self._install([{"type": "audio", "data": b"x" * 6000}, boundary(0)])
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "out.mp3"
            result = engine.synthesize("hi", "en-US-AriaNeural", str(target))
            self.assertTrue(result.subtitle_path)
            leftovers = sorted(p.name for p in Path(folder).iterdir() if p.name.endswith(".part"))
            self.assertEqual(leftovers, [])

    def test_cancel_after_last_chunk_keeps_nothing(self) -> None:
        """最后一个 chunk 之后、落盘之前点取消：不能把文件提交上去。"""
        cancel = threading.Event()

        def progress(_value):
            cancel.set()

        self._install([{"type": "audio", "data": b"a" * 6000}])
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "out.mp3"
            with self.assertRaises(engine.SynthesisCancelled):
                engine.synthesize(
                    "hi", "en-US-AriaNeural", str(target), cancel=cancel,
                    on_progress=progress,
                )
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_subtitle_write_failure_keeps_audio_and_says_where_it_is(self) -> None:
        """音频已提交、字幕提交失败：报错里必须带音频路径，且不留 .part。"""

        def boundary(index):
            return {
                "type": "WordBoundary",
                "offset": index * 5_000_000,
                "duration": 4_000_000,
                "text": f"w{index}",
            }

        self._install([{"type": "audio", "data": b"x" * 6000}, boundary(0)])
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "out.mp3"
            # 让字幕路径变成一个目录：临时文件能写，最终改名一定失败。
            Path(engine.srt_path_for(str(target))).mkdir()
            with self.assertRaises(engine.SynthesisError) as caught:
                engine.synthesize("hi", "en-US-AriaNeural", str(target))
            self.assertTrue(target.exists())
            self.assertIn("音频已保存", str(caught.exception))
            self.assertIn(str(target), str(caught.exception))
            leftovers = sorted(p.name for p in Path(folder).iterdir() if p.name.endswith(".part"))
            self.assertEqual(leftovers, [])

    def test_upstream_exception_becomes_synthesis_error_and_cleans_up(self) -> None:
        def explode(_script):
            raise RuntimeError("websocket closed")

        self._install([{"type": "audio", "data": b"a"}, explode])
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "out.mp3"
            with self.assertRaises(engine.SynthesisError):
                engine.synthesize("hi", "en-US-AriaNeural", str(target))
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_existing_file_is_not_destroyed_by_a_failed_run(self) -> None:
        """失败时**不能**动用户已有的同名文件。"""
        self._install([{"type": "audio", "data": b""}])
        with tempfile.TemporaryDirectory() as folder:
            target = Path(folder) / "out.mp3"
            target.write_bytes(b"previous good audio")
            with self.assertRaises(engine.SynthesisError):
                engine.synthesize("hi", "en-US-AriaNeural", str(target))
            self.assertEqual(target.read_bytes(), b"previous good audio")


class ProgressTests(unittest.TestCase):
    def test_bytes_convert_to_duration(self) -> None:
        progress = engine.Progress(audio_bytes=int(engine.MP3_BYTES_PER_MS * 1000))
        self.assertEqual(progress.audio_milliseconds, 1000)

    def test_zero_bytes(self) -> None:
        self.assertEqual(engine.Progress().audio_milliseconds, 0)


if __name__ == "__main__":
    unittest.main()
