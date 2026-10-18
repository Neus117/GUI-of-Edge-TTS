"""程序入口：命令行、自检、以及创建窗口。

分开写的原因是**自检不能依赖窗口**：``--version`` 与 ``--selftest`` 必须在
没有桌面、没有网络的情况下也能给出一个可判定的结果。归档里踩过这个坑——
拿"不创建窗口的命令"去验证窗口相关的改动，等于什么都没验证。
"""

from __future__ import annotations

import argparse
import os
import sys
import traceback
from typing import List, Optional

from . import platform_win, text as text_mod, version as version_mod
from .lang import L, apply as apply_language
from .settings import Settings, config_path
from .subtitles import SubtitleBuilder, compose
from .theme import Theme

EXIT_OK = 0
EXIT_FAILED = 1


def _ensure_console() -> bool:
    """保证 ``print`` 有地方可写，且不会炸。

    打包成 windowed exe 之后没有控制台——**这个缺陷只在冻结态出现**，
    从源码跑永远看不到（归档 `projects/File-tracker.md` 第五节记过同一个形态）。

    ⚠️ 判据是"**有没有可以写的地方**"，不是"有没有控制台"：
    父进程用 ``> out.log`` 或管道收集输出时没有控制台，但那明明是可以写的。
    第一版只看控制台，于是那种情况下程序算完了却一个字都不输出。

    ⚠️ 而且冻结态里 ``sys.stdout`` 恒为 ``None``（windowed 启动器不给子进程
    标准句柄），所以**必须先 `attach_parent_console()`**，它会去要父进程的
    管道/重定向句柄——不能只用 `has_output_stream()` 判断。
    """
    if platform_win.attach_parent_console():
        return True
    return platform_win.has_output_stream()


def _report_without_console(title: str, body: str) -> None:
    """没有控制台时的出口：存一份到配置目录，并弹一个短提示框。

    **不静默退出**：用户双击运行 `--version` 时至少要看到版本号，
    否则他会以为程序坏了。
    """
    saved = ""
    try:
        target = config_path().parent / "last-output.txt"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
        saved = str(target)
    except OSError:
        pass
    message = body
    if saved:
        message += L(f"\n\n（已保存到 {saved}）", f"\n\n(Saved to {saved})")
    try:
        import tkinter as tk  # pylint: disable=import-outside-toplevel

        root = tk.Tk()
        root.withdraw()
        # 6 秒后自动关闭：不需要用户点任何东西（归档 01 错误六的延伸）
        root.after(6000, root.destroy)
        from tkinter import messagebox  # pylint: disable=import-outside-toplevel

        messagebox.showinfo(title, message)
        root.destroy()
    except Exception:  # noqa: BLE001 - 连界面都建不起来就只能放弃了
        pass


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="GUI-of-Edge-TTS.exe",
        description=L(
            "Edge-TTS 的图形界面：文字转语音，同时生成字幕。",
            "GUI for Edge-TTS: text to speech with matching subtitles.",
        ),
    )
    parser.add_argument(
        "--version",
        action="store_true",
        help=L("打印版本与构建提交后退出", "Print the version and build commit, then exit"),
    )
    parser.add_argument(
        "--selftest",
        action="store_true",
        help=L(
            "不创建窗口地跑一遍自检（参数解析 / 字幕合成 / 主题 / 设置读写）",
            "Run self-checks without a window (parameters, subtitles, theme, settings)",
        ),
    )
    parser.add_argument(
        "--path",
        default="",
        help=L(
            "启动时直接采用这个语音（ShortName，例如 en-US-AriaNeural）",
            "Use this voice at startup (ShortName, e.g. en-US-AriaNeural)",
        ),
    )
    parser.add_argument(
        "--smoke",
        action="store_true",
        help=L(
            "在这个进程里跑一次真实生成（联网），用于核对打包后的产物",
            "Run one real generation (network) in this process to verify the packaged build",
        ),
    )
    parser.add_argument(
        "--out",
        default="",
        help=L(
            "启动时预设输出目录（--smoke 时是它的产物目录）",
            "Preset the output folder (with --smoke, the output folder for products)",
        ),
    )
    parser.add_argument(
        "--settings",
        action="store_true",
        help=L("启动后直接打开设置窗口", "Open the settings window at startup"),
    )
    parser.add_argument(
        "text_file",
        nargs="?",
        default="",
        help=L("启动时载入的文本文件（可选）", "Optional text file to load at startup"),
    )
    return parser


def _check(label: str, condition: bool, detail: str = "") -> bool:
    mark = "OK  " if condition else "FAIL"
    line = f"[{mark}] {label}"
    if detail:
        line += f" — {detail}"
    print(line)
    return condition


def run_selftest() -> int:
    """不创建窗口的自检。

    每一项都**回读实际值**再断言，不看"调用有没有报错"——
    这正是归档 `DevAesthetics` 第 22.3 节要求的判据形式。
    """
    from . import params as params_mod  # 延迟导入，保证 --version 足够快

    results: List[bool] = []

    print(L(f"版本：{version_mod.version_string()}", f"Version: {version_mod.version_string()}"))
    results.append(_check(L("版本号非空", "Version is non-empty"), bool(version_mod.APP_VERSION)))
    results.append(
        _check(
            L("构建提交已知", "Build commit is known")
            if version_mod.version_string().split("+")[-1] != "unknown"
            else L("构建提交未知（开发态可能是 unknown）", "Build commit unknown (development may be unknown)"),
            True,
            version_mod.version_string().split("+")[-1],
        )
    )

    processed = text_mod.preprocess_text("你好，世界！\r\n\r\n\r\nHello.")
    results.append(
        _check(
            L(
                "文本预处理：中文标点转半角 + 压缩空行",
                "Text preprocessing: Chinese punctuation to ASCII + blank-line compression",
            ),
            processed == "你好,世界!\n\nHello.",
            repr(processed),
        )
    )

    results.append(
        _check(
            L(
                "参数归一化：'20' / '1.2x' / '+30%'",
                "Parameter normalization: '20' / '1.2x' / '+30%'",
            ),
            (params_mod.parse_rate("20"), params_mod.parse_rate("1.2x"), params_mod.parse_rate("+30%"))
            == ("+20%", "+20%", "+30%"),
            str((params_mod.parse_rate("20"), params_mod.parse_rate("1.2x"))),
        )
    )
    try:
        params_mod.parse_rate("abc")
        bad_rejected = False
    except params_mod.ParameterError:
        bad_rejected = True
    results.append(_check(L("非法参数会被拒绝而不是发往服务端", "Invalid parameters are rejected locally"), bad_rejected))
    try:
        params_mod.parse_rate("900")
        out_of_range_rejected = False
    except params_mod.ParameterError:
        out_of_range_rejected = True
    results.append(_check(L("超范围参数会被拒绝（900%）", "Out-of-range values are rejected (900%)"), out_of_range_rejected))

    builder = SubtitleBuilder()
    # 上游的单位是 100 纳秒（tick）：5_000_000 ticks = 500 ms，4_000_000 = 400 ms，
    # 于是每块首尾各差 5 个词 × 500 ms。
    for index in range(6):
        builder.feed(
            {
                "type": "WordBoundary",
                "offset": index * 5_000_000,
                "duration": 4_000_000,
                "text": f"w{index}",
            }
        )
    cues = builder.cues()
    results.append(
        _check(
            L(
                "字幕合并：6 个词 → 2 块（每块最多 5 个）",
                "Subtitle merge: 6 words → 2 cues (max 5 words each)",
            ),
            len(cues) == 2 and len(cues[0].content.split()) == 5,
            (
                L(
                    f"{len(cues)} 块，首块 {cues[0].content!r}",
                    f"{len(cues)} cues, first {cues[0].content!r}",
                )
                if cues
                else L("没有生成字幕块", "No subtitle cues were generated")
            ),
        )
    )
    body = compose(cues)
    results.append(
        _check(
            L(
                "SRT 时间戳格式与刻度换算（tick → 毫秒）",
                "SRT timestamp format and tick-to-ms conversion",
            ),
            body.startswith("1\n00:00:00,000 --> 00:00:02,400\n"),
            body.splitlines()[1] if len(body.splitlines()) > 1 else "",
        )
    )

    for mode, expect_dark in (("light", False), ("dark", True)):
        theme = Theme.detect(mode)
        results.append(
            _check(
                L(
                    f"主题 {mode}：颜色齐备且深浅正确",
                    f"Theme {mode}: complete palette and correct darkness",
                ),
                theme.dark is expect_dark and theme.palette.background.startswith("#"),
                L(f"背景 {theme.palette.background}", f"Background {theme.palette.background}"),
            )
        )

    settings = Settings()
    settings.validate()
    results.append(
        _check(
            L("设置默认值合法", "Default settings are valid"),
            bool(settings.theme) and bool(settings.output_dir),
            settings.output_dir,
        )
    )

    import tempfile  # pylint: disable=import-outside-toplevel
    from pathlib import Path  # pylint: disable=import-outside-toplevel

    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "settings.json"
        settings.voice = "en-US-AriaNeural"
        settings.save(path)
        reloaded = Settings.load(path)
        results.append(
            _check(
                L("设置能写能读回", "Settings can be saved and loaded"),
                reloaded.voice == settings.voice,
                reloaded.voice,
            )
        )
        path.write_text("{ 这不是 JSON", encoding="utf-8")
        broken = Settings.load(path)
        results.append(
            _check(
                L(
                    "损坏的设置文件降级到默认值且留档",
                    "Corrupt settings fall back to defaults and are archived",
                ),
                broken.voice == "" and path.with_suffix(".json.bad").exists(),
            )
        )

    icon = platform_win.resource_path("images/Edge-TTS.ico")
    results.append(_check(L("图标资源可定位", "Icon resource can be located"), os.path.exists(icon), icon))
    results.append(
        _check(
            L("配置文件路径可确定", "Settings path can be determined"),
            str(config_path()).endswith("settings.json"),
            str(config_path()),
        )
    )

    print()
    failed = results.count(False)
    print(
        L(
            f"自检：{len(results) - failed}/{len(results)} 项通过",
            f"Self-test: {len(results) - failed}/{len(results)} checks passed",
        )
    )
    return EXIT_OK if failed == 0 else EXIT_FAILED


def main(argv: Optional[List[str]] = None) -> int:
    settings = Settings.load().with_environment_overrides()
    apply_language(settings.language)
    parser = build_parser()
    args = parser.parse_args(argv)

    # 中文输出必须能在管道/文件里读——用户报障时会把它贴出来。
    platform_win.force_utf8_streams()

    if args.version or args.selftest or args.smoke:
        # 这三个命令都要往某个地方写。`_ensure_console()` 的判据是
        # **有没有可写的地方**（控制台、管道、重定向文件都算），
        # 而不是"有没有控制台"——后者会让 `> out.log` 这种调用什么都拿不到。
        has_output = _ensure_console()
        if args.version:
            if has_output:
                print(version_mod.version_string())
            else:
                _report_without_console("GUI-of-Edge-TTS", version_mod.version_string())
            return EXIT_OK
        if args.smoke:
            from . import _smoke  # pylint: disable=import-outside-toplevel

            if has_output:
                return _smoke.smoke_main(args.out or None)
            import io  # pylint: disable=import-outside-toplevel

            buffer = io.StringIO()
            original = sys.stdout
            sys.stdout = buffer
            try:
                code = _smoke.smoke_main(args.out or None)
            finally:
                sys.stdout = original
            title = L("端到端冒烟", "End-to-end smoke") + (
                L("通过", " passed") if code == EXIT_OK else L("未通过", " failed")
            )
            _report_without_console(title, buffer.getvalue())
            return code
        if has_output:
            return run_selftest()
        # 无控制台：把自检结果收进一个字符串再弹出来
        import io  # pylint: disable=import-outside-toplevel

        buffer = io.StringIO()
        original = sys.stdout
        sys.stdout = buffer
        try:
            code = run_selftest()
        finally:
            sys.stdout = original
        title = L("自检", "Self-test") + (
            L("通过", " passed") if code == EXIT_OK else L("未通过", " failed")
        )
        _report_without_console(title, buffer.getvalue())
        return code

    # ---- 真正的界面 ------------------------------------------------------
    # 冻结成 windowed exe 时没有 stdout：塞一个吞掉一切的替身，
    # 免得任何一句诊断输出把启动路径弄崩（症状是"双击没反应"）。
    platform_win.silence_missing_streams()
    settings = settings.with_environment_overrides()
    apply_language(settings.language)
    if args.path:
        settings.voice = args.path
    if args.out:
        settings.output_dir = args.out

    # DPI 感知必须在任何窗口之前设置：窗口尺寸按 96 DPI 定、字体按 168 DPI 定
    # 会让文字比窗口宽（归档 `DevAesthetics` 第 1.2 节）。
    platform_win.enable_dpi_awareness()
    dark = settings.theme == "dark" or (
        settings.theme == "system" and platform_win.system_uses_dark_theme()
    )
    platform_win.allow_dark_native_controls(dark)

    import tkinter as tk  # pylint: disable=import-outside-toplevel

    from .ui import Application  # pylint: disable=import-outside-toplevel

    root = tk.Tk()
    try:
        application = Application(root, settings)
    except Exception:  # noqa: BLE001 - 起不来时要说清是什么错，不能静默退出
        traceback.print_exc()
        try:
            from tkinter import messagebox  # pylint: disable=import-outside-toplevel

            messagebox.showerror(
                L("启动失败", "Startup failed"),
                L("界面初始化失败：\n\n", "Could not initialize the interface:\n\n")
                + traceback.format_exc(limit=3),
            )
        except Exception:  # noqa: BLE001
            pass
        return EXIT_FAILED

    # 标题栏深浅已经在 Application.__init__ 的 `_apply_window_chrome()` 里
    # 设过一遍了（它覆盖主窗口与所有已打开的弹窗）。这里不再重复调用——
    # 两处各自设一次，迟早会有一处漏掉（实测主窗口就被漏过一次）。
    if args.text_file:
        application.load_text_file(args.text_file)

    if args.settings:
        application.show_settings()

    root.mainloop()
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
