"""Windows 平台细节：主题检测、DPI 感知、深色标题栏、资源路径。

**全部函数在非 Windows 或缺接口时安静降级**，绝不抛异常把界面带崩。
判据是"能回读到的值"，不是"调用没报错"（归档 `DevAesthetics` 第 22.3 节）。
"""

from __future__ import annotations

import ctypes
import os
import subprocess
import sys
from contextlib import contextmanager
from ctypes import wintypes
from pathlib import Path
from typing import Dict, Iterator, Optional, Tuple

IS_WINDOWS = sys.platform.startswith("win")

# 注册表：Windows 10 1809+ 的"应用使用浅色主题"，0 = 深色
_PERSONALIZE_KEY = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
_APPS_USE_LIGHT_THEME = "AppsUseLightTheme"
# 强调色（ABGR，低 24 位有效）
_DWM_KEY = r"Software\Microsoft\Windows\DWM"
_ACCENT_COLOR = "AccentColor"
_ACCENT_PALETTE = "AccentPalette"


@contextmanager
def suspend_redraw(widget) -> Iterator[None]:
    """冻结窗口（含子控件）的重绘，直到 ``with`` 块结束。

    语言切换会一次改很多按钮的文字与宽度。Tk 在两次布局之间可能把**中间
    状态**送到屏幕：旧按钮的像素会从新的缝隙里露出来，看起来像闪白条。
    这里用 Windows 的 ``LockWindowUpdate`` 把整段更新压成一帧：用户只看到
    切换前和切换后，没有中间态。``LockWindowUpdate`` 只锁一个窗口，且
    ``finally`` 一定解锁；拿不到句柄/非 Windows 时安静降级。
    """
    hwnd = 0
    locked = False
    if IS_WINDOWS:
        try:
            hwnd = int(widget.winfo_id())
        except Exception:  # noqa: BLE001 - 控件可能已销毁
            hwnd = 0
    if hwnd:
        try:
            user32 = ctypes.windll.user32
            # HWND 必须声明成指针宽：ctypes 默认按 c_int 传，64 位下会被截断。
            user32.LockWindowUpdate.argtypes = [wintypes.HWND]
            user32.LockWindowUpdate.restype = wintypes.BOOL
            locked = bool(user32.LockWindowUpdate(wintypes.HWND(hwnd)))
        except Exception:  # noqa: BLE001
            locked = False
    try:
        yield
    finally:
        if hwnd:
            try:
                user32 = ctypes.windll.user32
                user32.RedrawWindow.argtypes = [
                    wintypes.HWND,
                    ctypes.c_void_p,
                    ctypes.c_void_p,
                    wintypes.UINT,
                ]
                user32.RedrawWindow.restype = wintypes.BOOL
                if locked:
                    user32.LockWindowUpdate(None)
                # 解锁后强制擦掉旧像素，再把整棵控件树画一遍。
                user32.RedrawWindow(
                    wintypes.HWND(hwnd),
                    None,
                    None,
                    0x0001  # RDW_INVALIDATE
                    | 0x0004  # RDW_ERASE
                    | 0x0100  # RDW_UPDATENOW
                    | 0x0080,  # RDW_ALLCHILDREN
                )
            except Exception:  # noqa: BLE001
                pass


# --------------------------------------------------------------------------- #
# 主题
# --------------------------------------------------------------------------- #
def system_uses_dark_theme() -> bool:
    """系统当前是否"深色应用模式"。

    读不到时返回 ``False``（浅色）——浅色是这套配色的基准，
    猜错的代价只是观感，反过来猜错会让用户在亮环境里看不清。
    """
    if not IS_WINDOWS:
        return False
    try:
        import winreg  # pylint: disable=import-outside-toplevel

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _PERSONALIZE_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _APPS_USE_LIGHT_THEME)
        return int(value) == 0
    except (OSError, ValueError, ImportError):
        return False


def _accent_color_from_palette() -> Optional[str]:
    """从 ``AccentPalette`` 取强调色：8 组 RGB，第 7 组是"浅色下的强调色"。"""
    if not IS_WINDOWS:
        return None
    try:
        import winreg  # pylint: disable=import-outside-toplevel

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _DWM_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _ACCENT_PALETTE)
    except (OSError, ImportError):
        return None
    if not isinstance(value, (bytes, bytearray)) or len(value) < 28:
        return None
    # 第 7 组（下标 24..26，RGB 顺序）在浅色主题下最接近系统用的强调色
    red, green, blue = value[24], value[25], value[26]
    if (red, green, blue) == (0, 0, 0):
        return None
    return f"#{red:02X}{green:02X}{blue:02X}"


def system_accent_color() -> Optional[str]:
    """系统强调色 ``#RRGGBB``；读不到返回 ``None``（由主题自己定）。"""
    if not IS_WINDOWS:
        return None
    try:
        import winreg  # pylint: disable=import-outside-toplevel

        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _DWM_KEY) as key:
            value, _ = winreg.QueryValueEx(key, _ACCENT_COLOR)
        # AccentColor 是 ABGR：低三位是 R,G,B
        red = value & 0xFF
        green = (value >> 8) & 0xFF
        blue = (value >> 16) & 0xFF
        if red == 0 and green == 0 and blue == 0:
            return _accent_color_from_palette()
        return f"#{red:02X}{green:02X}{blue:02X}"
    except (OSError, ImportError, TypeError):
        return _accent_color_from_palette()


# --------------------------------------------------------------------------- #
# DPI
# --------------------------------------------------------------------------- #
def enable_dpi_awareness() -> str:
    """让进程按显示器 DPI 感知。**必须在创建 Tk 根窗口之前调用。**

    返回**实际生效**的模式名（查回来的，不是"我调用过"）。
    已经被清单/宿主设过时，`SetProcessDpiAwarenessContext` 会返回失败
    （ERROR_ACCESS_DENIED）；旧代码此时仍然报 `per-monitor-v2`，于是诊断
    信息会掩盖"实际不是这个模式"。
    """
    if not IS_WINDOWS:
        return "skipped"
    try:
        user32 = ctypes.windll.user32
        user32.SetProcessDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.SetProcessDpiAwarenessContext.restype = wintypes.BOOL
        if user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4)):
            return "per-monitor-v2"
    except (AttributeError, OSError):
        pass
    current = _process_awareness()
    if current not in ("unaware", "unknown", "skipped"):
        return current
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return _process_awareness()
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
        return _process_awareness()
    except (AttributeError, OSError):
        return "none"


def _process_awareness() -> str:
    """回读当前进程的 DPI 感知模式。"""
    if not IS_WINDOWS:
        return "skipped"
    try:
        value = ctypes.c_int(0)
        ctypes.windll.shcore.GetProcessDpiAwareness(None, ctypes.byref(value))
        return {0: "unaware", 1: "system", 2: "per-monitor"}.get(
            int(value.value), f"dpi-{int(value.value)}"
        )
    except (AttributeError, OSError):
        pass
    try:
        user32 = ctypes.windll.user32
        user32.GetThreadDpiAwarenessContext.restype = ctypes.c_void_p
        user32.GetAwarenessFromDpiAwarenessContext.argtypes = [ctypes.c_void_p]
        user32.GetAwarenessFromDpiAwarenessContext.restype = wintypes.DWORD
        context = user32.GetThreadDpiAwarenessContext()
        awareness = int(user32.GetAwarenessFromDpiAwarenessContext(context))
        return {0: "unaware", 1: "system", 2: "per-monitor"}.get(awareness, "unknown")
    except (AttributeError, OSError, ValueError):
        return "unknown"


def system_dpi() -> int:
    """系统 DPI；取不到按 96。"""
    if not IS_WINDOWS:
        return 96
    try:
        dpi = int(ctypes.windll.user32.GetDpiForSystem())
        return dpi if 48 <= dpi <= 480 else 96
    except (AttributeError, OSError):
        return 96


# --------------------------------------------------------------------------- #
# 深色标题栏 / 原生控件
# --------------------------------------------------------------------------- #
def apply_dark_titlebar(window_id: int, dark: bool) -> bool:
    """把窗口的非客户区（标题栏）设成深色。

    DWM 绘制的标题栏自绘客户区碰不到它，必须单独声明，且**要在窗口显示之前**
    （归档 `DevAesthetics` 第十节）。返回值是"真的设置成功了吗"。

    ⚠️ **``argtypes`` 必须声明**：不声明时 ctypes 按 ``c_int`` 传参，
    64 位下 HWND 会被截成 32 位，于是**每一次调用都返回
    ``E_HANDLE (0x80070006)``**——看起来像"这台机器不支持"，实际是
    "我把句柄传坏了"。这一条实测踩过：返回值一直是 False，而
    `DwmSetWindowAttribute` 一次都没真正执行过。
    """
    if not IS_WINDOWS or not window_id:
        return False
    try:
        dwmapi = ctypes.windll.dwmapi
    except (AttributeError, OSError):
        return False

    dwmapi.DwmSetWindowAttribute.argtypes = [
        wintypes.HWND,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    dwmapi.DwmSetWindowAttribute.restype = ctypes.c_long

    value = ctypes.c_int(1 if dark else 0)
    for attribute in (20, 19):  # 20 = Win11；19 = Win10 18985 之前
        try:
            result = dwmapi.DwmSetWindowAttribute(
                wintypes.HWND(window_id),
                wintypes.DWORD(attribute),
                ctypes.byref(value),
                ctypes.sizeof(value),
            )
        except (AttributeError, OSError, ctypes.ArgumentError):
            return False
        if result == 0:
            return True
    return False


def allow_dark_native_controls(dark: bool) -> bool:
    """让系统绘制的原生控件（滚动条、菜单、文件对话框）跟随深色。

    ``uxtheme.dll`` 的未公开导出 ``SetPreferredAppMode`` 是按**序号 135** 取的
    （按名字取不到）。0=跟随系统 1=允许深色 2=强制深色。
    必须在创建窗口之前调用。
    """
    if not IS_WINDOWS:
        return False
    try:
        uxtheme = ctypes.WinDLL("uxtheme")
        ordinal = getattr(uxtheme, "135", None)
        if ordinal is None:
            ordinal = uxtheme[135]
        ordinal.argtypes = [ctypes.c_int]
        ordinal.restype = ctypes.c_int
        ordinal(2 if dark else 0)
        return True
    except (AttributeError, OSError, KeyError):
        return False


# ---- 关于"蓝色焦点方框"的一条记录（不要删） ------------------------------
#
# 现象：点一下设置窗口里的开关，会冒出一个**蓝色方框**套在开关外。
#
# **试过、无效**：按 Win32 的规矩给那个 HWND 发
#     WM_UPDATEUISTATE = UIS_SET | UISF_ACTIVE | UISF_HIDEFOCUS
# 然后用 WM_QUERYUISTATE 回读 —— 回读到的 UISF_HIDEFOCUS 仍是 False。
# **回读没过就不算修好**，所以这条办法被否掉了。
#
# **真正管用的是**：把画布的 ``takefocus`` 设为 0 —— 不让 Tk 把原生焦点
# 交给那个 Canvas 窗口，系统也就没有"要画焦点框"的对象。
# 见 ``ui.FlatButton`` / ``ui.ToggleSwitch`` 里对应的注释。
# 键盘可达性由自绘的焦点态 + ``<space>`` / ``<Return>`` 绑定保证。


def focus_rect_suppressed(hwnd: int) -> bool:
    """回读"焦点矩形是否已被关掉"——**判据必须能被独立验证**。

    只检查 `suppress_focus_rect()` 返回 True 是不够的：那只能说明
    ``SendMessage`` 没抛异常。这里用 ``WM_QUERYUISTATE`` 问一次真实状态，
    确认 ``UISF_HIDEFOCUS`` 那一位确实被置上了。
    """
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        user32 = ctypes.windll.user32
        user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.SendMessageW.restype = wintypes.LPARAM
        state = user32.SendMessageW(wintypes.HWND(hwnd), WM_QUERYUISTATE, 0, 0)
        return bool(int(state) & UISF_HIDEFOCUS)
    except (AttributeError, OSError, ValueError):
        return False


def detach_visual_style(hwnd: int) -> bool:
    """摘掉子窗口的**视觉样式**，让系统不再给它画状态边框。

    用户实测反馈：点击某些自绘控件时，外面会冒出一圈**蓝色方框**。
    逐条排除的过程（每条都做了回读）：

    1. ``highlightthickness=0`` —— 已经是 0，不是 Tk 的 highlight；
    2. 我自己画的焦点圈 —— 已删除，图元清单里确认只剩 image；
    3. ``WM_UPDATEUISTATE`` 关 ``UISF_HIDEFOCUS`` —— **回读仍是 False，无效**；
    4. ``takefocus=0`` —— 只影响 Tk 的 Tab 遍历；``GetFocus()`` 更直接证明
       键盘焦点**从来没落在这些子窗口上**（它们没有 ``WS_TABSTOP``）。

    排除到这里，剩下的就是**视觉样式引擎**（``uxtheme``）：它对子窗口做
    "按压/激活"状态绘制时会补一圈边框。正解是把这个窗口从主题里摘出来
    ——``SetWindowTheme(hwnd, "", "")``，空主题 = 纯自绘、无主题装饰。
    对自绘控件这正是我们要的：本来就不需要系统画任何东西。
    """
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        uxtheme = ctypes.WinDLL("uxtheme")
        uxtheme.SetWindowTheme.argtypes = [
            wintypes.HWND,
            ctypes.c_wchar_p,
            ctypes.c_wchar_p,
        ]
        uxtheme.SetWindowTheme.restype = ctypes.c_long
        return uxtheme.SetWindowTheme(wintypes.HWND(hwnd), "", "") == 0
    except (AttributeError, OSError):
        return False


def window_id_of(widget) -> int:
    """取 Tk 控件的**顶层窗口句柄**（HWND）。

    ``winfo_id()`` 在控件还没映射到屏幕时会抛 ``TclError``，因此这里只捕获
    明确的两种情况；**不要用裸 ``except``**，否则真的缺陷会被吞掉。

    ⚠️ 拿到之后要沿 ``GetAncestor(GA_ROOT)`` 走一步：Tk 在 Windows 上会
    给 toplevel 套一层 wrapper，``winfo_id()`` 有时给的是**里面那个**句柄，
    而 DWM 只认真正的顶层窗口——用错的句柄调 ``DwmSetWindowAttribute``
    会一律返回 ``E_HANDLE (0x80070006)``，看起来像"系统不支持深色标题栏"。
    """
    try:
        import tkinter  # pylint: disable=import-outside-toplevel

        error = tkinter.TclError
    except ImportError:
        error = OSError
    try:
        handle = int(widget.winfo_id())
    except (AttributeError, ValueError, TypeError, error):
        return 0
    if not handle or not IS_WINDOWS:
        return handle
    try:
        user32 = ctypes.windll.user32
        # ⚠️ `restype` 不声明时 ctypes 按 c_int 返回——64 位下 HWND 会被截断，
        # 后续 DWM/WM_SETICON 全部用错句柄（本模块自己的 5.5 节踩过）。
        user32.GetAncestor.argtypes = [wintypes.HWND, wintypes.UINT]
        user32.GetAncestor.restype = wintypes.HWND
        GA_ROOT = 2
        root_handle = user32.GetAncestor(wintypes.HWND(handle), GA_ROOT)
        # `restype` 是 c_void_p 时 ctypes **返回 int 或 None**（不是 c_void_p 对象），
        # 所以不能再取 `.value`——那样会抛 AttributeError 被下面的 except 吞掉，
        # 悄悄退回内层句柄（DWM 又会拿到 E_HANDLE）。
        return int(root_handle or 0) or handle
    except (AttributeError, OSError, ValueError):
        return handle


class _MONITORINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("rcMonitor", wintypes.RECT),
        ("rcWork", wintypes.RECT),
        ("dwFlags", wintypes.DWORD),
    ]


MONITOR_DEFAULTTONEAREST = 2


def monitor_work_area(window_id: int) -> Optional[Tuple[int, int, int, int]]:
    """窗口所在显示器的可用区域 ``(left, top, right, bottom)``；拿不到返回 None。

    为什么不用 Tk 的 ``winfo_screenwidth/height``：那是**主显示器**的尺寸。
    主窗口在第二块屏上时，弹窗会被夹到主屏去；显示器在主屏左边/上边时
    坐标是负数，而旧代码里的 ``max(0, ...)`` 会把弹窗强行拉回 0。

    ⚠️ 只看 monitor work area（扣掉任务栏），不是整块屏幕。
    """
    if not IS_WINDOWS or not window_id:
        return None
    try:
        user32 = ctypes.windll.user32
        user32.MonitorFromWindow.argtypes = [wintypes.HWND, wintypes.DWORD]
        user32.MonitorFromWindow.restype = wintypes.HMONITOR
        user32.GetMonitorInfoW.argtypes = [
            wintypes.HMONITOR,
            ctypes.POINTER(_MONITORINFO),
        ]
        user32.GetMonitorInfoW.restype = wintypes.BOOL
        monitor = user32.MonitorFromWindow(
            wintypes.HWND(window_id), MONITOR_DEFAULTTONEAREST
        )
        if not monitor:
            return None
        info = _MONITORINFO()
        info.cbSize = ctypes.sizeof(_MONITORINFO)
        if not user32.GetMonitorInfoW(monitor, ctypes.byref(info)):
            return None
        rect = info.rcWork
        return (int(rect.left), int(rect.top), int(rect.right), int(rect.bottom))
    except (AttributeError, OSError, ValueError):
        return None


def set_window_icon(
    window_id: int,
    small_icon_path: str,
    big_icon_path: Optional[str] = None,
) -> tuple:
    """用 Win32 ``WM_SETICON`` 给窗口设置**按窗口 DPI 取尺寸**的图标。

    ``small_icon_path`` 是标题栏图标（按主题给 light/dark），
    ``big_icon_path`` 是任务栏/Alt-Tab 图标（默认主图标）。

    Tk 的 ``iconbitmap`` 在 Windows 上只选 ICO 里的一个帧，175% 缩放时
    系统要的是 28×28（标题栏）和 56×56（任务栏/Alt-Tab），不是标准的
    16/32/256；用单帧拉伸就会糊。这里让 ``LoadImageW`` 按系统真实尺寸
    取帧，再分别设置 ICON_SMALL / ICON_BIG。

    ⚠️ 尺寸按**窗口所在显示器**的 DPI 取（`GetDpiForWindow`），不是
    `GetSystemMetrics`（那个按系统 DPI）。混合 DPI 下两者不同。

    ⚠️ HICON 按"路径 + 尺寸"缓存：旧实现每个弹窗、每次换主题都重新
    ``LoadImageW`` 两个句柄，而且从不``DestroyIcon``——长会话里句柄一直涨。
    ``WM_SETICON`` 不接管所有权，同一个 HICON 可以给多个窗口共用，
    所以缓存是安全的；每个组合只加载一次，句柄随进程结束回收。

    返回句柄元组（调用方持有引用即可，Tk 窗口不拥有它们）。
    """
    if not IS_WINDOWS or not window_id:
        return ()
    big_path = big_icon_path or small_icon_path
    small_size = _icon_metric(SM_CXSMICON, window_id) or 16
    big_size = _icon_metric(SM_CXICON, window_id) or 32
    key = (small_icon_path, big_path, small_size, big_size)
    handles = _ICON_CACHE.get(key)
    if handles is None:
        handles = _load_icon_pair(small_icon_path, big_path, small_size, big_size)
        if len(handles) == 2:
            _ICON_CACHE[key] = handles
    if handles:
        _apply_window_icons(window_id, handles)
    return handles


#: `SM_CXSMICON` / `SM_CXICON`
SM_CXSMICON = 49
SM_CXICON = 11

#: (小图标路径, 大图标路径, 小尺寸, 大尺寸) → (HICON, HICON)
_ICON_CACHE: Dict[Tuple[str, str, int, int], Tuple[int, ...]] = {}


def _icon_metric(index: int, window_id: int) -> int:
    """按**窗口所在显示器**的 DPI 取系统图标边长。"""
    if not IS_WINDOWS:
        return 0
    try:
        user32 = ctypes.windll.user32
        user32.GetDpiForWindow.argtypes = [wintypes.HWND]
        user32.GetDpiForWindow.restype = wintypes.UINT
        dpi = int(user32.GetDpiForWindow(wintypes.HWND(window_id)))
        if dpi > 0:
            user32.GetSystemMetricsForDpi.argtypes = [ctypes.c_int, wintypes.UINT]
            user32.GetSystemMetricsForDpi.restype = ctypes.c_int
            size = int(user32.GetSystemMetricsForDpi(index, dpi))
            if size > 0:
                return size
    except (AttributeError, OSError, ValueError):
        pass
    try:
        return int(ctypes.windll.user32.GetSystemMetrics(index))
    except (AttributeError, OSError):
        return 0


def _load_icon_pair(
    small_path: str, big_path: str, small_size: int, big_size: int
) -> Tuple[int, ...]:
    """按目标尺寸从 ICO 里取帧。任何失败都返回已取到的句柄（可能为空）。"""
    try:
        user32 = ctypes.windll.user32
        user32.LoadImageW.argtypes = [
            wintypes.HINSTANCE,
            wintypes.LPCWSTR,
            wintypes.UINT,
            ctypes.c_int,
            ctypes.c_int,
            wintypes.UINT,
        ]
        user32.LoadImageW.restype = wintypes.HICON
        LR_LOADFROMFILE = 0x10
        IMAGE_ICON = 1
        small = user32.LoadImageW(
            None, small_path, IMAGE_ICON, small_size, small_size, LR_LOADFROMFILE
        )
        big = user32.LoadImageW(
            None, big_path, IMAGE_ICON, big_size, big_size, LR_LOADFROMFILE
        )
        return tuple(int(handle or 0) for handle in (small, big) if handle)
    except (AttributeError, OSError, ValueError):
        return ()


def _apply_window_icons(window_id: int, handles: Tuple[int, ...]) -> None:
    try:
        user32 = ctypes.windll.user32
        user32.SendMessageW.argtypes = [
            wintypes.HWND,
            wintypes.UINT,
            wintypes.WPARAM,
            wintypes.LPARAM,
        ]
        user32.SendMessageW.restype = wintypes.LPARAM
        WM_SETICON = 0x0080
        if len(handles) >= 1:
            user32.SendMessageW(wintypes.HWND(window_id), WM_SETICON, 0, handles[0])
        if len(handles) >= 2:
            user32.SendMessageW(wintypes.HWND(window_id), WM_SETICON, 1, handles[1])
    except (AttributeError, OSError, ValueError):
        pass


# --------------------------------------------------------------------------- #
# 控制台输出（打包成 windowed exe 之后没有 stdout）
# --------------------------------------------------------------------------- #
ATTACH_PARENT_PROCESS = -1
STD_OUTPUT_HANDLE = -11
STD_ERROR_HANDLE = -12
FILE_TYPE_PIPE = 3
FILE_TYPE_DISK = 1

#: ``WM_UPDATEUISTATE`` / ``WM_QUERYUISTATE`` 用的常量。
#: 名字取 Win32 的原文，免得看代码的人要去查"2 和 1 是什么意思"。
UIS_SET = 2
UISF_ACTIVE = 0x4
UISF_HIDEFOCUS = 0x1
WM_UPDATEUISTATE = 0x0129
WM_QUERYUISTATE = 0x012A


def _stream_from_std_handle(which: int):
    """把标准句柄包成 Python 流；句柄不可用时返回 ``None``。

    这一步是修下面这个真 bug 的关键：

    **PyInstaller 的 windowed 启动器不给子进程任何标准句柄**
    （``GetStdHandle`` 返回 0/NULL），而且 ``sys.stdout`` 是 ``None``。
    所以"检查 sys.stdout"永远判定"没有输出方向"——可父进程明明做了
    ``> out.log`` 或管道。

    做法：先把标准句柄**绑成 C 运行时的 fd**（``msvcrt.open_osfhandle``），
    再用 ``os.fdopen`` 包成文本流。这样父进程的管道/重定向文件就能收到输出，
    冻结态、源码态**同一条路径**。
    """
    import msvcrt  # pylint: disable=import-outside-toplevel

    kernel32 = ctypes.windll.kernel32
    # `GetStdHandle` 的返回值是 HANDLE（指针宽）；不声明 restype 时默认 c_int，
    # 64 位下高 32 位会被截掉——而且 INVALID_HANDLE_VALUE 的比较高下永远不成立。
    kernel32.GetStdHandle.argtypes = [wintypes.DWORD]
    kernel32.GetStdHandle.restype = wintypes.HANDLE
    handle = kernel32.GetStdHandle(which)
    if not handle or handle == wintypes.HANDLE(-1).value:
        return None
    kind = ctypes.windll.kernel32.GetFileType(wintypes.HANDLE(handle))
    if kind not in (FILE_TYPE_PIPE, FILE_TYPE_DISK):
        return None
    try:
        fd = msvcrt.open_osfhandle(handle, os.O_WRONLY)
    except OSError:
        return None
    try:
        return os.fdopen(fd, "w", encoding="utf-8", errors="replace", buffering=1)
    except OSError:
        return None


def attach_parent_console() -> bool:
    """让这个进程有地方可写：控制台、或父进程的管道/重定向文件。

    返回是否成功。**这是"双击的 windowed exe 里 print() 会炸"的正解**，
    而且它顺带修掉了一个更隐蔽的形态：父进程用 ``> out.log`` 收集输出时，
    第一版把它误判成"没有输出方向"，于是程序算完了却一个字都不输出。
    """
    if not IS_WINDOWS:
        return False

    # 1) 先试控制台：这样在 cmd / PowerShell 里跑能**实时**看到输出
    try:
        ctypes.windll.kernel32.AttachConsole(ATTACH_PARENT_PROCESS)
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.kernel32.SetConsoleOutputCP(65001)
    except (AttributeError, OSError):
        pass
    try:
        console_out = open("CONOUT$", "w", encoding="utf-8", buffering=1)  # noqa: SIM115
        console_err = open("CONOUT$", "w", encoding="utf-8", buffering=1)  # noqa: SIM115
    except OSError:
        console_out = console_err = None

    if console_out is not None:
        sys.stdout, sys.stderr = console_out, console_err
        return True

    # 2) 没有控制台（重定向/管道）：用父进程留下的标准句柄
    piped_out = _stream_from_std_handle(STD_OUTPUT_HANDLE)
    piped_err = _stream_from_std_handle(STD_ERROR_HANDLE)
    if piped_out is None and piped_err is None:
        return False
    if piped_out is not None:
        sys.stdout = piped_out
    if piped_err is not None:
        sys.stderr = piped_err
    return True


def console_available() -> bool:
    """现在写 stdout 会不会炸。"""
    return sys.stdout is not None and hasattr(sys.stdout, "write")


def has_output_stream() -> bool:
    """有没有**任何**可以写的地方。

    判据是"这个流能不能写"，不是"它是不是控制台"——父进程用 ``> out.log``
    或管道收集输出时没有控制台，但那明明是可以写的。

    ⚠️ 注意：在 PyInstaller 的 windowed 冻结态里，这一条**恒为假**
    （启动器不给子进程标准句柄，``sys.stdout`` 就是 ``None``），
    所以真正管用的是 :func:`attach_parent_console` ——它会去要父进程的句柄。
    """
    stream = sys.stdout
    if stream is None or not hasattr(stream, "write"):
        return False
    try:
        stream.write("")
    except (OSError, ValueError, AttributeError):
        return False
    return True


def force_utf8_streams() -> None:
    """把 stdout/stderr 钉成 UTF-8。

    **冻结成 windowed exe 之后，流的编码是"跟随区域设置"的**——中文 Windows 上
    就是 GBK。于是中文输出在管道/文件里变成乱码，而**正是这些输出要拿来
    让用户截图报障**。显式钉成 UTF-8 之后，``--selftest > 文件`` 才是可读的。
    """
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8", errors="replace")
        except (OSError, ValueError, AttributeError):
            pass


def silence_missing_streams() -> None:
    """把"没有 stdout"变成"写了也没事"。

    **冻结成 windowed exe 之后，``sys.stdout`` 是 ``None``**，
    任何一句 ``print()`` 都会抛异常——而崩溃点往往在启动路径上，
    表现成"双击没反应"。这里塞一个吞掉一切的替身，
    让诊断输出变成无害的东西，而不是让程序起不来。
    """
    if getattr(sys, "frozen", False) and sys.stdout is None:
        import io  # pylint: disable=import-outside-toplevel

        sink = io.StringIO()
        sys.stdout = sink
        sys.stderr = sink


def report(message: str) -> None:
    """只有在真的能写的时候才写。

    给"诊断输出"用：**它不该有能力把程序弄崩**。真正的结果走状态栏与对话框。
    """
    stream = sys.stdout
    if stream is None:
        return
    try:
        print(message, file=stream, flush=True)
    except (OSError, ValueError, AttributeError):
        pass


# --------------------------------------------------------------------------- #
# 资源与外壳交互
# --------------------------------------------------------------------------- #
def resource_path(relative: str) -> str:
    """资源绝对路径。

    **从源码运行时按"仓库里的相对位置"找**（归档 `projects/File-tracker.md`
    第五节：重写时丢掉这一步 ⇒ 从源码运行必然没有图标）。
    """
    candidates = []
    if getattr(sys, "frozen", False):
        base = getattr(sys, "_MEIPASS", None)
        if base:
            candidates.append(Path(base) / relative)
        candidates.append(Path(sys.executable).parent / relative)
    package_root = Path(__file__).resolve().parent          # …/src/gui_of_edge_tts
    repo_root = package_root.parent.parent                  # …/<repo>
    candidates.append(repo_root / relative)
    candidates.append(package_root / relative)
    candidates.append(Path.cwd() / relative)
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return str(candidates[0] if candidates else relative)


def reveal_in_explorer(path: str, select: bool = False) -> bool:
    """在资源管理器里打开（或选中）某个路径。"""
    target = Path(path)
    if not IS_WINDOWS:
        return False
    try:
        if select and target.exists():
            # **不要用 `subprocess.run`**：它会等 explorer 退出。用户机器上
            # Explorer 没在跑/启动慢时，这一句会把界面线程一起卡住。
            subprocess.Popen(["explorer", "/select,", str(target)])
        else:
            folder = str(target if target.is_dir() else target.parent)
            os.startfile(folder)  # type: ignore[attr-defined]  # noqa: S606
        return True
    except (OSError, AttributeError):
        return False
