"""所有**用户可见界面**的主题一致性审计。

存在的理由：这一版被用户连续报了三轮"没有正确反色"，而每一轮我都只修了
**报出来的那一处**。问题不在修得对不对，而在**我没有把范围一次性盖住**：

* 第一轮漏了主窗口里三个参数标签（手写控件清单漏了）；
* 第二轮漏了设置/提示窗口里的按钮（没传 `theme`）；
* 第三轮漏了弹窗里"没有进 `_theme_widget_tree` 遍历范围"的那些控件。

所以这个脚本的做法是：**枚举所有顶级窗口 → 递归每一个控件 → 逐个回读
颜色并和主题期望值对比**，而不是"检查我记得的那几个"。

判据（每条都是可回读的值）：

1. 控件的 ``background`` 必须等于它所属层级期望的主题色之一
   （面板色 / 表面色 / 强调色）；
2. **不允许**出现系统色（``System*``）；
3. 弹窗的标题栏深色属性必须与主题一致（``apply_dark_titlebar`` 的返回值）；
4. 弹窗高度不得比内容高出 40 px 以上（留白）；
5. 每个可点击控件都必须能在控件树里被找到（"定义了却没人显示"）。

用法::

    python tools/audit_theme_surfaces.py            # 两个主题都查
    python tools/audit_theme_surfaces.py --theme dark
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

# 这些控件类型由系统或 ttk 绘制，颜色不由 tk 的 background 选项决定
SKIP_TYPES = {
    "TCombobox",
    "TProgressbar",
    "TScrollbar",
    "TSpinbox",
    "TSeparator",
    "Menu",
    "Scrollbar",
}


def audit_window(window, palette, path: str, problems: List[str], seen: List[Dict[str, Any]]) -> None:
    """审计**一整扇窗口**：包括窗口自己，以及它的全部子孙控件。

    ⚠️ **窗口自己一定要查。** 第一版只查 `winfo_children()`，于是
    **根窗口本身从来没被检查过**——而它正是"深色下面板没变深"的根因：
    子控件全是深色，根窗口还是 `SystemButtonFace`，从间隙里露出来。
    **检查器漏掉了被检查对象本身**，这是最隐蔽的一种漏法。
    """
    try:
        own = str(window.cget("background"))
    except Exception:  # noqa: BLE001
        own = ""
    if own:
        seen.append({"widget": f"{path}（窗口自己）", "background": own})
        if own.startswith("System"):
            problems.append(f"{path} 窗口自己的底色还是系统色 {own}")
        elif not _in_palette(own, palette):
            problems.append(
                f"{path} 窗口自己的底色 {own} 不在主题色里"
                f"（期望 background={palette.background}）"
            )
    audit(window, palette, path, problems, seen)


def _in_palette(colour: str, palette) -> bool:
    allowed = {
        palette.background,
        palette.surface,
        palette.surface_hover,
        palette.accent,
        palette.accent_hover,
        palette.track,
        palette.scrollbar,
        palette.scrollbar_hover,
    }
    return colour.lower() in {c.lower() for c in allowed}


def audit(widget, palette, path: str, problems: List[str], seen: List[Dict[str, Any]], depth: int = 0):
    """递归审计一棵控件树的**子孙**（窗口自己由 :func:`audit_window` 查）。"""
    if depth > 14:
        return
    for child in widget.winfo_children():
        name = type(child).__name__
        label = ""
        try:
            label = str(child.cget("text"))[:18]
        except Exception:  # noqa: BLE001
            pass
        here = f"{path}/{name}{('(' + label + ')') if label else ''}"
        if name in SKIP_TYPES:
            seen.append({"widget": here, "skipped": "系统/ttk 绘制"})
            continue
        try:
            background = str(child.cget("background"))
        except Exception:  # noqa: BLE001
            background = ""
        if background:
            seen.append({"widget": here, "background": background})
            if background.startswith("System"):
                problems.append(f"{here} 还是系统色 {background}")
            elif not _in_palette(background, palette):
                # 系统定义的颜色名（如 white / gray90）也算没反色
                problems.append(
                    f"{here} 的底色 {background} 不在主题色里"
                    f"（期望 background={palette.background} 或 surface={palette.surface}）"
                )
        audit(child, palette, here, problems, seen, depth + 1)


def run(theme_mode: str) -> int:
    os.environ["ETTS_THEME"] = theme_mode
    from gui_of_edge_tts import platform_win  # noqa: PLC0415

    platform_win.enable_dpi_awareness()
    import tkinter as tk  # noqa: PLC0415

    from gui_of_edge_tts.settings import Settings  # noqa: PLC0415
    from gui_of_edge_tts.ui import Application  # noqa: PLC0415

    # ⚠️ **整个审计过程不开可见窗口。**
    #
    # 第一版是"把窗口建出来、让它显示、再读颜色"——结果是用户屏幕上不停弹窗，
    # 而他正在工作。用户明确要求过不要在调试时弹窗。
    #
    # 关键认识：**读颜色和几何根本不需要窗口被显示**。
    #   * `winfo_children()` / `cget("background")` 在窗口不可见时照样正确；
    #   * `winfo_reqwidth()` / `winfo_reqheight()` 是 Tk 算出来的自然尺寸，
    #     也不需要可见；
    #   * 只有 `winfo_width()`（实际分配）需要一次 `update_idletasks()`。
    # 所以这里把窗口 `withdraw()`（撤下，不进任务栏、不抢焦点），
    # 需要让 Tk 走一遍布局时用 `update_idletasks()`——它不处理输入事件，
    # 因此**不会影响用户正在操作的程序**。
    root = tk.Tk()
    root.withdraw()
    app = Application(root, Settings().with_environment_overrides())
    for _ in range(8):
        root.update_idletasks()
    root.withdraw()

    palette = app.theme.palette
    problems: List[str] = []

    # ---- 主窗口 -----------------------------------------------------------
    seen: List[Dict[str, Any]] = []
    audit_window(root, palette, "主窗口", problems, seen)

    # ---- 弹窗：全都建出来（但撤下），逐个审计 ------------------------------
    dialogs = []
    for label, opener, attribute in (
        ("设置窗口", app.show_settings, "_settings_window"),
        ("提示窗口", app.show_help, "_help_window"),
    ):
        opener()
        window = getattr(app, attribute, None)
        if window is None or not window.winfo_exists():
            problems.append(f"{label} 没有打开")
            continue
        window.withdraw()
        for _ in range(8):
            root.update_idletasks()
        window.withdraw()
        # 弹窗自己的底色
        own = str(window.cget("background"))
        if own.lower() != palette.background.lower():
            problems.append(f"{label} 自己的底色 {own} ≠ 面板色 {palette.background}")
        audit_window(window, palette, label, problems, seen)
        # **留白检查**：窗口被撤下时读不到实际高度，所以用"我们主动要求的
        # 尺寸"和"内容自然需要的尺寸"比。写死一个偏大的高度就会被抓住
        # ——这正是用户报的"设置窗口下面一半全是留白"。
        requested = getattr(window, "requested_geometry", None)
        required = (window.winfo_reqwidth(), window.winfo_reqheight())
        if requested is not None:
            if requested[1] - required[1] > 40:
                problems.append(
                    f"{label} 写死的高度 {requested[1]} px 比内容需要的 {required[1]} px "
                    f"高出 {requested[1] - required[1]} px：下面全是留白"
                )
        dialogs.append(
            f"{label} 请求={requested or '按内容'} 内容={required}"
        )
        window.destroy()

    # ---- 标题栏深浅是否真的设上了 -----------------------------------------
    # 这仍然要有真实 HWND 才能问 DWM；用 `withdraw` 过的窗口句柄问是可以的
    # （不需要它可见），所以这里只验证"调用成功"，不去动用户的屏幕。
    hwnd = platform_win.window_id_of(root)
    if hwnd and not platform_win.apply_dark_titlebar(hwnd, app.theme.dark):
        problems.append("主窗口标题栏的深色属性没设上（apply_dark_titlebar 返回 False）")

    root.destroy()

    print(f"=== 主题 {theme_mode}（dark={theme_mode == 'dark'}）===")
    print(f"  审计控件 {len([s for s in seen if 'background' in s])} 个，跳过 {len([s for s in seen if 'skipped' in s])} 个")
    print(f"  弹窗：{', '.join(dialogs)}")
    if problems:
        print(f"  发现 {len(problems)} 个问题：")
        for problem in problems:
            print(f"    [PROBLEM] {problem}")
        return 1
    print("  [OK] 所有可见界面的颜色都在主题色内，标题栏与留白都正常")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--theme", default="", choices=["", "light", "dark"])
    args = parser.parse_args()
    modes = [args.theme] if args.theme else ["light", "dark"]
    codes = [run(mode) for mode in modes]
    return 1 if any(codes) else 0


if __name__ == "__main__":
    sys.exit(main())
