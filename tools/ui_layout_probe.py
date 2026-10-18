"""回读界面的实际几何与颜色（"我以为摆对了" → "回读到的坐标是多少"）。

不抓图、不猜观感，只回答几个可验证的问题：

* 每个控件**占不占位置**（几何量，不是"看不看得见"）
* 窗口客户区是否容得下所有分区（底栏有没有被挤出窗口）
* 深浅两套主题下，文字与背景的实际 RGB 是否同色（"低对比度灰字"是画出来的
  还是没画出来）
* 描边/间距是否落在 4 的倍数网格上

用法::

    python tools/ui_layout_probe.py --theme light --out layout-light.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

from gui_of_edge_tts import platform_win  # noqa: E402
from gui_of_edge_tts.settings import Settings  # noqa: E402


def _rgb(colour: str):
    value = colour.lstrip("#")
    if len(value) != 6:
        return None
    try:
        return tuple(int(value[index : index + 2], 16) for index in (0, 2, 4))
    except ValueError:
        return None


def _relative_luminance(colour: str) -> float:
    channels = _rgb(colour)
    if channels is None:
        return 0.0
    parts = []
    for channel in channels:
        value = channel / 255.0
        parts.append(value / 12.92 if value <= 0.03928 else ((value + 0.055) / 1.055) ** 2.4)
    return 0.2126 * parts[0] + 0.7152 * parts[1] + 0.0722 * parts[2]


def contrast_ratio(first: str, second: str) -> float:
    """WCAG 对比度。**用来发现问题，不用来否决用户选的颜色。**"""
    light, dark = sorted((_relative_luminance(first), _relative_luminance(second)), reverse=True)
    return (light + 0.05) / (dark + 0.05)


SYSTEM_COLOUR_PREFIXES = ("System", "Sys")


def system_colour_leftovers(widget, found=None, depth: int = 0):
    """走一遍控件树，找出**底色还是系统色**的控件。

    系统色（``SystemButtonFace`` / ``SystemButtonText``）表示"这个控件
    从来没被主题刷过"。这是"漏设一个控件"的**可查证据**——比肉眼看
    "深色下有那么一块浅的"可靠得多（实测就是靠它抓到那三个参数标签）。
    """
    if found is None:
        found = []
    if depth > 12:
        return found
    for child in widget.winfo_children():
        name = type(child).__name__
        if name in ("TCombobox", "TProgressbar", "TScrollbar", "TSpinbox", "TSeparator"):
            continue
        if getattr(child, "kind", "") in ("accent", "neutral", "ghost"):
            continue  # FlatButton 自己上色
        try:
            background = str(child.cget("background"))
        except Exception:  # noqa: BLE001
            background = ""
        if background.startswith(SYSTEM_COLOUR_PREFIXES):
            label = ""
            try:
                label = str(child.cget("text"))[:20]
            except Exception:  # noqa: BLE001
                pass
            found.append((label or name, name, background))
        found = system_colour_leftovers(child, found, depth + 1)
    return found


def widget_info(widget, theme) -> Dict[str, Any]:
    """一个控件的几何 + 颜色。**取不到就记取不到**，不要填 0 当有值。"""
    info: Dict[str, Any] = {"class": type(widget).__name__}
    try:
        info["text"] = str(widget.cget("text"))[:60]
    except Exception:  # noqa: BLE001
        pass
    try:
        info["x"] = widget.winfo_rootx() - widget.winfo_toplevel().winfo_rootx()
        info["y"] = widget.winfo_rooty() - widget.winfo_toplevel().winfo_rooty()
        info["w"] = widget.winfo_width()
        info["h"] = widget.winfo_height()
        # ``winfo_ismapped`` 只对顶层子控件为真；嵌在卡片里的控件要用
        # ``winfo_viewable``（它沿着父链一路查），否则会误报"没显示"。
        info["viewable"] = bool(widget.winfo_viewable())
    except Exception as exc:  # noqa: BLE001
        info["geometry_error"] = repr(exc)
    for key, option in (("bg", "background"), ("fg", "foreground")):
        try:
            info[key] = str(widget.cget(option))
        except Exception:  # noqa: BLE001
            pass
    try:
        info["font"] = str(widget.cget("font"))
    except Exception:  # noqa: BLE001
        pass
    # 文字**需要多宽** vs 实际分到多宽：被截断的提示等于没有提示，
    # 而"看不出来被截断"正是这一条要防的（规范 20.8）。
    try:
        text = str(widget.cget("text"))
        font_name = str(widget.cget("font"))
        import tkinter.font as tkfont  # pylint: disable=import-outside-toplevel

        measured = tkfont.Font(root=widget, name=font_name).measure(text)
        info["text_px"] = measured
        info["text_truncated"] = bool(text) and measured > widget.winfo_width() + 2
    except Exception:  # noqa: BLE001
        pass
    return info


def _close_probe_window(root, app) -> None:
    """关掉探针窗口前先撤掉 `_drain_events` 的定时器。

    探针会连续建/销毁多扇 Tk 根窗口；残留的 `after(80)` 会在下一扇窗口里
    触发，终端上打出 `invalid command name "…_drain_events"`（实测）。
    这不是程序缺陷，但会污染门禁输出。
    """
    drain_id = getattr(app, "_drain_id", None)
    if drain_id:
        try:
            root.after_cancel(drain_id)
        except Exception:  # noqa: BLE001
            pass
    root.destroy()


def measure_configure_depth() -> int:
    """单独开一扇屏幕外窗口，实测 `<Configure>` 回调的最大嵌套深度。

    ## 为什么必须单独量

    `root.bind("<Configure>")` 的 bindtag 是 ``"."``，而这个窗口里**每个
    子控件的 bindtags 都含 ``"."``**。旧代码在重算里切换「生成语音 /
    生成中…」文字（宽度随之变），再 `update_idletasks()` **同步**派发那个
    按钮的 Configure → 回到重算入口 → 无底递归。修之前实测 **995 层**，
    随后 RecursionError 从 mainloop 冒出来（2026-10-17 用户报的崩溃）。

    ## 为什么不在版位测量那扇窗口里做

    要触发它必须真的泵 `update()`（只 `update_idletasks()` 不派发
    Configure），而 `update()` 会让 `after(150/200)` 的回调跑掉，改变
    后面要量的版位几何。**两种测量会互相干扰**，所以各开一扇窗口。
    """
    settings = Settings().with_environment_overrides()
    settings.show_hints = True
    import tkinter as tk  # noqa: PLC0415

    from gui_of_edge_tts.ui import Application  # noqa: PLC0415
    from gui_of_edge_tts.theme import (  # noqa: PLC0415
        WINDOW_DEFAULT_HEIGHT,
        WINDOW_DEFAULT_WIDTH,
    )

    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _probe_window import park  # noqa: PLC0415

    root = tk.Tk()
    app = Application(root, settings)
    depth = {"max": 0}

    def _watch_configure(_event=None) -> None:
        frame = sys._getframe()
        count = 0
        while frame is not None:
            count += 1
            frame = frame.f_back
        depth["max"] = max(depth["max"], count)

    root.bind_all("<Configure>", _watch_configure, add="+")
    try:
        park(root, WINDOW_DEFAULT_WIDTH, WINDOW_DEFAULT_HEIGHT)
        import time  # noqa: PLC0415

        time.sleep(0.25)
        for _ in range(4):
            root.update()
        app._fix_progress_slot(force=True)  # noqa: SLF001 - 强制走一遍重算
        for _ in range(2):
            root.update()
        for width in (1100, WINDOW_DEFAULT_WIDTH):
            height = root.winfo_height()
            root.geometry(f"{width}x{height}+-4000+-4000")
            for _ in range(3):
                root.update()
    finally:
        _close_probe_window(root, app)
    return depth["max"]


def measure_action_states() -> List[str]:
    """单独开一扇屏幕外窗口，走一遍"生成中 / 完成"两种状态。

    ## 为什么单独量

    静态版位探针只在"什么都没发生"时量一次，而 2026-10-17 用户报的
    「进度条展不开、打开音频不显示」恰好只在这两个状态下出现：

    * `progress_holder` 的行权重是 0 时只有 1px 高，进度条被裁成一条线；
    * 第 0 列把整行剩余宽度吃掉时，百分比文字钻到「取消」按钮底下；
    * 状态栏长高时窗口不长，下面几行被裁。

    这三条都必须在**真的调用了 `_begin_progress` / `set_result_status`**
    之后量，否则检查器永远是绿的。
    """
    from types import SimpleNamespace  # noqa: PLC0415

    settings = Settings().with_environment_overrides()
    settings.show_hints = False
    import tkinter as tk  # noqa: PLC0415

    from gui_of_edge_tts.ui import Application  # noqa: PLC0415

    if str(Path(__file__).resolve().parent) not in sys.path:
        sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _probe_window import park  # noqa: PLC0415

    problems: List[str] = []
    root = tk.Tk()
    app = Application(root, settings)
    try:
        park(root)
        import time  # noqa: PLC0415

        time.sleep(0.35)
        for _ in range(6):
            root.update()
        app._remember_clean_height()  # noqa: SLF001
        startup_height = root.winfo_height()

        app._begin_progress(SimpleNamespace(short_name="probe"), "", "", "", 21.0)
        app.set_status("正在合成：probe", "info")
        for _ in range(5):
            root.update()

        if not app.progress.winfo_manager():
            problems.append("生成中：进度条没有显示")
        if app.progress_holder.winfo_height() < app.progress.winfo_height():
            problems.append(
                f"生成中：进度条被容器裁掉（holder="
                f"{app.progress_holder.winfo_height()}px，进度条="
                f"{app.progress.winfo_height()}px）"
            )
        if root.winfo_height() <= startup_height:
            problems.append("生成中：状态栏长高后窗口没有加高")

        # 百分比文字必须整个落在「取消」按钮左边，不能被按钮盖住。
        cancel_left = app.cancel_button.winfo_rootx() - root.winfo_rootx()
        texts = [item for item in app.progress.find_all() if app.progress.type(item) == "text"]
        for item in texts:
            bbox = app.progress.bbox(item)
            if not bbox:
                continue
            right = app.progress.winfo_rootx() - root.winfo_rootx() + bbox[2]
            if right > cancel_left:
                problems.append(
                    f"生成中：进度百分比文字压到了「取消」按钮下面"
                    f"（文字右缘 {right}px > 取消左缘 {cancel_left}px）"
                )

        app._end_progress()  # noqa: SLF001
        app.set_result_status("完成：probe.mp3\n字幕：probe.srt\n用时 1.0 秒", ["probe.mp3"])
        for _ in range(8):
            root.update()
        if not app.open_file_button.winfo_manager():
            problems.append("完成：打开音频按钮没有显示")
        elif app.open_file_button.winfo_height() < 30:
            problems.append(
                f"完成：打开音频按钮被裁（高度 {app.open_file_button.winfo_height()}px）"
            )
        footer_bottom = (
            app.version_label.winfo_rooty() - root.winfo_rooty()
            + app.version_label.winfo_height()
        )
        if footer_bottom > root.winfo_height():
            problems.append(
                f"完成：页脚超出客户区（底边 {footer_bottom}px > 窗口 {root.winfo_height()}px）"
            )

        # 「清空」只能清文字：用户手动把窗口拉高后，输入框高度不能被缩回去。
        root.geometry(f"{root.winfo_width()}x{root.winfo_height() + 120}+-4000+-4000")
        for _ in range(3):
            root.update()
        editor_before = app.editor_card.winfo_height()
        app.clear_text()
        for _ in range(6):
            root.update()
        editor_after = app.editor_card.winfo_height()
        if abs(editor_after - editor_before) > 2:
            problems.append(
                "清空把输入框高度改了："
                f"{editor_before}px → {editor_after}px（用户拉高的窗口不应被重置）"
            )
    finally:
        _close_probe_window(root, app)
    return problems


def run(theme_name: str, language: str = "zh") -> Dict[str, Any]:
    os.environ["ETTS_THEME"] = theme_name
    os.environ["ETTS_LANG"] = language
    platform_win.enable_dpi_awareness()

    import tkinter as tk

    from gui_of_edge_tts.ui import Application

    settings = Settings().with_environment_overrides()
    settings.show_hints = True
    # 递归深度单独量（见 `measure_configure_depth` 的说明）：必须真的泵
    # `update()`，而那会改变版位测量所依赖的 after 回调时序。
    configure_depth = measure_configure_depth()
    # 操作区/状态栏的动态状态单独量（生成中、完成）
    action_problems = measure_action_states()
    # 屏幕外跑：布局照算、不闪、更快（2026-10-17 起可见窗口也已允许，
    # 但门禁用屏幕外更安静；见 `00` 硬性约束 ⑤）
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from _probe_window import park, verify_offscreen  # noqa: PLC0415

    root = tk.Tk()
    app = Application(root, settings)
    # 先只挪位置、**不改尺寸**：窗口高度现在由程序按内容自己定
    # （`_remember_clean_height`）。这里如果像旧版那样强行写 1320x792，
    # 就会把程序刚长高到 849 的窗口压回去，然后检查器报"页脚超出客户区"
    # ——量到的是探针自己制造的缺陷。
    park(root)
    verify_offscreen()
    # 让**真实的事件循环**把启动阶段的 after 回调跑完：`_lock_editor_min_height`
    # (80ms) 会把编辑区行锁到 299px，`_fix_progress_slot` (200ms) 会定住操作区，
    # `_remember_clean_height` (150ms) 再按内容把窗口长高。只跑
    # `update_idletasks()` 的话这些都不会发生——量到的是一个**还没稳定**的窗口，
    # 会得出"内容放得下"的错误结论（2026-10-17 实测：探针 792/272，真实 849/299）。
    import time  # noqa: PLC0415

    time.sleep(0.35)
    for _ in range(6):
        root.update()
    app._remember_clean_height()  # noqa: SLF001 - 幂等；确保基准已记
    root.update_idletasks()

    theme = app.theme
    client_w = root.winfo_width()
    client_h = root.winfo_height()

    # ---- 静止状态下**必须藏着**的控件 --------------------------------------
    #
    # 这一条是补出来的：我一次整块替换时把 `grid_remove()` 那两行一起删了，
    # 于是**什么都没做的时候，一条空进度条和一个「取消」按钮就摆在界面上**
    # （用户实测报回来的原话："我没有粘贴文字，我没有启动转语音。你这个空
    # 进度条和这个取消按钮放在这里是什么意思嘛？"）。
    #
    # 原来的探针只查"几何是否合理、配色是否对"，**不查"该藏的有没有藏"**，
    # 所以这种错误一路通过。判据是「**当前没有布局管理器在管它**」——
    # `winfo_manager()` 对 grid/place/pack 三种都成立，而 `grid_info()`
    # 只对 grid 有效（进度条与「打开音频」后来改成了 `place`，
    # 用 `grid_info()` 会永远读成"隐藏"，检查器就形同虚设）。
    should_be_hidden = (
        ("进度条", "progress"),
        ("取消按钮", "cancel_button"),
        ("打开音频", "open_file_button"),
    )
    idle_problems: List[str] = []
    for label, attribute in should_be_hidden:
        widget = getattr(app, attribute, None)
        if widget is None:
            idle_problems.append(f"{label} 不存在（属性 {attribute}）")
            continue
        if widget.winfo_manager():
            idle_problems.append(
                f"{label} 在静止状态下是显示着的——它应该只在生成过程中出现"
            )

    reported: List[Dict[str, Any]] = []
    for name in (
        "help_strip",
        "help_strip_text",
        "title_label",
        "theme_button",
        "help_button",
        "settings_card",
        "voice_caption",
        "voice_box",
        "voice_filter",
        "voice_count",
        "rate_entry",
        "volume_entry",
        "pitch_entry",
        "params_hint",
        "editor_card",
        "editor_caption",
        "text",
        "editor_tip",
        "action_bar",
        "progress_holder",
        "generate_button",
        "cancel_button",
        "status_card",
        "status_label",
        "counts_label",
        "version_label",
    ):
        widget = getattr(app, name, None)
        if widget is None:
            reported.append({"name": name, "missing": True})
            continue
        info = widget_info(widget, theme)
        info["name"] = name
        reported.append(info)

    palette = theme.palette
    same_colour = {
        key: getattr(palette, key)
        for key in (
            "background",
            "card",
            "surface",
            "text",
            "text_secondary",
            "accent",
            "border_strong",
        )
    }
    #: 静止态"该藏的有没有藏"的结论，直接并入总问题列表
    problems: List[str] = list(idle_problems) + list(action_problems)
    if getattr(app, "_voice_pop_scrollbar", None) is None:
        problems.append(
            "语音下拉列表没有换成扁平滚动条（_install_flat_voice_popdown 失败）"
        )
    if configure_depth > 50:
        problems.append(
            f"<Configure> 回调嵌套到 {configure_depth} 层："
            "根窗口的 Configure 绑定吃到了子控件的事件（会递归到 RecursionError）"
        )
    dialogs: List[Dict[str, Any]] = []
    if same_colour["text"] == same_colour["surface"]:
        problems.append("正文色与输入区表面色相同：那等于看不见")
    # **面板只有一种底色**（用户定稿）：card 与 background 必须相同，
    # 否则又会出现"一块一块的色块"。
    if same_colour["card"] != same_colour["background"]:
        problems.append(
            f"面板出现了两种底色：card={same_colour['card']} ≠ background={same_colour['background']}"
        )
    if same_colour["surface"] == same_colour["background"]:
        problems.append("输入区表面色与面板底色相同：看不出哪里能打字")
    if same_colour["border_strong"] == same_colour["background"]:
        problems.append("按钮描边色与面板底色相同：按钮会和背景融在一起")

    # 正文与它所在表面的对比度：低对比度灰字是"画出来了但看不清"，
    # 而它正是深色主题最容易出的问题。
    ratio_body = contrast_ratio(same_colour["text"], same_colour["surface"])
    ratio_secondary = contrast_ratio(same_colour["text_secondary"], same_colour["surface"])
    if ratio_body < 4.5:
        problems.append(f"正文对比度只有 {ratio_body:.2f}（要求 ≥ 4.5）")
    if ratio_secondary < 3.0:
        problems.append(f"次要文字对比度只有 {ratio_secondary:.2f}（要求 ≥ 3.0）")

    # **系统色残留**：这是"漏设一个控件"的唯一可查证据。
    # 实测踩过——"语速 % / 音量 % / 音调 Hz"三个标签从没被设色，
    # 深色主题下就变成浅色块，而肉眼看到的是"主题没适配"。
    leftovers = system_colour_leftovers(app.root)
    for name, widget_class, background in leftovers[:10]:
        problems.append(f"{name}（{widget_class}）还是系统色 {background}：主题没刷到它")

    # ---- 弹窗也要查（用户报过"设置窗口视觉规范与主界面不统一"）----------
    # 只查主窗口是不够的：弹窗里的按钮曾经因为**没传 theme** 而永远停在
    # SystemButtonFace，而主窗口的遍历看不到它们。
    for label, opener, attribute in (
        ("设置窗口", app.show_settings, "_settings_window"),
        ("提示窗口", app.show_help, "_help_window"),
    ):
        opener()
        dialog = getattr(app, attribute, None)
        if dialog is not None and dialog.winfo_exists():
            park(dialog)
        for _ in range(6):
            root.update_idletasks()
        if dialog is None or not dialog.winfo_exists():
            problems.append(f"{label}没有打开")
            continue
        dialog_leftovers = system_colour_leftovers(dialog)
        for name, widget_class, background in dialog_leftovers[:5]:
            problems.append(
                f"{label}：{name}（{widget_class}）还是系统色 {background}：主题没刷到它"
            )
        dialogs.append(
            {
                "name": label,
                "geometry": [dialog.winfo_width(), dialog.winfo_height()],
                "content": [dialog.winfo_reqwidth(), dialog.winfo_reqheight()],
                "leftovers": dialog_leftovers,
            }
        )
        # **留白检查**：窗口比内容高出太多就是"下面全是留白"。
        # 判据是几何量，不是"看起来空"。
        slack = dialog.winfo_height() - dialog.winfo_reqheight()
        if slack > 40:
            problems.append(f"{label} 比内容高出 {slack} px：下面全是留白")
        dialog.destroy()

    verify_offscreen()
    visible = [item for item in reported if item.get("viewable") and "y" in item]
    bottom = max((item["y"] + item["h"] for item in visible), default=0)
    if bottom > client_h + 1:
        problems.append(f"最下面的控件底边（{bottom}）超出了客户区高度（{client_h}）")
    for item in reported:
        if item.get("missing") or not item.get("viewable"):
            continue
        if item["y"] + item["h"] > client_h + 1:
            problems.append(f"{item['name']} 落在客户区外面（y={item['y']} h={item['h']}）")
        if item.get("text_truncated"):
            problems.append(
                f"{item['name']} 的提示语被截断：需要 {item['text_px']} px，"
                f"只分到 {item['w']} px —— {item.get('text', '')[:40]!r}"
            )

    spacing = theme.px(4)
    # 判据是**相邻分区之间的空隙**落在 4 逻辑像素网格上，不是"绝对 y 能被 4 整除"
    # ——嵌套容器的基线偏移会让绝对坐标出现 1~3 像素的余数，那不是间距错误。
    # 窗口自身还要自报一次版位问题（提示语放不下、占位文字被裁）。
    problems += app.layout_findings()
    # 另外：168 DPI 下 4 逻辑像素正好等于 7 物理像素，所以余数按"离最近的网格
    # 倍数有多远"算，允许 2 像素的累计取整误差（多行叠加时会攒出来）。
    sections = [
        item for item in reported
        if item.get("name") in {
            "help_strip", "title_label", "settings_card", "editor_card",
            "action_bar", "status_card", "counts_label",
        } and item.get("viewable")
    ]
    sections.sort(key=lambda item: item["y"])
    gaps = [
        {"from": earlier["name"], "to": later["name"], "gap": later["y"] - (earlier["y"] + earlier["h"])}
        for earlier, later in zip(sections, sections[1:])
    ]
    off_grid_gaps = []
    for entry in gaps:
        remainder = abs(entry["gap"]) % spacing
        if min(remainder, spacing - remainder) > 2:
            off_grid_gaps.append(entry)

    result = {
        "theme": theme_name,
        "dark": theme.dark,
        "dpi": theme.dpi,
        "client": [client_w, client_h],
        "palette": same_colour,
        "contrast": {"body_on_surface": round(ratio_body, 2), "secondary_on_surface": round(ratio_secondary, 2)},
        "system_colour_leftovers": leftovers,
        "dialogs": dialogs,
        "widgets": reported,
        "lowest_widget_bottom": bottom,
        "configure_depth_max": configure_depth,
        "action_state_problems": action_problems,
        "logical_grid_px": spacing,
        "section_gaps": gaps,
        "off_grid_gaps": off_grid_gaps,
        "problems": problems,
    }

    _close_probe_window(root, app)
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", default="light", choices=["light", "dark"])
    parser.add_argument("--lang", default="zh", choices=["zh", "en"])
    parser.add_argument("--out", default="")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    result = run(args.theme, args.lang)
    if args.out:
        Path(args.out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")

    if not args.quiet:
        print(
            f"theme={result['theme']} lang={args.lang} dark={result['dark']} "
            f"dpi={result['dpi']} client={result['client']}"
        )
        for item in result["widgets"]:
            if item.get("missing"):
                print(f"  [MISSING] {item['name']}")
                continue
            print(
                f"  {item['name']:<16} {item.get('x', '?'):>5},{item.get('y', '?'):>4} "
                f"{item.get('w', '?'):>5}x{item.get('h', '?'):<4} view={item.get('viewable')} "
                f"bg={item.get('bg')} fg={item.get('fg')}"
            )
        print("lowest bottom:", result["lowest_widget_bottom"])
        for dialog in result.get("dialogs", []):
            print(f"  {dialog['name']}: 几何 {dialog['geometry']} 内容 {dialog['content']}")
        print(f"4 逻辑像素 = {result['logical_grid_px']} 物理像素")
        print(f"Configure 回调最大嵌套深度：{result['configure_depth_max']} 层")
        for entry in result["section_gaps"]:
            print(f"  间距 {entry['from']:<14} → {entry['to']:<14} {entry['gap']:>4} px")
        if result["off_grid_gaps"]:
            print("不在网格上的间距:", result["off_grid_gaps"])
        if result["problems"]:
            for problem in result["problems"]:
                print("[PROBLEM]", problem)
        else:
            print("[OK] 没有发现几何/配色上的问题")
    return 1 if result["problems"] else 0


if __name__ == "__main__":
    sys.exit(main())
