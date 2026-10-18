"""GUI-of-Edge-TTS：edge-tts 的图形界面。

分层的目的：**让判断可以自动验证**。文本预处理、SRT 合成规则、语音目录
这些以前埋在窗口回调里的逻辑，现在都在不依赖 tkinter 的模块里，由
``tests/`` 覆盖。``ui`` 是唯一碰界面的模块。
"""

from .version import APP_NAME, APP_VERSION, APP_URL, version_string

__all__ = ["APP_NAME", "APP_VERSION", "APP_URL", "version_string"]
