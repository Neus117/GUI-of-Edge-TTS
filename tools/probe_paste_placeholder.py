"""复现"粘贴内容之后，生成说编辑区是空的"。

**判据是用户真实走的路径**：不是 `text.insert()`，而是

* 真剪贴板 + 真实的 `<<Paste>>` 事件（Ctrl+V）
* 真实的 `<<Modified>>` 通知链
* 真实的校验入口

不猜，只看每一步回读到的值。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))

os.environ["ETTS_THEME"] = "light"

import tkinter as tk  # noqa: E402

from gui_of_edge_tts import platform_win  # noqa: E402
from gui_of_edge_tts.settings import Settings  # noqa: E402
from gui_of_edge_tts.ui import Application  # noqa: E402

PAYLOAD = "Hello from the clipboard. This should be pasted."


def pump(root, times: int = 6) -> None:
    # **只用 update_idletasks**：`update()` 会处理输入事件，而窗口停在屏幕外，
    # 处理输入既没必要也可能把焦点拉过来。事件用 `event_generate` 直接投递，
    # 不依赖真实焦点。
    for _ in range(times):
        root.update_idletasks()


def observe(app, label: str) -> None:
    print(
        f"  [{label}] placeholder_active={app._placeholder_active} "
        f"edit_modified={app.text.edit_modified()} "
        f"get_text()={app.get_text()!r} "
        f"widget={app.text.get('1.0', 'end')!r}"
    )


def main() -> int:
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
    from _probe_window import park, verify_offscreen

    platform_win.enable_dpi_awareness()
    root = tk.Tk()
    app = Application(root, Settings())
    # 窗口停到屏幕外：能收键盘事件，但用户看不到、也抢不走焦点
    park(root, 1000, 760)
    verify_offscreen()
    pump(root)

    print("=== 初始状态 ===")
    observe(app, "初始")

    failures = []

    # ---- 用户动作一：Ctrl+V（真实剪贴板 + 真实事件） ----------------------
    root.clipboard_clear()
    root.clipboard_append(PAYLOAD)
    root.update_idletasks()
    # **不调 focus_force()**：那会把焦点从用户正在用的窗口抢过来。
    # Tk 的 `<<Paste>>` 只要求"目标控件是这个顶层窗口里的输入焦点"，
    # 窗口停在屏幕外、焦点在本进程内部就够了。
    app.text.focus_set()
    pump(root)
    app.text.event_generate("<<Paste>>")
    pump(root, 10)
    print("=== 按 Ctrl+V 之后 ===")
    observe(app, "粘贴后")

    if PAYLOAD not in app.get_text():
        failures.append("Ctrl+V 之后 get_text() 里没有剪贴板内容")
    if "把要朗读的文字" in app.get_text():
        failures.append("Ctrl+V 之后占位提示还在，会混进用户内容")
    if app._placeholder_active:
        failures.append("Ctrl+V 之后 _placeholder_active 仍然是 True")
    validated = app._validate()
    if validated is None:
        failures.append("Ctrl+V 之后校验仍然说编辑区是空的")
    else:
        print(f"  → 校验通过，文本长度 {len(validated[0])}")

    # ---- 用户动作二：在已有内容后面继续输入 -------------------------------
    app.text.insert("end", " 追加一句")
    pump(root, 6)
    print("=== 追加输入之后 ===")
    observe(app, "追加后")
    if "追加一句" not in app.get_text():
        failures.append("追加输入之后内容不对")
    if "把要朗读的文字" in app.get_text():
        failures.append("追加输入之后占位提示又混进来了")

    # ---- 用户动作三：清空之后再粘贴 ---------------------------------------
    app.clear_text()
    pump(root, 6)
    print("=== 清空之后 ===")
    observe(app, "清空后")
    if not app._placeholder_active:
        failures.append("清空之后占位提示没有回来")
    if app.get_text() != "":
        failures.append("清空之后 get_text() 不是空的（占位提示被当成内容）")

    app.text.event_generate("<<Paste>>")
    pump(root, 10)
    print("=== 清空后再粘贴 ===")
    observe(app, "清空后粘贴")
    if PAYLOAD not in app.get_text():
        failures.append("清空后再粘贴拿不到内容")
    if app._placeholder_active:
        failures.append("清空后再粘贴，占位状态没清掉")

    # ---- 用户动作四：用鼠标中键/菜单粘贴（<<Paste>> 的另一条路） ----------
    app.clear_text()
    pump(root)
    app.text.event_generate("<<Paste>>", x=10, y=10)
    pump(root, 10)
    print("=== 清空后再粘贴（带坐标） ===")
    observe(app, "带坐标粘贴")
    if app._placeholder_active:
        failures.append("带坐标粘贴之后占位状态没清掉")

    verify_offscreen()
    root.destroy()

    print()
    if failures:
        print(f"复现成功：{len(failures)} 个问题")
        for item in failures:
            print(f"  - {item}")
        return 1
    print("没有复现出问题（说明缺陷在别的路径上）")
    return 0


if __name__ == "__main__":
    sys.exit(main())
