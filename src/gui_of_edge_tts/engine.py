"""合成引擎：把一次"文本 → mp3 + srt"的过程包成一个可取消的调用。

这个模块**不碰界面**，它只通过 ``on_progress`` 回调报告发生了什么，
所以"生成到一半被取消会留下什么"这类问题可以脱离窗口单独测。

两条硬规矩：

1. **先写临时文件，成功了再改名。** 失败或取消时删掉临时文件——
   用户不该在输出目录里看到一个播不出来的半截 mp3。
2. **任何会导致失败的校验都发生在写文件之前**（归档 `DevAesthetics` 第 15.3 节）。
"""

import asyncio
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from .lang import L, is_chinese
from .subtitles import Cue, SubtitleBuilder, compose

# 上游用 CBR 48 kbps 的 mp3（见 edge-tts constants），因此进度可以用
# "已收字节数"直接换算成"已生成多久"，不需要猜。
MP3_BYTES_PER_MS = 48_000 / 8 / 1000


class SynthesisCancelled(Exception):
    """用户在生成过程中点了取消。"""


class SynthesisError(Exception):
    """合成失败。``message`` 已经是给用户看的话。"""


@dataclass
class Progress:
    """一次进度回调的全部信息。"""

    audio_bytes: int = 0
    boundaries: int = 0
    last_text: str = ""
    finished: bool = False

    @property
    def audio_milliseconds(self) -> int:
        return int(self.audio_bytes / MP3_BYTES_PER_MS)


@dataclass
class SynthesisResult:
    """一次成功合成之后的事实。"""

    audio_path: str
    subtitle_path: Optional[str]
    audio_bytes: int
    cue_count: int
    elapsed_seconds: float
    cues: List[Cue] = field(default_factory=list)

    @property
    def subtitle_written(self) -> bool:
        return bool(self.subtitle_path)


def srt_path_for(audio_path: str) -> str:
    """mp3 旁边的同名 srt。

    用 ``with_suffix`` 而不是 ``replace(".mp3", ".srt")``：后者会把路径里
    任何一处 ``.mp3`` 都换掉（比如 ``我的.mp3 备份/song.mp3``），
    也会在扩展名不是小写时漏掉。
    """
    return str(Path(audio_path).with_suffix(".srt"))


def is_cancelled(cancel) -> bool:
    """``threading.Event`` 与 ``asyncio.Event`` 的 ``is_set()`` 是同一个名字，
    但**它们不通用**（一个可以跨线程 set，另一个只能在事件循环里）。

    界面侧用的是 ``threading.Event``：用户在窗口里点取消，而循环跑在后台
    线程里。这里只要求"有个 ``is_set()`` 能问"，两种都收。
    """
    return cancel is not None and bool(cancel.is_set())


async def _run(
    text: str,
    voice: str,
    audio_path: str,
    subtitle_path: str,
    rate: str,
    volume: str,
    pitch: str,
    proxy: Optional[str],
    cancel,
    on_progress: Optional[Callable[[Progress], None]],
    boundary: str,
) -> SynthesisResult:
    import edge_tts  # pylint: disable=import-outside-toplevel

    started = time.monotonic()
    builder = SubtitleBuilder()
    progress = Progress()
    audio_path_obj = Path(audio_path)
    temp_path = audio_path_obj.with_name(f".{audio_path_obj.name}.part")

    # **取消要在这里就查一次**：等到 stream() 跑起来再查，连接已经建立了，
    # 取消反而变成"先连一次网再丢弃"。
    if is_cancelled(cancel):
        raise SynthesisCancelled()

    communicate = edge_tts.Communicate(
        text,
        voice,
        rate=rate,
        volume=volume,
        pitch=pitch,
        boundary=boundary,
        proxy=proxy,
    )

    # 显式接住异步生成器：**取消/失败时要在事件循环还活着的时候把它 aclose**，
    # 否则它会被留到 loop.close() 那一刻才回收，报一句
    # "Task was destroyed but it is pending"——那是一句没人看得懂的噪音，
    # 而它每次都出现在"用户刚点了取消"之后。
    stream = communicate.stream()
    try:
        with open(temp_path, "wb") as sink:
            async for chunk in stream:
                if is_cancelled(cancel):
                    raise SynthesisCancelled()
                kind = chunk.get("type")
                if kind == "audio":
                    data = chunk.get("data") or b""
                    sink.write(data)
                    progress.audio_bytes += len(data)
                    if on_progress is not None:
                        on_progress(progress)
                elif kind in ("WordBoundary", "SentenceBoundary"):
                    builder.feed({**chunk, "type": "WordBoundary"})
                    progress.boundaries += 1
                    progress.last_text = str(chunk.get("text", ""))
                    if on_progress is not None:
                        on_progress(progress)
            sink.flush()
            os.fsync(sink.fileno())
    except SynthesisCancelled:
        _discard(temp_path)
        raise
    except BaseException:
        _discard(temp_path)
        raise
    finally:
        await _aclose(stream)

    if progress.audio_bytes == 0:
        _discard(temp_path)
        raise SynthesisError(
            L(
                "服务端没有返回音频。常见原因：网络不通、文本是空白，"
                "或所选语音已被上游下线。",
                "The server returned no audio. Check the network; the selected "
                "voice may also have been retired upstream.",
            )
        )

    os.replace(temp_path, audio_path)

    cues = builder.cues()
    written_srt: Optional[str] = None
    if cues:
        body = compose(cues)
        if body.strip():
            Path(subtitle_path).write_text(body, encoding="utf-8")
            written_srt = subtitle_path

    progress.finished = True
    if on_progress is not None:
        on_progress(progress)

    return SynthesisResult(
        audio_path=audio_path,
        subtitle_path=written_srt,
        audio_bytes=progress.audio_bytes,
        cue_count=len(cues),
        elapsed_seconds=time.monotonic() - started,
        cues=cues,
    )


def _discard(path: Path) -> None:
    try:
        if path.exists():
            path.unlink()
    except OSError:
        pass


async def _aclose(stream) -> None:
    """尽力关掉异步生成器；关不掉也不该让生成流程失败。"""
    closer = getattr(stream, "aclose", None)
    if closer is None:
        return
    try:
        await closer()
    except (RuntimeError, StopAsyncIteration):
        pass
    except Exception:  # noqa: BLE001 - 上游可能在关闭时抛任意东西
        pass


def synthesize(
    text: str,
    voice: str,
    audio_path: str,
    rate: str = "+0%",
    volume: str = "+0%",
    pitch: str = "+0Hz",
    proxy: Optional[str] = None,
    cancel=None,
    on_progress: Optional[Callable[[Progress], None]] = None,
    boundary: str = "WordBoundary",
) -> SynthesisResult:
    """在当前线程里跑完一次合成（界面把它放在后台线程调用）。

    ``boundary`` 用 ``WordBoundary``：字幕要按词对齐，句级粒度做不出
    5 个词一块的字幕。
    """
    if not text.strip():
        raise SynthesisError(L("没有可合成的文本。", "There is no text to synthesize."))
    if not voice.strip():
        raise SynthesisError(L("没有选择语音。", "No voice is selected."))

    subtitle_path = srt_path_for(audio_path)
    loop = asyncio.new_event_loop()
    try:
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(
            _run(
                text=text,
                voice=voice,
                audio_path=audio_path,
                subtitle_path=subtitle_path,
                rate=rate,
                volume=volume,
                pitch=pitch,
                proxy=proxy,
                cancel=cancel,
                on_progress=on_progress,
                boundary=boundary,
            )
        )
    except SynthesisCancelled:
        raise
    except SynthesisError:
        raise
    except Exception as exc:  # noqa: BLE001 - 统一转成用户看得懂的话
        raise SynthesisError(_humanize(exc)) from exc
    finally:
        try:
            loop.close()
        except Exception:  # noqa: BLE001 - 关不掉也不该让界面崩
            pass


def _humanize(exc: BaseException) -> str:
    """把上游异常翻译成用户能据以行动的一句话。"""
    name = type(exc).__name__
    text = str(exc).strip() or name
    lowered = text.lower()
    if "no audio was received" in lowered or name == "NoAudioReceived":
        return L(
            "服务端没有返回音频。请检查网络连接；"
            "如果网络正常，可能是所选语音已被上游下线，换一个语音再试。",
            "The server returned no audio. Check the network; if it is fine, "
            "the selected voice may have been retired upstream — try another voice.",
        )
    if "403" in lowered or "forbidden" in lowered:
        return L(
            "服务端拒绝了这次请求（403）。通常是网络环境或代理的问题，稍后重试。",
            "The server rejected the request (403). This is usually a network or "
            "proxy issue; try again later.",
        )
    if "timeout" in lowered or "timed out" in lowered:
        return L(
            "连接服务端超时。请检查网络或代理设置，然后重试。",
            "Timed out connecting to the server. Check the network or proxy and retry.",
        )
    if "certificate" in lowered or "ssl" in lowered:
        return L(
            "HTTPS 证书校验失败。如果使用了代理，请检查代理设置。",
            "HTTPS certificate verification failed. If a proxy is configured, "
            "check its settings.",
        )
    if "cannot connect" in lowered or "connect" in lowered and "error" in lowered:
        return L(f"连不上服务端：{text}", f"Cannot connect to the server: {text}")
    if isinstance(exc, OSError):
        return L(f"写文件失败：{text}", f"Could not write the file: {text}")
    return f"{text}（{name}）" if is_chinese() else f"{text} ({name})"
