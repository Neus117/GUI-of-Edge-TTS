"""版位自检的**阳性对照**：确认它真的会拦住被裁掉的内容。

判据是"回读到的值"，不是"我觉得没问题"——而一个检查器"返回通过"
和"根本没有检查这一项"在输出里长得一模一样（归档 `02` 第 26.4 节），
所以这里造两种必然出问题的情形，确认 :meth:`Application.layout_findings`
真的会报出来。

用法::

    python tools/probe_layout_negative.py
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


def build_app() -> tuple:
    # **窗口停到屏幕外**：这个探针要"让它真的去检查一次"，但不需要用户看见
    import sys as _sys
    from pathlib import Path as _Path

    _sys.path.insert(0, str(_Path(__file__).resolve().parent))
    from _probe_window import park

    platform_win.enable_dpi_awareness()
    root = tk.Tk()
    app = Application(root, Settings())
    park(root, 1320, 792)
    return root, app


def main() -> int:
    failures = []

    # ---- 阳性一：占位文字比控件高 -----------------------------------------
    root, app = build_app()
    try:
        app.text.delete("1.0", "end")
        app.text.insert("1.0", "\n".join(f"第 {index} 行" for index in range(1, 40)))
        app._placeholder_active = True  # noqa: SLF001 - 装作这就是占位符
        for _ in range(3):
            root.update_idletasks()
        findings = app.layout_findings()
        hit = any(
            "占位文字放不下" in item or "placeholder does not fit" in item.lower()
            for item in findings
        )
        print(f"  [{'OK  ' if hit else 'FAIL'}] 阳性：占位文字被裁掉 — {findings[:1]}")
        if not hit:
            failures.append("占位文字溢出")
    finally:
        root.destroy()

    # ---- 阳性二：提示条文字比容器宽 ---------------------------------------
    root, app = build_app()
    try:
        app.settings.show_hints = True
        long_text = "这一句话故意写得非常非常长" * 8
        app.help_strip_text.configure(text=long_text)
        # 布局探针读的是**方法返回的当前文案**（真实界面用的那句），
        # 所以这里临时替换方法，而不是去改已删除的类常量。
        original = app._hint_strip_text
        app._hint_strip_text = lambda: long_text
        for _ in range(3):
            root.update_idletasks()
        findings = app.layout_findings()
        app._hint_strip_text = original
        hit = any(
            "提示条文字需要" in item or "Hint strip needs" in item
            for item in findings
        )
        print(f"  [{'OK  ' if hit else 'FAIL'}] 阳性：提示条文字被截断 — {findings[:1]}")
        if not hit:
            failures.append("提示条截断")
    finally:
        root.destroy()

    # ---- 阴性：正常状态不能报 ---------------------------------------------
    root, app = build_app()
    try:
        findings = app.layout_findings()
        print(f"  [{'OK  ' if not findings else 'FAIL'}] 阴性：正常界面没有问题 — {findings[:1]}")
        if findings:
            failures.append("正常界面被误报")
    finally:
        root.destroy()

    print()
    if failures:
        print(f"阳性/阴性对照未通过：{', '.join(failures)}")
        return 1
    print("阳性被拦、阴性放过：版位自检确实在跑")
    return 0


if __name__ == "__main__":
    sys.exit(main())
