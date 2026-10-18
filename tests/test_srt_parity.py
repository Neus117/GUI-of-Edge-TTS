"""字幕输出与上游 ``edge_tts.srt_composer`` 的格式一致性。

这一条很重要：**格式要是悄悄变了，播放器会什么都不显示，而程序不会报错。**
判据是"两边的块逐块相同"——按块比而不是按字节比，因为上游会在整篇末尾
多写一个空行（纯观感差异，已在 ``subtitles.compose`` 的 docstring 里记下）。
"""

from __future__ import annotations

import datetime
import re
import unittest

import context  # noqa: F401  pylint: disable=unused-import
from gui_of_edge_tts import subtitles as sub

try:
    from edge_tts.srt_composer import Subtitle as UpstreamSubtitle, compose as upstream_compose

    HAVE_EDGE_TTS = True
except ImportError:  # pragma: no cover - 没装 edge-tts 时跳过
    HAVE_EDGE_TTS = False


def blocks_of(body: str) -> list:
    """把 SRT 正文拆成块，忽略末尾空行差异。"""
    return [block.strip() for block in re.split(r"\n\s*\n", body.strip()) if block.strip()]


def timedelta(milliseconds: int) -> datetime.timedelta:
    return datetime.timedelta(milliseconds=milliseconds)


@unittest.skipUnless(HAVE_EDGE_TTS, "需要安装 edge-tts")
class UpstreamParityTests(unittest.TestCase):
    def _theirs(self, items):
        return [
            UpstreamSubtitle(
                index=index,
                start=timedelta(start),
                end=timedelta(end),
                content=content,
            )
            for index, start, end, content in items
        ]

    def test_two_blocks_match_upstream(self) -> None:
        items = [
            (1, 0, 1400, "hello there"),
            (2, 1500, 2600, "second block"),
        ]
        ours = [sub.Cue(index=i, start_ms=s, end_ms=e, content=c) for i, s, e, c in items]
        self.assertEqual(blocks_of(sub.compose(ours)), blocks_of(upstream_compose(self._theirs(items))))

    def test_hour_rollover_matches_upstream(self) -> None:
        items = [(1, 3_600_000, 3_601_000, "late")]
        ours = [sub.Cue(index=i, start_ms=s, end_ms=e, content=c) for i, s, e, c in items]
        self.assertEqual(blocks_of(sub.compose(ours)), blocks_of(upstream_compose(self._theirs(items))))

    def test_many_sub_second_blocks_match_upstream(self) -> None:
        items = [(i + 1, i * 137, i * 137 + 120, f"w{i}") for i in range(12)]
        ours = [sub.Cue(index=i, start_ms=s, end_ms=e, content=c) for i, s, e, c in items]
        self.assertEqual(blocks_of(sub.compose(ours)), blocks_of(upstream_compose(self._theirs(items))))

    def test_our_timestamp_equals_upstream_timestamp(self) -> None:
        from edge_tts.srt_composer import timedelta_to_srt_timestamp

        for milliseconds in (0, 1, 999, 1000, 61_500, 3_599_999, 3_600_000, 86_399_999):
            self.assertEqual(
                sub.timestamp(milliseconds),
                timedelta_to_srt_timestamp(timedelta(milliseconds)),
                f"{milliseconds} ms",
            )


if __name__ == "__main__":
    unittest.main()
