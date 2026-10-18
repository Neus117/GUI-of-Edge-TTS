"""SRT 字幕：从 WordBoundary 事件合成字幕块。

**为什么不用上游的 ``edge_tts.SubMaker``**：它一个字幕块放一个词，
屏幕上会一行一个词地跳。这里按"最多 N 个词 + 不跨句 + 不跨长停顿"合并，
这是本项目自己的取舍，因此自己维护。

上游 7.3.x 起不再依赖外部 ``srt`` 包（自带 ``edge_tts.srt_composer``），
所以这里也不依赖它——时间戳格式化为标准 SRT，输出与上游 ``compose()`` 一致。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta
from typing import Iterable, List

# 一个字幕块最多放几个词（合并上限）。
MAX_WORDS_PER_CUE = 5
# 两块之间的间隔超过这个值就不合并——那多半是句间的自然停顿。
MAX_GAP_MS = 700
# 词尾出现这些字符时，本块到此为止（成句）。
SENTENCE_ENDINGS = ".!?。！？…"


@dataclass(frozen=True)
class Word:
    """一个 WordBoundary 事件。"""

    offset_ms: int
    duration_ms: int
    text: str

    @property
    def end_ms(self) -> int:
        return self.offset_ms + self.duration_ms


@dataclass(frozen=True)
class Cue:
    """一个字幕块。"""

    index: int
    start_ms: int
    end_ms: int
    content: str


def word_from_event(event: dict) -> Word:
    """把上游的 chunk 转成 :class:`Word`。

    上游的单位是 100 纳秒（tick），1 毫秒 = 10000 ticks。
    """
    offset = int(event.get("offset", 0))
    duration = int(event.get("duration", 0))
    return Word(
        offset_ms=offset // 10_000,
        duration_ms=duration // 10_000,
        text=str(event.get("text", "")).strip(),
    )


def merge_words(
    words: Iterable[Word],
    max_words: int = MAX_WORDS_PER_CUE,
    max_gap_ms: int = MAX_GAP_MS,
) -> List[Cue]:
    """把逐词事件合并成字幕块。

    规则（按优先级）：

    1. 合并不超过 ``max_words`` 个词；
    2. **不跨句**——上一个词的结尾是 ``. ! ?`` 之类的收尾标点时就断开；
    3. **不跨长停顿**——两块之间的间隔超过 ``max_gap_ms`` 就断开；
    4. 空词的边界事件被丢弃（有的语言会发出来）。
    """
    cleaned = [w for w in words if w.text]
    if not cleaned:
        return []

    cues: List[Cue] = []
    buffer: List[Word] = []
    index = 1

    def flush() -> None:
        nonlocal index, buffer
        if not buffer:
            return
        # 有的语言会把标点单独作为一次边界事件发过来（文本是 ","），
        # 直接 join 会出现"a   ,   b"这样的多重空格。压成单空格。
        content = " ".join(w.text for w in buffer).strip()
        content = " ".join(content.split())
        if not content:
            buffer = []
            return
        cues.append(
            Cue(
                index=index,
                start_ms=buffer[0].offset_ms,
                end_ms=max(w.end_ms for w in buffer),
                content=content,
            )
        )
        index += 1
        buffer = []

    for word in cleaned:
        if buffer:
            gap = word.offset_ms - buffer[-1].end_ms
            if gap > max_gap_ms:
                flush()
        buffer.append(word)

        ends_sentence = bool(word.text) and word.text[-1] in SENTENCE_ENDINGS
        if len(buffer) >= max_words or ends_sentence:
            flush()

    flush()
    return cues


def timestamp(milliseconds: int) -> str:
    """毫秒 → ``HH:MM:SS,mmm``。"""
    if milliseconds < 0:
        milliseconds = 0
    delta = timedelta(milliseconds=milliseconds)
    total_seconds = int(delta.total_seconds())
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    millis = milliseconds % 1000
    return f"{hours:02d}:{minutes:02d}:{seconds:02d},{millis:03d}"


def compose(cues: Iterable[Cue]) -> str:
    """生成 SRT 正文。

    * 空内容返回空字符串，**不返回一个只有序号和箭头的空文件**——
      空文件会让播放器显示一条无意义的字幕；
    * 块之间空一行；整篇**不以多余的换行结尾**（上游的 ``compose()`` 会多
      一个空行，纯属观感差异，`tests/test_srt_parity.py` 按"块"而不是按
      "字节"对比，把这一处差异显式记下来）。
    """
    blocks = []
    for cue in cues:
        content = cue.content.strip()
        if not content:
            continue
        blocks.append(
            f"{cue.index}\n{timestamp(cue.start_ms)} --> {timestamp(cue.end_ms)}\n{content}\n"
        )
    return "\n".join(blocks)


class SubtitleBuilder:
    """收集 WordBoundary 事件，最后一次性合成 SRT。

    与上游 ``SubMaker`` 的区别：``feed`` 只收事件，``compose`` 才做合并，
    所以合并规则可以单独测。
    """

    def __init__(self, max_words: int = MAX_WORDS_PER_CUE) -> None:
        self.words: List[Word] = []
        self.max_words = max_words

    def feed(self, event: dict) -> None:
        if event.get("type") != "WordBoundary":
            raise ValueError("只接受 WordBoundary 事件")
        self.words.append(word_from_event(event))

    def cues(self) -> List[Cue]:
        return merge_words(self.words, max_words=self.max_words)

    def compose(self) -> str:
        return compose(self.cues())

    def __len__(self) -> int:
        return len(self.words)
