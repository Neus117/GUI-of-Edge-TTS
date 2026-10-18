"""给控件挂一个悬停提示。

**为什么需要**：为了给提示条让出宽度，标题栏上的按钮改成了图标。
图标按钮不带文字，就必须有别的办法说清"点了会发生什么"——
否则它是一颗"看起来能点却不知道是什么"的按钮（规范 20.7 的反面）。

Tk 没有原生 tooltip，所以这里自己做一个：一个无边框的 ``Toplevel``，
悬停 400 ms 后出现在指针下方。**不需要任何第三方包。**

颜色一律从传进来的 :class:`~gui_of_edge_tts.theme.Theme` 取——
这里**没有兜底色**：兜底就意味着深浅主题下会有一处颜色对不上。
"""

from __future__ import annotations

from typing import Optional

from . import platform_win

DELAY_MS = 400


class Tooltip:
    """一个悬停提示。**每个控件一个实例**，绑好之后不用管它。"""

    def __init__(self, widget, text: str, theme) -> None:
        self.widget = widget
        self.text = text
        self.theme = theme
        self._window = None
        self._after_id: Optional[str] = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")

    def update(self, text: str = "", theme=None) -> None:
        if text:
            self.text = text
        if theme is not None:
            self.theme = theme
        self._hide()

    # ---- 内部 --------------------------------------------------------------

    def _schedule(self, _event=None) -> None:
        self._cancel()
        self._after_id = self.widget.after(DELAY_MS, self._show)

    def _cancel(self) -> None:
        if self._after_id is not None:
            try:
                self.widget.after_cancel(self._after_id)
            except Exception:  # noqa: BLE001 - 控件可能已经被销毁
                pass
            self._after_id = None

    def _show(self) -> None:
        if self._window is not None or not self.text:
            return
        import tkinter as tk  # pylint: disable=import-outside-toplevel

        try:
            x = self.widget.winfo_rootx()
            y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        except tk.TclError:
            return
        palette = self.theme.palette
        window = tk.Toplevel(self.widget)
        window.withdraw()
        window.wm_overrideredirect(True)
        window.wm_geometry(f"+{x}+{y}")
        window.configure(background=palette.surface_hover)
        label = tk.Label(
            window,
            text=self.text,
            background=palette.surface_hover,
            foreground=palette.text,
            borderwidth=0,
            highlightthickness=1,
            highlightbackground=palette.border,
            highlightcolor=palette.border,
            padx=self.theme.px(4),
            pady=self.theme.px(1),
            font=self.theme.font(9),
        )
        label.pack()
        with platform_win.suspend_redraw(window):
            window.deiconify()
            window.update_idletasks()
            # 贴近屏幕右/下边缘的按钮：提示框会有一半在屏幕外。量完自身尺寸
            # 后夹回**该显示器**的可用区域（含任务栏）。
            width = max(1, window.winfo_reqwidth())
            height = max(1, window.winfo_reqheight())
            try:
                hwnd = self.widget.winfo_id()
            except tk.TclError:
                hwnd = 0
            work = platform_win.monitor_work_area(hwnd)
            if work is None:
                work = (
                    0,
                    0,
                    self.widget.winfo_screenwidth(),
                    self.widget.winfo_screenheight(),
                )
            left, work_top, right, bottom = work
            x = min(max(left, x), max(left, right - width - 4))
            y = min(max(work_top, y), max(work_top, bottom - height - 4))
            window.wm_geometry(f"+{x}+{y}")
            window.update_idletasks()
        self._window = window

    def _hide(self, _event=None) -> None:
        self._cancel()
        if self._window is not None:
            try:
                self._window.destroy()
            except Exception:  # noqa: BLE001
                pass
            self._window = None
