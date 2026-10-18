"""版本与构建标识。

一份代码只有一个权威来源：``APP_VERSION`` 在源码里写死，构建脚本在打标签前
检查它与 git 标签一致；打包时由构建脚本把提交哈希写进 ``_build.py``，
因此发行版能自报"我是哪个提交构建的"（见归档 `02` 第 26.2 ②）。
"""

from __future__ import annotations

import os
import sys

APP_NAME = "GUI-of-Edge-TTS"
APP_DISPLAY_NAME = "Edge-TTS"
APP_VERSION = "2.0.1"
APP_URL = "https://github.com/Neus117/GUI-of-Edge-TTS"

_UNKNOWN_COMMIT = "unknown"


def _read_build_commit() -> str:
    """读取构建时注入的提交哈希。

    开发态（从源码运行）去问 git；冻结态读打包进来的 ``_build.py``。
    两者都拿不到时返回 ``unknown``，**不要猜**。
    """
    try:
        from . import _build  # type: ignore[attr-defined]  # pylint: disable=import-outside-toplevel

        commit = getattr(_build, "COMMIT", "")
        if commit:
            return str(commit)
    except ImportError:
        pass

    if getattr(sys, "frozen", False):
        return _UNKNOWN_COMMIT

    try:
        import subprocess  # pylint: disable=import-outside-toplevel

        here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        result = subprocess.run(
            ["git", "-C", here, "rev-parse", "--short", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        commit = result.stdout.strip()
        if result.returncode == 0 and commit:
            return commit
    except (OSError, subprocess.SubprocessError):  # type: ignore[name-defined]
        pass
    return _UNKNOWN_COMMIT


def version_string() -> str:
    """形如 ``Edge-TTS 2.0.1+ae4a6f4``。"""
    return f"{APP_DISPLAY_NAME} {APP_VERSION}+{_read_build_commit()}"
