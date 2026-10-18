"""字幕合并规则与 SRT 输出。

合并规则是本项目自己的取舍（上游 ``SubMaker`` 一词一块），所以每一条规则
都要有能失败的用例。
"""

from __future__ import annotations

import unittest

import context  # noqa: F401  pylint: disable=unused-import
from gui_of_edge_tts import subtitles as sub


def word(index: int, text: str, offset_ms: int = 0, duration_ms: int = 400) -> sub.Word:
    return sub.Word(offset_ms=offset_ms, duration_ms=duration_ms, text=text)


def line_of_words(count: int, gap_ms: int = 500, duration_ms: int = 400):
    return [
        word(i, f"w{i}", offset_ms=i * gap_ms, duration_ms=duration_ms)
        for i in range(count)
    ]


class TimestampTests(unittest.TestCase):
    def test_zero(self) -> None:
        self.assertEqual(sub.timestamp(0), "00:00:00,000")

    def test_milliseconds(self) -> None:
        self.assertEqual(sub.timestamp(1), "00:00:00,001")
        self.assertEqual(sub.timestamp(999), "00:00:00,999")

    def test_seconds_and_minutes(self) -> None:
        self.assertEqual(sub.timestamp(61_500), "00:01:01,500")

    def test_hours(self) -> None:
        self.assertEqual(sub.timestamp(3_600_000), "01:00:00,000")

    def test_negative_clamps_to_zero(self) -> None:
        self.assertEqual(sub.timestamp(-5), "00:00:00,000")


class EventConversionTests(unittest.TestCase):
    def test_ticks_to_milliseconds(self) -> None:
        converted = sub.word_from_event(
            {"type": "WordBoundary", "offset": 10_000_000, "duration": 5_000_000, "text": "hi"}
        )
        self.assertEqual(converted.offset_ms, 1000)
        self.assertEqual(converted.duration_ms, 500)
        self.assertEqual(converted.end_ms, 1500)

    def test_text_is_stripped(self) -> None:
        converted = sub.word_from_event(
            {"type": "WordBoundary", "offset": 0, "duration": 0, "text": "  hi  "}
        )
        self.assertEqual(converted.text, "hi")


class MergeTests(unittest.TestCase):
    def test_caps_at_max_words(self) -> None:
        cues = sub.merge_words(line_of_words(6), max_words=5)
        self.assertEqual(len(cues), 2)
        self.assertEqual(len(cues[0].content.split()), 5)
        self.assertEqual(len(cues[1].content.split()), 1)

    def test_indices_are_sequential_from_one(self) -> None:
        cues = sub.merge_words(line_of_words(11), max_words=5)
        self.assertEqual([c.index for c in cues], [1, 2, 3])

    def test_sentence_ending_breaks_the_cue(self) -> None:
        words = [word(0, "Hello."), word(1, "Next"), word(2, "one", offset_ms=1000)]
        cues = sub.merge_words(words, max_words=5)
        self.assertEqual(len(cues), 2)
        self.assertEqual(cues[0].content, "Hello.")

    def test_long_gap_breaks_the_cue(self) -> None:
        words = [word(0, "a", 0), word(1, "b", 2000)]
        cues = sub.merge_words(words, max_words=5, max_gap_ms=700)
        self.assertEqual(len(cues), 2)

    def test_short_gap_does_not_break(self) -> None:
        words = [word(0, "a", 0), word(1, "b", 500)]
        cues = sub.merge_words(words, max_words=5, max_gap_ms=700)
        self.assertEqual(len(cues), 1)

    def test_empty_words_are_dropped(self) -> None:
        words = [word(0, "a"), word(1, "   "), word(2, "b", 1000)]
        cues = sub.merge_words(words)
        self.assertEqual(len(cues), 1)
        self.assertEqual(cues[0].content, "a b")

    def test_no_words_gives_no_cues(self) -> None:
        self.assertEqual(sub.merge_words([]), [])
        self.assertEqual(sub.merge_words([word(0, "")]), [])

    def test_cue_spans_from_first_start_to_last_end(self) -> None:
        cues = sub.merge_words(line_of_words(3, gap_ms=500, duration_ms=400))
        self.assertEqual(cues[0].start_ms, 0)
        self.assertEqual(cues[0].end_ms, 1400)

    def test_exactly_max_words_is_one_cue(self) -> None:
        cues = sub.merge_words(line_of_words(5), max_words=5)
        self.assertEqual(len(cues), 1)


class ComposeTests(unittest.TestCase):
    def test_standard_shape(self) -> None:
        cues = [sub.Cue(index=1, start_ms=0, end_ms=1400, content="a b c")]
        self.assertEqual(
            sub.compose(cues), "1\n00:00:00,000 --> 00:00:01,400\na b c\n"
        )

    def test_blocks_separated_by_blank_line(self) -> None:
        cues = [
            sub.Cue(index=1, start_ms=0, end_ms=400, content="a"),
            sub.Cue(index=2, start_ms=500, end_ms=900, content="b"),
        ]
        self.assertEqual(sub.compose(cues).count("\n\n"), 1)

    def test_empty_content_produces_empty_string(self) -> None:
        self.assertEqual(sub.compose([]), "")
        self.assertEqual(sub.compose([sub.Cue(1, 0, 100, "   ")]), "")

    def test_rejects_non_word_boundary_events(self) -> None:
        builder = sub.SubtitleBuilder()
        with self.assertRaises(ValueError):
            builder.feed({"type": "audio", "data": b""})


class BuilderTests(unittest.TestCase):
    def test_end_to_end(self) -> None:
        builder = sub.SubtitleBuilder(max_words=2)
        for index in range(4):
            builder.feed(
                {
                    "type": "WordBoundary",
                    "offset": index * 5_000_000,
                    "duration": 4_000_000,
                    "text": f"w{index}",
                }
            )
        self.assertEqual(len(builder), 4)
        self.assertEqual(len(builder.cues()), 2)
        body = builder.compose()
        self.assertTrue(body.startswith("1\n00:00:00,000 --> 00:00:00,900\n"))
        self.assertIn("w0 w1", body)


if __name__ == "__main__":
    unittest.main()
