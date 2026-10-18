"""用户设置的读写。

**一处权威来源**：配置文件是唯一真相，界面只读它、只写它。
路径固定在 ``%APPDATA%\\GUI-of-Edge-TTS\\settings.json``（打包与否都一样），
这样从源码运行和从 exe 运行共享同一份偏好。

写入一律"先写临时文件再替换"，避免归档里出现过的那类缺陷：
**写到一半失败 ⇒ 半截文件 ⇒ 下次解析失败 ⇒ 所有偏好丢失**
（见 `projects/File-tracker.md` 第九节的数据安全缺陷）。
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path
from typing import Any, Optional

APP_DIR_NAME = "GUI-of-Edge-TTS"
SETTINGS_FILE_NAME = "settings.json"

THEME_SYSTEM = "system"
THEME_LIGHT = "light"
THEME_DARK = "dark"
THEMES = (THEME_SYSTEM, THEME_LIGHT, THEME_DARK)


def config_dir() -> Path:
    """配置目录。优先 ``%APPDATA%``；拿不到就退回用户主目录。"""
    base = os.environ.get("APPDATA") or os.environ.get("XDG_CONFIG_HOME")
    if base:
        return Path(base) / APP_DIR_NAME
    return Path.home() / f".{APP_DIR_NAME.lower()}"


def config_path() -> Path:
    return config_dir() / SETTINGS_FILE_NAME


def default_output_dir() -> str:
    """默认输出目录：优先"音乐"文件夹，退回桌面，再退回用户主目录。"""
    home = Path.home()
    for candidate in (home / "Music", home / "Desktop", home):
        if candidate.is_dir():
            return str(candidate)
    return str(home)


@dataclass
class Settings:
    """全部偏好。**新增字段必须给默认值**，否则老配置文件会读不出来。"""

    voice: str = ""
    rate: str = "0"
    volume: str = "0"
    pitch: str = "0"
    theme: str = THEME_SYSTEM
    language: str = ""
    output_dir: str = ""
    last_file_name: str = ""
    show_hints: bool = True
    proxy: str = ""
    #: 被环境变量（``ETTS_THEME`` / ``ETTS_LANG``）临时覆盖的字段 → 覆盖前的值。
    #: **不参与序列化**：这些变量是给截图/探针用的，关窗时不能把测试值写进
    #: 用户配置（否则跑一次深色截图，用户的主题就永久变成深色了）。
    _overridden: dict = field(default_factory=dict, repr=False, compare=False)

    # ---- 读写 --------------------------------------------------------------

    @staticmethod
    def _archive_bad(target: Path) -> None:
        """把读不出来的配置留档成 ``settings.json.bad``。

        **不能静默丢掉**：用户手改过的配置是唯一的一份，直接返回默认值
        再在下一次保存时覆盖，等于"设置凭空没了"。
        """
        try:
            target.replace(target.with_suffix(".json.bad"))
        except OSError:
            pass

    @classmethod
    def load(cls, path: Optional[Path] = None) -> "Settings":
        """读设置。文件不存在或内容损坏时返回默认值，**不抛异常**。

        损坏的那份会被改名成 ``settings.json.bad`` 留档：用户的下一次保存
        才有东西可查，直接吞掉会让人以为"我的设置凭空没了"。
        """
        target = path or config_path()
        try:
            # `utf-8-sig` 接受带 BOM 的 UTF-8：Windows 记事本和部分编辑器会写
            # BOM，而 `utf-8` 读到 BOM 时 json 会报"Expecting value"——
            # 一份**完全正确**的配置会被当成坏文件扔掉。
            raw = target.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            # PowerShell 5.1 的 `Out-File` 默认写 UTF-16LE（带 BOM）。
            # 先按 UTF-16 读一次；读不出来就留档，**不覆盖原文件**。
            try:
                raw = target.read_text(encoding="utf-16")
            except (OSError, UnicodeError):
                # `UnicodeDecodeError` 是 `UnicodeError` 的子类；utf-16 在
                # 没有 BOM 时抛的是基类 `UnicodeError`，两个都要接住。
                cls._archive_bad(target)
                return cls()
        except OSError:
            return cls()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            cls._archive_bad(target)
            return cls()
        if not isinstance(data, dict):
            return cls()
        known = {f.name for f in fields(cls) if not f.name.startswith("_")}
        clean = {k: v for k, v in data.items() if k in known}
        settings = cls(**clean)  # type: ignore[arg-type]
        settings.validate()
        return settings

    def save(self, path: Optional[Path] = None) -> Path:
        """原子写。失败抛 :class:`OSError`（或 :class:`UnicodeError`），由调用方提示。"""
        self.validate()
        target = path or config_path()
        target.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(self._persisted(), ensure_ascii=False, indent=2)
        handle, tmp_name = tempfile.mkstemp(
            dir=str(target.parent), prefix=".settings-", suffix=".tmp"
        )
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(tmp_name, target)
        except (OSError, UnicodeError):
            # 孤立代理项之类的内容会在 write 时抛 `UnicodeEncodeError`。
            # 不清掉临时文件的话，`%APPDATA%` 里会慢慢堆满 `.settings-*.tmp`。
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        return target

    def _persisted(self) -> dict:
        """真正要写进配置文件的字典：**环境变量的临时覆盖写回原值**。"""
        data = asdict(self)
        data.pop("_overridden", None)
        for name, original in self._overridden.items():
            if name in data:
                data[name] = original
        return data

    def validate(self) -> None:
        """把不合法的值收敛到合法值，**不报错**。

        设置文件是用户可编辑的，一个手改坏的值不该让程序起不来。
        """
        if self.theme not in THEMES:
            self.theme = THEME_SYSTEM
        if self.language not in ("", "zh", "en"):
            self.language = ""
        if not isinstance(self.output_dir, str) or not self.output_dir:
            self.output_dir = default_output_dir()
        if not isinstance(self.voice, str):
            self.voice = ""
        if not isinstance(self.last_file_name, str):
            self.last_file_name = ""
        if not isinstance(self.proxy, str):
            self.proxy = ""
        self.show_hints = bool(self.show_hints)
        if not isinstance(self._overridden, dict):
            self._overridden = {}
        for name in ("rate", "volume", "pitch"):
            value = getattr(self, name)
            if isinstance(value, (int, float)):
                setattr(self, name, str(value))
            elif not isinstance(value, str):
                setattr(self, name, "0")

    def resolved_output_dir(self) -> str:
        """输出目录；不存在时退回默认目录（用户删掉了那个文件夹也一样能用）。"""
        candidate = self.output_dir or default_output_dir()
        try:
            if Path(candidate).is_dir():
                return candidate
        except OSError:
            pass
        return default_output_dir()

    def proxy_or_none(self) -> Optional[str]:
        value = (self.proxy or "").strip()
        if not value:
            return None
        # 用户常直接填 127.0.0.1:7897；aiohttp 需要 scheme，补成 http://。
        if "://" not in value:
            value = f"http://{value}"
        return value

    def with_environment_overrides(self) -> "Settings":
        """让"还没进设置窗口"的临时覆盖生效。

        只为自动化核对（截图脚本）准备：``ETTS_THEME=dark`` 可以在不改用户
        配置文件的前提下把界面拉成深色。**正常使用时不设这个变量就没有影响。**

        ⚠️ 覆盖前的值记在 ``_overridden`` 里，`save()` 会把它们写回去：
        截图脚本关窗时也会走 `on_close` → `_save_settings()`，不记原值的话
        跑一次深色截图，用户的主题就变成深色了。
        """
        override = os.environ.get("ETTS_THEME", "").strip().lower()
        if override in THEMES:
            self._remember_override("theme", override)
        language = os.environ.get("ETTS_LANG", "").strip().lower()
        if language in ("zh", "en"):
            self._remember_override("language", language)
        return self

    def _remember_override(self, name: str, value: str) -> None:
        if name not in self._overridden:
            self._overridden[name] = getattr(self, name)
        setattr(self, name, value)

    def to_dict(self) -> dict:
        return self._persisted()

    def update_from(self, data: dict[str, Any]) -> None:
        for key, value in data.items():
            if hasattr(self, key):
                setattr(self, key, value)
        self.validate()
