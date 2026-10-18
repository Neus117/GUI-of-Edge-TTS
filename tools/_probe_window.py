"""探针专用：把 Tk 窗口放到**屏幕外**，读几何又不闪。

## 为什么默认停到屏幕外

2026-10-17 起这**不是必须遵守的禁令**：用户准备了 DeepSeek 专用桌面，
允许在那里开可见窗口（见 `00` 硬性约束 ⑤ / `tools/README.md`）。
但屏幕外仍然是门禁与无人测试的首选——窗口不会闪、不会抢焦点、更快。

几何探针需要窗口被**真正映射**过一次，否则
``winfo_width()`` / ``winfo_height()``（实际分配到的空间）读不到。
只 ``withdraw()`` 的话布局根本不会算。

## 做法

把窗口映射到屏幕坐标 **(-4000, -4000)**：

* 对 Windows 来说它是"可见窗口"（``IsWindowVisible`` 为真），
  所以 Tk 会正常走一遍布局，几何量都是真的；
* 但它**落在屏幕之外**，用户看不到，也不会出现在任务栏；
* 我们**不调** ``focus_force()`` / ``lift()``，所以不会抢走用户正在用的窗口的焦点。

## 判据

``verify_offscreen()`` 会去枚举本进程的可见窗口，确认它们都在屏幕外。
加探针的时候顺手调一次——**"我以为它不碍事"不算验证**。
"""

from __future__ import annotations

import ctypes
import os
from ctypes import wintypes
from typing import List, Tuple

#: 屏幕外的落点。离屏幕足够远，任何显示器布局下都在可见区域之外。
OFFSCREEN = -4000

USER32 = ctypes.windll.user32
WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


def park(window, width: int = 0, height: int = 0) -> None:
    """把窗口挪到屏幕外并映射一次，让 Tk 算出真实布局。

    ``width`` / ``height`` 给了就同时设定尺寸；不给就只挪位置。
    """
    for _ in range(4):
        window.update_idletasks()
    if width and height:
        window.geometry(f"{int(width)}x{int(height)}+{OFFSCREEN}+{OFFSCREEN}")
    else:
        window.geometry(f"+{OFFSCREEN}+{OFFSCREEN}")
    window.deiconify()          # 映射，让布局真正发生
    for _ in range(6):
        window.update_idletasks()
    # 再挪一次：Tk 在映射时可能按"需要的尺寸"重算过位置
    if width and height:
        window.geometry(f"{int(width)}x{int(height)}+{OFFSCREEN}+{OFFSCREEN}")
    else:
        window.geometry(f"+{OFFSCREEN}+{OFFSCREEN}")
    for _ in range(4):
        window.update_idletasks()


def visible_windows_on_screen(pid: int = 0) -> List[Tuple[str, int, int, int, int]]:
    """本进程里**真正落在屏幕范围内**的可见窗口。

    "不打扰用户"的判据就是这个列表为空——不是"我觉得它在屏幕外"。
    """
    target = pid or os.getpid()
    screen_left, screen_top = USER32.GetSystemMetrics(76), USER32.GetSystemMetrics(77)
    screen_right = screen_left + USER32.GetSystemMetrics(78)
    screen_bottom = screen_top + USER32.GetSystemMetrics(79)
    found: List[Tuple[str, int, int, int, int]] = []

    def callback(hwnd, _lparam):
        owner = wintypes.DWORD()
        USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner))
        if owner.value != target or not USER32.IsWindowVisible(hwnd):
            return True
        length = USER32.GetWindowTextLengthW(hwnd)
        buffer = ctypes.create_unicode_buffer(length + 1)
        USER32.GetWindowTextW(hwnd, buffer, length + 1)
        rect = wintypes.RECT()
        USER32.GetWindowRect(hwnd, ctypes.byref(rect))
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        # 只要有一部分落在可见屏幕内就算"会打扰用户"
        if rect.right > screen_left and rect.left < screen_right and rect.bottom > screen_top and rect.top < screen_bottom:
            found.append((buffer.value, rect.left, rect.top, width, height))
        return True

    USER32.EnumWindows(WNDENUMPROC(callback), 0)
    return found


def verify_offscreen() -> bool:
    """断言本进程没有窗口出现在屏幕上。探针开头/结尾各调一次。"""
    intruders = visible_windows_on_screen()
    if intruders:
        print("  [FAIL] 有窗口出现在屏幕上（会打断用户）：")
        for title, x, y, width, height in intruders:
            print(f"         {title!r} at ({x},{y}) {width}x{height}")
        return False
    print("  [OK  ] 本进程没有窗口出现在屏幕上")
    return True
