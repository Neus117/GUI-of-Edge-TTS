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

#: 连续多久收不到数据就放弃。上游默认 60 秒——连接卡死时，用户点了"取消"
#: 也只能等到下一个 chunk 才会被看到，界面会显示"正在取消…"最长一分钟。
#: 20 秒仍然足够容忍正常的网络抖动（音频是流式的，不会 20 秒没有数据）。
RECEIVE_TIMEOUT_SECONDS = 20


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
    #: 这次没有字幕、并且**删掉了一个同名的旧 .srt**（播放器会误加载它）。
    #: 界面用它把"旧字幕已移除"说出来，而不是让用户自己发现。
    stale_subtitle_removed: bool = False

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
        # 取消只能在两个 chunk 之间被看到；上游默认 60 秒收不到数据才超时，
        # 那段时间界面会一直显示"正在取消…"。20 秒足够容忍正常抖动。
        receive_timeout=RECEIVE_TIMEOUT_SECONDS,
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

    # **提交之前再查一次取消。** 用户可能在最后一个 chunk 之后、落盘之前点取消：
    # 那时循环已经结束，不查就会把一份"用户已经不要了"的文件改名落盘，
    # 并在界面上报成功。
    if is_cancelled(cancel):
        _discard(temp_path)
        raise SynthesisCancelled()

    cues = builder.cues()
    body = compose(cues) if cues else ""
    srt_temp: Optional[Path] = None
    written_srt: Optional[str] = None
    stale_subtitle_removed = False

    # **先把字幕写进临时文件**，再提交音频：两个文件都准备好了才落盘。
    # 这样"字幕写不进去"不会留下一个孤零零的音频（旧写法是音频先 commit，
    # 字幕失败后报"生成失败"，但 mp3 已经在那儿了）。
    if body.strip():
        srt_path = Path(subtitle_path)
        srt_temp = srt_path.with_name(f".{srt_path.name}.part")
        try:
            # 用默认换行翻译（Windows 上是 CRLF），与原来的 `write_text` 一致。
            with open(srt_temp, "w", encoding="utf-8") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
        except OSError:
            _discard(temp_path)
            _discard(srt_temp)
            raise

    # 改名失败（目标被占用/没有权限）时**临时文件也要收掉**：
    # 否则输出目录里会留下一个 `.xxx.mp3.part`，用户不知道那是什么。
    try:
        os.replace(temp_path, audio_path)
    except OSError:
        _discard(temp_path)
        _discard(srt_temp)
        raise

    if srt_temp is not None:
        try:
            os.replace(srt_temp, subtitle_path)
            written_srt = subtitle_path
        except OSError as exc:
            _discard(srt_temp)
            # 音频已经在磁盘上了。**不能只说"生成失败"而不告诉用户文件在哪**。
            raise SynthesisError(
                L(
                    f"音频已保存到 {audio_path}，但字幕写入失败：{exc}",
                    f"The audio was saved to {audio_path}, but the subtitles "
                    f"could not be written: {exc}",
                )
            ) from exc
    else:
        # 这次没有字幕（上游没返回词边界）：把同名的旧 .srt 清掉。
        # 否则播放器会自动加载**上一次**的字幕，配到这次的新音频上——
        # 那比"没有字幕"更糟。只清理同名的那个文件（本程序的命名约定）。
        stale = Path(subtitle_path)
        if stale.exists():
            _discard(stale)
            stale_subtitle_removed = True

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
        stale_subtitle_removed=stale_subtitle_removed,
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
        # ⚠️ **取消时只 aclose 外层生成器还不够。** edge-tts 的 `stream()` 内部
        # 还套着一层 `async for ... in self.__stream(): yield ...`，而
        # `__stream()` 里才是 `async with aiohttp.ClientSession()`。外层被
        # aclose 之后，内层生成器要等到**垃圾回收**才被 `asyncio` 的终结器
        # 排一个 `async_generator_athrow` 任务去关闭；如果这时循环已经
        # close 了，终端里就会出现：
        #
        #   Task was destroyed but it is pending!
        #   Unclosed client session
        #   RuntimeError: Event loop is closed（ClientResponse.__del__）
        #
        # 用户实测看到了这三句（只在**取消**时出现，正常完成没有）。
        # 修法：在循环还活着的时候把剩下的异步生成器与已排队的终结任务
        # 都跑完——顺序是 `shutdown_asyncgens()` → 等挂起任务 → `close()`。
        try:
            loop.run_until_complete(loop.shutdown_asyncgens())
        except Exception:  # noqa: BLE001 - 关不上也不该让界面崩
            pass
        try:
            # 终结器任务通常只有一个（athrow），给每个最多 3 秒；
            # 真有卡死的任务时不能把"关闭"变成无限等待。
            for _ in range(3):
                pending = [task for task in asyncio.all_tasks(loop) if not task.done()]
                if not pending:
                    break
                loop.run_until_complete(asyncio.wait(pending, timeout=3.0))
        except Exception:  # noqa: BLE001
            pass
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
    if "timeout" in lowered or "timed out" in lowered or isinstance(exc, TimeoutError):
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
    if isinstance(exc, ConnectionError):
        # `ConnectionResetError` / `ConnectionAbortedError` 都是 `OSError`，
        # 但它们的意思**不是"写文件失败"**——下一支只认带文件名的 OSError。
        return L(f"连接被中断：{text}", f"The connection was interrupted: {text}")
    if isinstance(exc, OSError) and getattr(exc, "filename", None):
        # 只有**指向某个文件**的 OSError 才是写文件失败。
        # 网络层的 OSError 没有 filename，不能套这句话（否则用户会去查磁盘）。
        return L(f"写文件失败：{text}", f"Could not write the file: {text}")
    return f"{text}（{name}）" if is_chinese() else f"{text} ({name})"
