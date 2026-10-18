"""从仓库直接运行 / PyInstaller 打包的入口。

文件名里带连字符不能当模块名，所以它只做一件事：把 ``src`` 放进
``sys.path``，然后把控制权交给 ``gui_of_edge_tts.bootstrap``。
"""

from __future__ import annotations

import os
import sys


def _ensure_src_on_path() -> None:
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    if getattr(sys, "frozen", False):
        # PyInstaller 把包收进 _MEIPASS；补充一次以防 pathex 未覆盖
        bundled = getattr(sys, "_MEIPASS", "")
        if bundled and bundled not in sys.path:
            sys.path.insert(0, bundled)


def main() -> int:
    _ensure_src_on_path()
    try:
        from gui_of_edge_tts.bootstrap import main as bootstrap_main

        return bootstrap_main()
    except SystemExit:
        raise
    except BaseException:  # noqa: BLE001 - **入口绝不能静默死掉**
        # 冻结成 windowed exe 之后没有控制台，未捕获的异常只会让窗口
        # 一闪而过（或干脆不出现），用户看到的是"双击没反应"。
        # 所以这里必须留一份可以事后查看的记录。
        import traceback

        text = traceback.format_exc()
        saved = ""
        try:
            from pathlib import Path

            target = Path(os.environ.get("TEMP", ".")) / "GUI-of-Edge-TTS-crash.log"
            target.write_text(text, encoding="utf-8")
            saved = str(target)
        except Exception:  # noqa: BLE001
            pass
        try:
            import tkinter as tk
            from tkinter import messagebox

            root = tk.Tk()
            root.withdraw()
            messagebox.showerror(
                "启动失败",
                text if not saved else f"{text}\n\n（已保存到 {saved}）",
            )
            root.destroy()
        except Exception:  # noqa: BLE001
            pass
        return 1


if __name__ == "__main__":
    sys.exit(main())
