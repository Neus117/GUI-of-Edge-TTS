"""端到端冒烟：在**这个进程里**走一遍用户真实走的那条路。

由 ``--smoke`` 触发。它做的是一件单测做不到的事：
把文字填进**真实的** ``Text`` 控件、选一个**真实的**语音、调**真实的**
生成入口（只把保存对话框换成一个已知路径），然后等**真实的**事件循环
把"完成"搬回状态栏，最后检查磁盘上是不是真的出现了 mp3 与 srt。

**判据全部是磁盘上的事实与界面上的文字**——进程存活、退出码、日志没报错
都不算（归档 `01` 错误一）。

放进包里而不是只放在 `tools/` 的原因：**打包成 exe 之后还能再跑一遍**。
冻结态与源码态的环境不一样（没有控制台、Tcl/Tk 从包里加载、
依赖被裁剪过），只有真的跑一次才知道它行不行。
"""

from __future__ import annotations

import os
import time
from pathlib import Path
from typing import List, Optional

SAMPLE_TEXT = (
    "Hello, this is an end to end check of GUI of Edge TTS. "
    "The subtitles should be split into short blocks."
)
DEFAULT_TIMEOUT = 90.0

#: 把窗口停到这个坐标：对 Windows 来说它仍是"已映射窗口"（几何/事件都真实），
#: 但落在屏幕之外——冒烟跑得快、也不闪。
#: 2026-10-17 起用户允许在专用桌面开可见窗口；屏幕外只是默认的快速路径。
OFFSCREEN = -4000


def _timestamp_to_ms(stamp: str) -> int:
    """``00:00:01,400`` → 1400。"""
    clock, _, millis = stamp.strip().partition(",")
    hours, minutes, seconds = (int(part) for part in clock.split(":"))
    return ((hours * 60 + minutes) * 60 + seconds) * 1000 + int(millis or 0)


class SmokeResult:
    def __init__(self) -> None:
        self.notes: List[str] = []
        self.failures: List[str] = []

    def note(self, message: str) -> None:
        self.notes.append(message)
        print(f"  · {message}")

    def fail(self, message: str) -> None:
        self.failures.append(message)
        print(f"  [FAIL] {message}")

    @property
    def ok(self) -> bool:
        return not self.failures

    def report(self) -> str:
        lines = [f"端到端冒烟：{len(self.notes)} 条观察，{len(self.failures)} 个问题"]
        for note in self.notes:
            lines.append(f"  · {note}")
        for failure in self.failures:
            lines.append(f"  [FAIL] {failure}")
        return "\n".join(lines)


def run_smoke(
    output_dir: Path,
    voice_short_name: str = "en-US-AriaNeural",
    timeout: float = DEFAULT_TIMEOUT,
    theme: str = "light",
) -> SmokeResult:
    """跑一次真实生成。**会联网。**"""
    result = SmokeResult()
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_path = output_dir / "smoke.mp3"
    subtitle_path = output_dir / "smoke.srt"

    os.environ["ETTS_THEME"] = theme

    import tkinter as tk  # pylint: disable=import-outside-toplevel

    from . import platform_win  # pylint: disable=import-outside-toplevel
    from .settings import Settings  # pylint: disable=import-outside-toplevel
    from .ui import Application  # pylint: disable=import-outside-toplevel

    platform_win.enable_dpi_awareness()
    settings = Settings()
    settings.validate()
    settings.voice = voice_short_name
    settings.output_dir = str(output_dir)
    settings.show_hints = False

    root = tk.Tk()
    # ⚠️ **一创建就立刻收起**：Tk 的根窗口默认是"显示出来"的，而
    # `Application()` 要跑一百多毫秒——等到那时才挪窗口，用户已经看到它闪了
    # 一下（实测被抓到过一次）。`withdraw()` 在创建之后马上调用，屏幕上什么都不会出现。
    root.withdraw()
    app = None
    try:
        app = Application(root, settings)
        # 再把窗口**映射到屏幕外**：几何量、事件、状态栏都要求窗口真的被映射
        # 过一次（`winfo_width()` 之类读的是"分到的空间"），所以不能一直收起。
        # 屏幕外是快速路径；如果要在可见桌面上看效果，把坐标改回屏内即可。
        root.geometry(
            f"{max(root.winfo_reqwidth(), 1000)}x{max(root.winfo_reqheight(), 700)}"
            f"{OFFSCREEN:+d}{OFFSCREEN:+d}"
        )
        root.deiconify()
        root.update_idletasks()

        # 等语音列表：等的是"目录真的拿到了"，不是"等够了秒数"
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and not app.catalog.loaded:
            root.update()
            time.sleep(0.1)
        if app.catalog.loaded:
            result.note(f"语音列表已加载：{len(app.catalog)} 项")
        else:
            result.note(f"语音列表没加载成功（{app.catalog_error!r}），用兜底清单继续")

        voice = app.catalog.default_voice(voice_short_name)
        if voice is None:
            result.fail("兜底清单里也没有可用语音")
            return result

        # ---- 填真实控件 ------------------------------------------------
        # `set_editor_content` 就是"读入文件"按钮走的那个入口；它必须先把
        # 占位提示摘干净。*不要*在这里手工把 ``_placeholder_active`` 置 False——
        # 那样等于绕开被测代码，而这一版恰恰是在这条路径上出过一个真缺陷
        # （粘贴内容与占位提示混在一起，于是校验说"编辑区是空的"）。
        app.set_editor_content(SAMPLE_TEXT)
        if app._placeholder_active:  # noqa: SLF001
            result.fail("填了内容之后占位提示还在——它会混进用户内容")
        if "把要朗读的文字" in app.text.get("1.0", "end"):  # noqa: SLF001
            result.fail("编辑区里还留着占位提示的文字")
        if app.get_text().strip() != SAMPLE_TEXT.strip():
            result.fail(f"编辑区内容不对：{app.get_text()[:40]!r}")
        app._update_counts()  # noqa: SLF001
        app._visible_voices = list(app.catalog)  # noqa: SLF001
        app.voice_box.current(app._visible_voices.index(voice))  # noqa: SLF001

        validated = app._validate()  # noqa: SLF001
        if validated is None:
            result.fail("校验没过，生成不会开始")
            return result
        content, chosen, rate, volume, pitch = validated
        result.note(f"校验通过：语音 {chosen.short_name} rate={rate} volume={volume} pitch={pitch}")

        for path in (audio_path, subtitle_path):
            if path.exists():
                path.unlink()

        # ---- 走真实的生成入口（只把保存对话框换成已知路径） --------------
        app.start_generation_to(content, chosen, rate, volume, pitch, str(audio_path))
        if not app.generating:
            result.fail("调用之后 generating 仍然是 False")
        shown = False
        wait_until = time.monotonic() + 3.0
        while time.monotonic() < wait_until and app.generating:
            root.update()
            # 进度条现在是自绘的 `FlatProgress`，用 `place` 显隐——
            # 判据用 `winfo_manager()`（"当前由谁在管理"）：
            # 隐藏时是空串，`winfo_ismapped()` 在无人测试里不可靠。
            if app.progress.winfo_manager():
                shown = True
                break
            time.sleep(0.05)
        if shown:
            result.note("进度区已显示")
        elif app.generating:
            result.fail("进度区始终没有出现在窗口里")
        else:
            result.note("生成太快，进度区没来得及显示（延迟显示想要的行为）")

        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and app.generating:
            root.update()
            time.sleep(0.05)
        for _ in range(30):
            root.update()
            time.sleep(0.02)
        if app.generating:
            result.fail(f"{timeout:.0f} 秒内没有结束")
            app.cancel_generation()
            root.update()
            return result

        status_text = app.status_label.cget("text")
        result.note(f"状态栏：{status_text!r}")

        # ---- 判据：磁盘上真的有东西 ------------------------------------
        if not audio_path.exists():
            result.fail(f"没有生成 {audio_path.name}")
        else:
            size = audio_path.stat().st_size
            # 只读 3 个字节：`read_bytes()[:3]` 会把整段音频读进内存再切片。
            with audio_path.open("rb") as handle:
                header = handle.read(3)
            result.note(f"音频 {audio_path.name} = {size:,} 字节，头部 {header!r}")
            if size < 1000:
                result.fail("音频文件太小，多半不是有效的 mp3")
            if not (header[:3] == b"ID3" or (header[0] == 0xFF and (header[1] & 0xE0) == 0xE0)):
                result.fail(f"mp3 头部可疑：{header!r}")

        if not subtitle_path.exists():
            result.fail(f"没有生成 {subtitle_path.name}")
        else:
            body = subtitle_path.read_text(encoding="utf-8")
            blocks = [b for b in body.strip().split("\n\n") if b.strip()]
            if not blocks:
                result.fail("字幕文件是空的")
            elif not body.lstrip().startswith("1\n"):
                result.fail("字幕没有从序号 1 开始")
            elif "-->" not in body:
                result.fail("字幕里没有时间轴")
            else:
                longest = max(len(b.splitlines()[-1].split()) for b in blocks)
                result.note(f"字幕 {len(blocks)} 块，首块「{blocks[0].splitlines()[-1]}」，每块最多 {longest} 个词")
                if longest > 5:
                    result.fail(f"有字幕块超过 5 个词：{longest}")
                # 音频与字幕**对齐**才能用：上游是 CBR 48 kbps，
                # 所以文件大小能换算时长，拿它和最后一条字幕的结束时间比。
                if audio_path.exists():
                    audio_ms = audio_path.stat().st_size / (48_000 / 8 / 1000)
                    last_end = max(
                        _timestamp_to_ms(b.splitlines()[1].split(" --> ")[1]) for b in blocks
                    )
                    drift = last_end - audio_ms
                    result.note(
                        f"时长对齐：音频约 {audio_ms / 1000:.2f} 秒，"
                        f"字幕结束 {last_end / 1000:.2f} 秒，差 {drift / 1000:+.2f} 秒"
                    )
                    if abs(drift) > 3000:
                        result.fail("字幕结束时间与音频长度差了 3 秒以上")

        # ---- 状态栏必须说出真实路径 ------------------------------------
        for path in (audio_path, subtitle_path):
            if path.exists() and str(path) not in status_text:
                result.fail(f"状态栏里没有提到 {path}")
        if app.result_paths and str(audio_path) == app.result_paths[0]:
            result.note("状态栏的「打开音频 / 所在文件夹」指向真实产物")
        elif audio_path.exists():
            result.fail("状态栏的按钮没有指向刚生成的文件")
        # ⚠️ 判据是「**当前由哪个布局管理器在管它**」（`winfo_manager()`），
        # 不要盯着某一个管理器：
        #   * `winfo_ismapped()` 不可靠——窗口停在屏幕外做无人测试时，
        #     控件明明已经摆好，`ismapped` 有时仍是 0，于是同一份代码
        #     "单独跑通过、在门禁里跑失败"（实测的间歇性失败）；
        #   * `grid_info()` 只在控件用 grid 时才有值。这颗按钮后来改成了
        #     `place`（为了在"进度条 / 打开音频"共用坑位时不改变列宽），
        #     于是 `grid_info()` 永远是空，检查器误报"按钮没出现"。
        #
        # `winfo_manager()` 对三种管理器都成立：显示时是 "place"/"grid"，
        # 隐藏（`*_forget`/`*_remove`）时是空串。
        hidden = [b for b in app.result_buttons if not b.winfo_manager()]
        if not hidden:
            result.note("产物按钮已出现（打开音频）")
        elif audio_path.exists():
            names = "、".join(b.cget_text() for b in hidden)
            result.fail(f"生成成功后产物按钮没出现：{names}")
    finally:
        # 超时/提前返回时后台线程可能还在跑：先取消，再给它两秒把
        # aiohttp session 与临时文件收干净，然后才销毁窗口。
        # 不等的话，进程退出会在 %TEMP% 留 `.part`，终端里还会冒
        # "Unclosed client session"。
        try:
            if app is not None and app.generating:
                app.cancel_generation()
                deadline = time.monotonic() + 2.0
                while app.generating and time.monotonic() < deadline:
                    root.update()
                    time.sleep(0.02)
            if app is not None:
                for thread in (app._voice_thread, app._synth_thread):  # noqa: SLF001
                    if thread is not None and thread.is_alive():
                        thread.join(1.0)
        except Exception:  # noqa: BLE001 - 收尾失败不该盖住真正的结果
            pass
        try:
            root.destroy()
        except Exception:  # noqa: BLE001
            pass
    return result


def smoke_main(output_dir: Optional[str] = None, timeout: float = DEFAULT_TIMEOUT) -> int:
    """``--smoke`` 的入口：返回退出码。"""
    import tempfile  # pylint: disable=import-outside-toplevel

    from . import platform_win  # pylint: disable=import-outside-toplevel
    from .version import version_string  # pylint: disable=import-outside-toplevel

    platform_win.silence_missing_streams()
    print(f"版本：{version_string()}")
    folder = Path(output_dir) if output_dir else Path(tempfile.mkdtemp(prefix="etts-smoke-"))
    print(f"输出目录：{folder}")
    result = run_smoke(folder, timeout=timeout)
    print()
    print(result.report())
    print(f"产物留在：{folder}")
    return 0 if result.ok else 1
