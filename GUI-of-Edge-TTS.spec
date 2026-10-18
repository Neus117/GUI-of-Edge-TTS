# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller 打包配置。

**路径一律相对这个文件推**，不写死开发机的绝对路径——否则换一台机器、
换一个检出目录就打不出包（归档 `02` 第 27.3 节）。

用法（推荐走 build.ps1，它会先生成 ``src/gui_of_edge_tts/_build.py``）::

    pyinstaller --noconfirm GUI-of-Edge-TTS.spec
"""

import os
import sys
from pathlib import Path

# PyInstaller 在执行 spec 时会注入 SPECPATH；`__file__` 在新的 PyInstaller 里
# 也成立。两个都试一遍，取第一个能用的——**不要写死盘符**。
try:
    REPO = os.path.abspath(os.path.dirname(__file__))
except NameError:  # pragma: no cover - 只在老版本 PyInstaller 里发生
    REPO = os.path.abspath(SPECPATH)  # noqa: F821

SRC = os.path.join(REPO, "src")
ENTRY = os.path.join(SRC, "GUI-of-Edge-TTS.py")
VERSION_FILE = os.path.join(REPO, "version.txt")
ICON = os.path.join(REPO, "images", "Edge-TTS.ico")
LIGHT_ICON = os.path.join(REPO, "images", "Edge-TTS_light.ico")
DARK_ICON = os.path.join(REPO, "images", "Edge-TTS_dark.ico")


def tcl_tk_payload():
    """收集 Tcl/Tk 的 DLL。

    **DLL 这一步不能省。** conda 环境把 ``tcl86t.dll`` / ``tk86t.dll`` 放在
    ``Library/bin``，而 PyInstaller 的 tkinter hook 按标准 cpython 布局
    （DLLs / tcl 子目录）去找——**分析阶段不报缺，运行时才炸**：

        ImportError: DLL load failed while importing _tkinter: 找不到指定的模块

    所以这里显式把 DLL 放到包根目录；与 hook 添加的同名文件会自动去重。

    Tcl/Tk 的脚本库**不再手工复制**：PyInstaller 6 的 Tcl/Tk hook 已经生成
    ``_tcl_data`` / ``_tk_data``。旧配置又把它们复制到 ``_internal/tcl``，
    单文件包里会多出一份约 0.8 MB 的重复数据。
    """
    prefix = Path(getattr(sys, "base_prefix", sys.prefix))

    search = [prefix / "Library" / "bin", prefix / "DLLs", prefix]
    wanted = ["tcl86t.dll", "tk86t.dll", "zlib.dll"]
    binaries = []
    for name in wanted:
        for folder in search:
            candidate = folder / name
            if candidate.exists():
                binaries.append((str(candidate), "."))
                break
    return binaries


TCL_TK_BINARIES = tcl_tk_payload()

a = Analysis(  # noqa: F821
    [ENTRY],
    pathex=[SRC],
    binaries=TCL_TK_BINARIES,
    # 图标要打进包里：resource_path() 在冻结态会去 _MEIPASS 下找它。
    # 目的目录用 images/，与仓库里的相对位置保持一致。
    datas=[(ICON, "images"), (LIGHT_ICON, "images"), (DARK_ICON, "images")],
    hiddenimports=[],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    # edge-tts 只用 aiohttp / certifi / tabulate / typing_extensions；
    # 下面这些是界面用不到的重量级包，明确排除可以省下十几 MB。
    # **不要排除 setuptools**：aiohttp 的若干 hook 依赖 pkg_resources，
    # 排掉之后在别的机器上会以"缺模块"的形式炸掉。
    excludes=[
        "PyQt5",
        "PyQt6",
        "PySide2",
        "PySide6",
        "matplotlib",
        "numpy",
        "pandas",
        "scipy",
        "pytest",
        "IPython",
    ],
    noarchive=False,
    optimize=0,
)

pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="GUI-of-Edge-TTS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # UPX 会让杀毒软件误报，而且省不了多少
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version=VERSION_FILE,
    icon=[ICON],
)
