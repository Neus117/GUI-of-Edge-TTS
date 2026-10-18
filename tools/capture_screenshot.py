"""抓一张真实窗口的截图，供人工核对观感。

**为什么是 Python 而不是 PowerShell**：本机只有 Windows PowerShell 5.1，
它对中文注释/字符串的编码处理会莫名其妙地失败（本工具的第一版就是这么废掉的）。
Python 没有这个问题，而且它本来就装在这台机器上。

``--print`` 额外把窗口尺寸、客户区尺寸和几个控件的实际几何打成一行 JSON，
便于把"我以为摆对了"变成"回读到的坐标是多少"。

用法::

    python tools/capture_screenshot.py --exe <python.exe> --args "..." --out shot.png --settle 9
"""

from __future__ import annotations

import argparse
import ctypes
import json
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

try:
    from PIL import ImageGrab
except ImportError:  # pragma: no cover - 正常环境里应该装了 Pillow
    ImageGrab = None  # type: ignore[assignment]

USER32 = ctypes.windll.user32
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW = 0x00000080
SW_RESTORE = 9
HWND_TOPMOST = -1
HWND_NOTOPMOST = -2
SWP_NOSIZE = 0x0001
SWP_NOMOVE = 0x0002
DEFAULT_DESKTOP_DPI = 96

# 本进程是 DPI 未感知的，而目标窗口是 Per-Monitor V2（175% 缩放）。
# 不声明"我也感知 DPI"的话，GetWindowRect 返回的是**逻辑虚拟坐标**，
# 而屏幕抓图要的是物理像素——直接抓就会抓错位置（第一版抓出来的是
# 窗口右半边和旁边的资源管理器）。
try:
    ctypes.windll.user32.SetThreadDpiAwarenessContext(ctypes.c_void_p(-4))
    _DPI_AWARE = True
except (AttributeError, OSError):
    _DPI_AWARE = False

WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)


class RECT(ctypes.Structure):
    _fields_ = [
        ("left", ctypes.c_long),
        ("top", ctypes.c_long),
        ("right", ctypes.c_long),
        ("bottom", ctypes.c_long),
    ]


def window_pid(hwnd: int) -> int:
    pid = wintypes.DWORD()
    USER32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def window_title(hwnd: int) -> str:
    length = USER32.GetWindowTextLengthW(hwnd)
    buffer = ctypes.create_unicode_buffer(length + 1)
    USER32.GetWindowTextW(hwnd, buffer, length + 1)
    return buffer.value


def is_visible(hwnd: int) -> bool:
    if not USER32.IsWindowVisible(hwnd):
        return False
    ex_style = USER32.GetWindowLongW(hwnd, GWL_EXSTYLE)
    if ex_style & WS_EX_TOOLWINDOW:
        return False
    return bool(window_title(hwnd))


def process_tree(root_pid: int) -> set:
    """``root_pid`` 以及它的全部后代进程号。

    **PyInstaller onefile 是两个进程**：bootloader 父进程没有窗口，
    真正有窗口的是它拉起来的子进程（归档 `02` 第十七节、错误九形状一）。
    只按"启动时拿到的那个 pid"找窗口，会永远找不到——第一版就是这么
    判定"exe 起不来窗口"的。
    """
    TH32CS_SNAPPROCESS = 0x00000002
    INVALID = ctypes.c_void_p(-1).value

    class PROCESSENTRY32(ctypes.Structure):
        _fields_ = [
            ("dwSize", wintypes.DWORD),
            ("cntUsage", wintypes.DWORD),
            ("th32ProcessID", wintypes.DWORD),
            ("th32DefaultHeapID", ctypes.POINTER(ctypes.c_ulong)),
            ("th32ModuleID", wintypes.DWORD),
            ("cntThreads", wintypes.DWORD),
            ("th32ParentProcessID", wintypes.DWORD),
            ("pcPriClassBase", ctypes.c_long),
            ("dwFlags", wintypes.DWORD),
            ("szExeFile", ctypes.c_char * 260),
        ]

    kernel32 = ctypes.windll.kernel32
    snapshot = kernel32.CreateToolhelp32Snapshot(TH32CS_SNAPPROCESS, 0)
    if snapshot == INVALID:
        return {root_pid}
    parents = {}
    try:
        entry = PROCESSENTRY32()
        entry.dwSize = ctypes.sizeof(PROCESSENTRY32)
        if kernel32.Process32First(snapshot, ctypes.byref(entry)):
            while True:
                parents[int(entry.th32ProcessID)] = int(entry.th32ParentProcessID)
                if not kernel32.Process32Next(snapshot, ctypes.byref(entry)):
                    break
    finally:
        kernel32.CloseHandle(snapshot)

    tree = {root_pid}
    changed = True
    while changed:
        changed = False
        for pid, parent in parents.items():
            if parent in tree and pid not in tree:
                tree.add(pid)
                changed = True
    return tree


def find_window(pids, wanted_title: str = "", timeout: float = 30.0, root_pid: int = 0) -> int:
    """按进程号找可见顶层窗口。**只认窗口，不认进程存活**。

    ``root_pid`` 给定时，**每一轮都重新算一次进程树**——PyInstaller onefile
    的子进程是在启动后几秒才出现的，只算一次会永远看不到它
    （第一版就是这么又判断了一次"exe 起不来窗口"的）。
    """
    if isinstance(pids, int):
        pids = {pids}
    pids = set(pids)
    deadline = time.monotonic() + timeout
    while True:
        if root_pid:
            pids = process_tree(root_pid)
        found: list[int] = []

        def callback(hwnd, _lparam):
            if window_pid(hwnd) in pids and is_visible(hwnd):
                found.append(hwnd)
            return True

        USER32.EnumWindows(WNDENUMPROC(callback), 0)
        if wanted_title:
            titled = [h for h in found if wanted_title in window_title(h)]
            if titled:
                return titled[0]
        if found:
            return found[0]
        if time.monotonic() >= deadline:
            return 0
        time.sleep(0.3)


def click_window(hwnd: int) -> None:
    """在那个窗口上模拟一次点击。

    这是绕过"前台锁定"的正规做法：Windows 允许"用户点过的窗口"抢前台。
    副作用是把焦点给了被测程序——这正是我们要的（焦点环也能拍进去）。
    """
    rect = RECT()
    USER32.GetWindowRect(hwnd, ctypes.byref(rect))
    x = (rect.left + rect.right) // 2
    y = rect.top + 12  # 标题栏上按一下，不会点到输入框里
    USER32.SetCursorPos(x, y)
    USER32.mouse_event(0x0002, 0, 0, 0, 0)  # LEFTDOWN
    USER32.mouse_event(0x0004, 0, 0, 0, 0)  # LEFTUP
    time.sleep(0.2)


VK_ESCAPE = 0x1B
KEYEVENTF_KEYUP = 0x0002

VK_BY_NAME = {
    "f1": 0x70,
    "esc": VK_ESCAPE,
    "escape": VK_ESCAPE,
    "enter": 0x0D,
    "return": 0x0D,
    "space": 0x20,
}

MODIFIER_VK = {"ctrl": 0x11, "control": 0x11, "shift": 0x10, "alt": 0x12}


def press_keys(hwnd: int, spec: str) -> None:
    """往窗口发一串按键，例如 ``f1``、``ctrl+o``。

    **先把焦点给那个窗口**：不然按键会落到当前前台窗口上——
    那就成了"测了别的东西"，正是这一轮栽过的那类错。

    焦点靠 `SetForegroundWindow` 拿不到时（系统对"不是前台的进程"会忽略它），
    退回到"在那个窗口上点一下"——那是 Windows 认可的用户动作。

    ⚠️ 点击**必须先做**：`GetForegroundWindow() == hwnd` 并不代表"这个窗口
    的控件拿到了键盘焦点"（焦点可能还在别的进程里）。第一版把点击放进了
    条件分支，于是条件不成立时一次点击都没有，F1 直接落空。
    """
    click_window(hwnd)
    USER32.SetForegroundWindow(hwnd)
    time.sleep(0.5)
    if USER32.GetForegroundWindow() != hwnd:
        print(f"WARN: 前台窗口不是目标窗口（实际 {USER32.GetForegroundWindow()}），按键可能落空")

    codes = []
    for part in (piece.strip().lower() for piece in spec.split("+")):
        if not part:
            continue
        if part in MODIFIER_VK:
            codes.append(MODIFIER_VK[part])
        elif len(part) == 1:
            codes.append(int(USER32.VkKeyScanA(ord(part))) & 0xFF)
        elif part in VK_BY_NAME:
            codes.append(VK_BY_NAME[part])
        else:
            raise SystemExit(f"不认识的按键：{part}")
    for code in codes:
        USER32.keybd_event(code, 0, 0, 0)
    for code in reversed(codes):
        USER32.keybd_event(code, 0, KEYEVENTF_KEYUP, 0)
    time.sleep(0.8)


def window_exe_path(hwnd: int) -> str:
    """拥有这个窗口的进程的**可执行文件全路径**。

    **这一条是防止"量错了对象"的**：机器上同时开着别的版本时，光看
    "窗口标题是 Edge-TTS" 会把别人的窗口当成自己的（实测栽过一次：
    抓到一扇 891×938 的旧界面，还据此推断"打包打错了"）。
    判据必须是"这个窗口的程序就是我启动的那个文件"。
    """
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, window_pid(hwnd))
    if not handle:
        return ""
    try:
        size = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(size.value)
        if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
            return buffer.value
        return ""
    finally:
        kernel32.CloseHandle(handle)


def windows_of(pids) -> list:
    """指定进程集合下的全部可见顶层窗口（hwnd, pid, title）。"""
    pids = {pids} if isinstance(pids, int) else set(pids)
    found: list = []

    def callback(hwnd, _lparam):
        if window_pid(hwnd) in pids and is_visible(hwnd):
            found.append((hwnd, window_pid(hwnd), window_title(hwnd)))
        return True

    USER32.EnumWindows(WNDENUMPROC(callback), 0)
    return found


def capture_printwindow(hwnd: int, width: int, height: int):
    """用 ``PrintWindow`` 把窗口自己画一遍，**不需要它在最前面**。

    ``PW_RENDERFULLCONTENT`` (2) 是给 DWM 合成窗口用的那个标志。归档里
    （`DevAesthetics` 22.1）在 wxPython 上它返回过乱码，所以这里必须
    **和屏幕抓图的结果对照**：两条路都存一份，比对像素差异。
    """
    from PIL import Image

    window_dc = USER32.GetWindowDC(hwnd)
    gdi32 = ctypes.windll.gdi32
    memory_dc = gdi32.CreateCompatibleDC(window_dc)
    bitmap = gdi32.CreateCompatibleBitmap(window_dc, width, height)
    gdi32.SelectObject(memory_dc, bitmap)
    try:
        ok = USER32.PrintWindow(hwnd, memory_dc, 2)
        if not ok:
            print("PrintWindow returned 0")
        buffer = ctypes.create_string_buffer(width * height * 4)

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", ctypes.c_uint32),
                ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16),
                ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32),
                ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32),
                ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32),
            ]

        header = BITMAPINFOHEADER()
        header.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        header.biWidth = width
        header.biHeight = -height  # 负数 = 自上而下
        header.biPlanes = 1
        header.biBitCount = 32
        header.biCompression = 0  # BI_RGB
        gdi32.GetDIBits(memory_dc, bitmap, 0, height, buffer, ctypes.byref(header), 0)
        return Image.frombuffer("RGBA", (width, height), buffer, "raw", "BGRA", 0, 1).convert("RGB")
    finally:
        gdi32.DeleteObject(bitmap)
        gdi32.DeleteDC(memory_dc)
        USER32.ReleaseDC(hwnd, window_dc)


def get_window_rect(hwnd: int, scale_to_physical: bool) -> tuple:
    """返回 (left, top, width, height)。``scale_to_physical`` 为真时按窗口 DPI 缩放。

    两种模式都要留着：``SetThreadDpiAwarenessContext`` 在某些 Windows 版本上
    会失败，那时 ``GetWindowRect`` 给的是**逻辑虚拟坐标**，而屏幕抓图要物理像素。
    反正拿到手就打印出来，和窗口自报的尺寸一对照就知道用的是哪一种
    （见 `tools/README-capture.md`）。
    """
    rect = RECT()
    USER32.GetWindowRect(hwnd, ctypes.byref(rect))
    left, top = rect.left, rect.top
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if not scale_to_physical:
        return left, top, width, height
    dpi = int(USER32.GetDpiForWindow(hwnd)) or DEFAULT_DESKTOP_DPI
    factor = dpi / 96.0
    return (
        int(round(left * factor)),
        int(round(top * factor)),
        int(round(width * factor)),
        int(round(height * factor)),
    )


GENERIC_INTERPRETERS = {"python.exe", "pythonw.exe", "py.exe", "pwsh.exe", "powershell.exe"}

#: 这个工具会打开真实窗口、并把它带到前台（截真实像素需要）。
#: 2026-10-17 起用户允许在 DeepSeek 专用桌面上这么做；`--allow-visible`
#: 只是"确认你确实要可见截图"的开关，不再是用户授权门槛。
VISIBLE_INTERRUPTION_NOTE = """
这个工具会在屏幕上**开一扇真实窗口**，并且为了拍到最前面会模拟点击、
把窗口带到前台（Windows 下截真实像素需要这么做）。

请先确认 DeepSeek Harness 在 **DeepSeek 专用桌面**上（见 `00` 硬性约束 ⑤）：
在这个桌面上，用户已经允许打开可见窗口、截图、抢焦点。

确认后加 --allow-visible 运行（它只是确认开关，不是授权门槛）：

    python tools/capture_screenshot.py --allow-visible --exe ... --out shot.png

只想核对"颜色/尺寸/版位对不对"的话**不需要它**：
    python tools/audit_theme_surfaces.py      # 全部界面的反色一致性
    python tools/ui_layout_probe.py           # 几何与配色
这两个工具用屏幕外窗口，更快、不闪。
"""


def kill_stale_copies(exe_name: str) -> None:
    """起飞前清掉**同名**进程。

    机器上残留的同名实例会让 ``windows_of`` / ``process_tree`` 里混进别人的
    窗口，于是抓到的、量的都不是我启动的那个。实测因为残留 6 个实例，
    连续两次抓图以退出码 127 中途失败，还差点得出"打包打错了"的错误结论。

    ⚠️ **绝不按解释器名清理**：从源码抓图时 ``--exe`` 就是 ``python.exe``，
    一句 ``taskkill /F /IM python.exe`` 会把**正在跑的这个脚本自己**杀掉——
    症状是"安静退出、一行输出都没有"，而退出码看起来像正常失败。
    这个坑实测踩过一次，所以这里显式排除通用解释器名。
    """
    if exe_name.lower() in GENERIC_INTERPRETERS:
        print(f"skip stale-kill for generic interpreter {exe_name}")
        return
    try:
        subprocess.run(["taskkill", "/F", "/IM", exe_name], capture_output=True, check=False)
    except Exception:  # noqa: BLE001
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="capture a running window")
    parser.add_argument("--exe", required=True)
    parser.add_argument("--args", default="")
    parser.add_argument("--out", required=True)
    parser.add_argument("--settle", type=float, default=8.0,
                        help="固定等待秒数；与 --wait-window 同时给出时以 --wait-window 为先")
    parser.add_argument("--wait-window", type=float, default=0.0,
                        help="最多等这么多秒直到窗口真的出现（判据是窗口，不是进程存活）")
    parser.add_argument("--title", default="Edge-TTS")
    parser.add_argument(
        "--window",
        default="",
        help="抓这个标题的窗口而不是主窗口（例如『设置』/『使用提示』）",
    )
    parser.add_argument("--env", action="append", default=[], help="NAME=VALUE")
    parser.add_argument("--place", default="", help="X,Y：抓到之后把窗口挪到这个位置")
    parser.add_argument(
        "--method",
        default="screen",
        choices=["screen", "printwindow"],
        help="screen = 抓屏幕对应区域（窗口必须在最前）；printwindow = 让窗口自己画一遍",
    )
    parser.add_argument(
        "--keys",
        action="append",
        default=[],
        help="启动后发一串按键（例如 f1），再抓图；可给多次",
    )
    parser.add_argument(
        "--allow-visible",
        action="store_true",
        dest="allow_visible",
        help="确认要打开可见窗口并抢焦点（专用桌面上允许；不加这一条则只打印说明）",
    )
    parser.add_argument("--print", action="store_true", dest="dump")
    args = parser.parse_args()

    if not args.allow_visible:
        print(VISIBLE_INTERRUPTION_NOTE)
        return 2

    env = None
    if args.env:
        import os

        env = dict(os.environ)
        for item in args.env:
            name, _, value = item.partition("=")
            env[name] = value

    command = [args.exe]
    if args.args:
        command += args.args.split()

    # 起飞前先清掉同名进程（见 kill_stale_copies 的说明）
    kill_stale_copies(Path(args.exe).name)

    print("launching:", " ".join(command))
    process = subprocess.Popen(command, env=env)  # noqa: S603

    exit_code = 1
    hwnd = 0
    try:
        if args.wait_window:
            # 判据是**窗口出现了**，不是"进程还活着"——归档 01 错误六、
            # 错误七都在这一条上栽过。留一点时间让控件画完第一帧。
            started = time.monotonic()
            hwnd = find_window(
                set(), args.title, timeout=args.wait_window, root_pid=process.pid
            )
            waited = time.monotonic() - started
            if not hwnd:
                print(
                    f"FAILED: {args.wait_window:.0f} 秒内没有出现窗口"
                    f"（进程树 {sorted(process_tree(process.pid))}）"
                )
                return 1
            print(f"window appeared after {waited:.1f}s（进程树 {sorted(process_tree(process.pid))}）")
            time.sleep(args.settle)
        else:
            time.sleep(args.settle)
            hwnd = find_window(set(), args.title, timeout=25.0, root_pid=process.pid)
        if not hwnd:
            print(f"FAILED: 没找到 pid={process.pid} 的可见窗口")
            return 1

        USER32.ShowWindow(hwnd, SW_RESTORE)
        # ``SetForegroundWindow`` 对"不是前台的进程"会被系统忽略，于是屏幕上
        # 别的窗口压在上面，抓到的是别人的画面（第一版抓到的就是资源管理器）。
        # 真正管用的两条：先点一下那个窗口（模拟用户点击，解除前台锁定），
        # 再把它设为前台并置顶一段时间。
        if args.method == "screen":
            click_window(hwnd)
            time.sleep(0.8)
            USER32.SetForegroundWindow(hwnd)
            USER32.BringWindowToTop(hwnd)
            USER32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE)
            time.sleep(1.5)
        elif args.place:
            # PrintWindow 不需要在最前，但**窗口要被映射才有内容**。
            # 挪位置时**保留窗口自己的尺寸**：写死尺寸会把窗口缩小，
            # 于是拍到的不是你交付的那个界面（实测把 1320x792 压成了 890x760）。
            current_left, current_top, current_w, current_h = get_window_rect(
                hwnd, scale_to_physical=not _DPI_AWARE
            )
            px, py = (int(v) for v in args.place.split(","))
            USER32.MoveWindow(hwnd, px, py, current_w, current_h, True)
            time.sleep(1.0)

        # 需要拍**某个指定的弹窗**时（例如 `--settings` 打开的那一扇）：
        # 按标题去找它，而不是抓主窗口。
        if args.window:
            wanted = args.window
            found = 0
            for _ in range(40):
                time.sleep(0.25)
                candidates = [
                    item
                    for item in windows_of(process_tree(process.pid))
                    if wanted in item[2]
                ]
                if candidates:
                    found = candidates[-1][0]
                    break
            if not found:
                print(f"FAILED: 没找到标题含 {wanted!r} 的窗口")
                return 1
            hwnd = found
            print(f"target window: hwnd={hwnd} title={window_title(hwnd)!r}")
            time.sleep(1.0)

        left, top, width, height = get_window_rect(hwnd, scale_to_physical=not _DPI_AWARE)
        if args.place and not args.window:
            px, py = (int(v) for v in args.place.split(","))
            USER32.MoveWindow(hwnd, px, py, width, height, True)
            time.sleep(1.0)
            left, top = px, py

        # 需要拍"用户按了某个键之后"的窗口（比如 F1 那个使用提示）
        for spec in args.keys:
            # 先记下**按键之前**就存在的窗口：提示窗口是按键之后才出现的，
            # 拿"当时所有窗口"去找新窗口会把主窗口自己也当成新的。
            before = {item[0] for item in windows_of(process_tree(process.pid))}
            press_keys(hwnd, spec)
            print(f"sent keys: {spec}")
            opened = []
            for _ in range(20):
                time.sleep(0.25)
                opened = [
                    item
                    for item in windows_of(process_tree(process.pid))
                    if item[0] not in before
                ]
                if opened:
                    break
            if opened:
                hwnd = opened[-1][0]
                print(f"new window: hwnd={hwnd} title={window_title(hwnd)!r}")
            else:
                # 把**当时所有可见窗口**打出来：只报"没有新窗口"看不出是
                # "窗口没开"还是"我的筛子没看见它"（归档 01 错误九）。
                print("WARN: 按键之后没有出现新窗口；当时的可见窗口：")
                for item in windows_of(process_tree(process.pid)):
                    print(f"    hwnd={item[0]} pid={item[1]} title={item[2]!r}")
            time.sleep(0.8)
            left, top, width, height = get_window_rect(hwnd, scale_to_physical=not _DPI_AWARE)

        box = (left, top, left + width, top + height)
        actual_exe = window_exe_path(hwnd)
        print(
            f"window hwnd={hwnd} pid={window_pid(hwnd)} {width}x{height} box={box} "
            f"title={window_title(hwnd)!r} dpi_aware={_DPI_AWARE}"
        )
        print(f"window exe = {actual_exe}")
        # 启动的东西与我量的东西必须是同一个文件。不是就**直接失败**——
        # 否则下一步的结论会建立在一个别人的窗口上。
        if actual_exe and Path(actual_exe).name.lower() != Path(args.exe).name.lower():
            print(f"FAILED: 抓到的是另一个程序的窗口（{Path(actual_exe).name} ≠ {Path(args.exe).name}）")
            return 1

        if args.dump:
            client = RECT()
            USER32.GetClientRect(hwnd, ctypes.byref(client))
            print(
                "geometry "
                + json.dumps(
                    {
                        "box": list(box),
                        "client": [client.right, client.bottom],
                        "dpi": int(USER32.GetDpiForWindow(hwnd)),
                        "dpi_aware": _DPI_AWARE,
                    }
                )
            )

        if ImageGrab is None:
            print("FAILED: 没有 Pillow，无法抓图")
            return 1
        target = Path(args.out)
        target.parent.mkdir(parents=True, exist_ok=True)
        if args.method == "printwindow":
            image = capture_printwindow(hwnd, width, height)
            note = "PrintWindow(PW_RENDERFULLCONTENT)"
        else:
            image = ImageGrab.grab(bbox=box, all_screens=True)
            note = "screen"
        image.save(target)
        print(
            f"saved {target} ({image.size[0]}x{image.size[1]}, {target.stat().st_size} bytes, "
            f"method={note}, distinct_colors={len(image.convert('RGB').getcolors(maxcolors=200000) or [])})"
        )
        exit_code = 0
    except BaseException:  # noqa: BLE001 - 打包/启动期的任何异常都要说出来
        # **不要静默死掉**：这个脚本本身是"仪器"，它崩了却不出声，
        # 就会变成"我量不到"被读成"那东西不存在"（归档 01 错误七）。
        import traceback

        traceback.print_exc()
        exit_code = 1
    finally:
        try:
            if hwnd:
                USER32.SetWindowPos(hwnd, HWND_NOTOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE)
        except Exception:  # noqa: BLE001
            pass
        try:
            process.terminate()
            process.wait(timeout=8)
        except Exception:  # noqa: BLE001
            try:
                process.kill()
            except Exception:  # noqa: BLE001
                pass
        # **PyInstaller onefile 是两个进程**：bootloader 父进程被杀掉之后，
        # 真正带窗口的子进程还在（归档 02 第十七节）。**不收尾就会把窗口
        # 留在用户屏幕上**（归档 01 错误六）。所以按进程名再扫一遍。
        try:
            subprocess.run(
                ["taskkill", "/F", "/IM", Path(args.exe).name],
                capture_output=True,
                check=False,
            )
        except Exception:  # noqa: BLE001
            pass
        print("cleaned up")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
