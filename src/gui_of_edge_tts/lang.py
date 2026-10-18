"""界面语言：中文 / English。

这里照搬 File Tracker 的 ``lang.py`` 纪律：

**每条用户可见的文案都写成 ``L("中文", "English")``，两半都在调用点。**
不做资源键查找——键漏了只会把键名或空白显示给用户；两个参数在语法上
强制同时存在，一条消息不可能只翻译一半。

语言偏好存在设置里；没有偏好时看 Windows 的**用户界面语言**
（``GetUserDefaultUILanguage``），不看时区。
"""

from __future__ import annotations

import ctypes
import os

PREFERENCE_AUTO = ""
PREFERENCE_CHINESE = "zh"
PREFERENCE_ENGLISH = "en"

#: 设置里可选的顺序。**语言名用自己的语言写，不翻译。**
CHOICES = (PREFERENCE_CHINESE, PREFERENCE_ENGLISH)
DISPLAY_NAMES = {
    PREFERENCE_CHINESE: "中文",
    PREFERENCE_ENGLISH: "English",
}

LANGUAGE_CHINESE = 0x04
_chinese: bool | None = None


def _detect_from_environment() -> bool:
    value = os.environ.get("ETTS_LANG", "").strip().lower()
    if value in (PREFERENCE_CHINESE, "zh-cn", "zh_cn", "chinese"):
        return True
    if value in (PREFERENCE_ENGLISH, "en-us", "en_us", "english"):
        return False
    for name in ("LANG", "LC_ALL", "LC_MESSAGES"):
        value = os.environ.get(name, "").strip().lower()
        if value.startswith(("zh", "chinese")):
            return True
    return False


def _detect_from_system() -> bool:
    """Windows 当前用户的界面语言是不是中文；失败时默认英文。"""
    override = os.environ.get("ETTS_LANG", "").strip().lower()
    if override:
        return _detect_from_environment()
    try:
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
    except (AttributeError, OSError):
        return _detect_from_environment()
    return (int(lang_id) & 0xFF) == LANGUAGE_CHINESE


def apply(preference: str | None) -> bool:
    """应用设置里的偏好；空值/未知值表示跟随系统。"""
    global _chinese
    if preference == PREFERENCE_CHINESE:
        _chinese = True
    elif preference == PREFERENCE_ENGLISH:
        _chinese = False
    else:
        _chinese = _detect_from_system()
    return _chinese


def is_chinese() -> bool:
    global _chinese
    if _chinese is None:
        _chinese = _detect_from_system()
    return _chinese


def current_preference() -> str:
    return PREFERENCE_CHINESE if is_chinese() else PREFERENCE_ENGLISH


def preference(chinese: bool) -> str:
    return PREFERENCE_CHINESE if chinese else PREFERENCE_ENGLISH


def pick(chinese: str, english: str) -> str:
    return chinese if is_chinese() else english


class _Pick:
    def __call__(self, chinese: str, english: str) -> str:
        return pick(chinese, english)


#: 调用点统一写 ``L("中文", "English")``。
L = _Pick()

__all__ = [
    "CHOICES",
    "DISPLAY_NAMES",
    "L",
    "LANGUAGE_CHINESE",
    "PREFERENCE_AUTO",
    "PREFERENCE_CHINESE",
    "PREFERENCE_ENGLISH",
    "apply",
    "current_preference",
    "is_chinese",
    "pick",
    "preference",
]
