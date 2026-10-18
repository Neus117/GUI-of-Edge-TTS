"""合成参数（语速 / 音量 / 音调）的解析与校验。

上游只接受三种形状的字符串：

* ``rate``   ``+20%`` / ``-10%`` / ``+0%``
* ``volume`` ``+20%`` / ``-10%`` / ``+0%``
* ``pitch``  ``+10Hz`` / ``-10Hz`` / ``+0Hz``

界面上的输入形式可以更随意（``20``、``1.2x``、``+20%``、``-10``），
由这里统一归一化——**上游的参数是拼进 SSML 的，形状不对会被服务端拒绝**，
所以这一步必须在调用前做完，而不是等报错。
"""

from __future__ import annotations

from typing import Optional, Tuple

from .lang import L

RATE_MIN, RATE_MAX = -100, 200
VOLUME_MIN, VOLUME_MAX = -100, 100
PITCH_MIN, PITCH_MAX = -100, 100

_PERCENT = ("%",)
_HZ = ("hz",)


class ParameterError(ValueError):
    """参数无法解析或超出范围。``field`` 指出是哪一个，便于界面定位。"""

    def __init__(self, field: str, message: str) -> None:
        super().__init__(message)
        self.field = field
        self.message = message


def _parse_number(raw: str, field: str, label: str, unit: str) -> int:
    text = (raw or "").strip().lower()
    if not text:
        return 0
    if unit == "%":
        for suffix in ("%", "percent", "百分比"):
            if text.endswith(suffix):
                text = text[: -len(suffix)].strip()
                break
        if text.endswith("x") or text.endswith("倍"):
            number = text[:-1].strip() if text.endswith("x") else text[:-1].strip()
            try:
                value = round((float(number) - 1.0) * 100)
            except (ValueError, OverflowError):
                raise ParameterError(
                    field, L(f"{label}无法识别：{raw!r}", f"Unrecognized {label}: {raw!r}")
                ) from None
            return value
    else:
        for suffix in ("hz", "赫兹"):
            if text.endswith(suffix):
                text = text[: -len(suffix)].strip()
                break
    if text.startswith("+"):
        text = text[1:]
    try:
        return int(round(float(text)))
    except (ValueError, OverflowError):
        # ⚠️ `float("inf")` / `"1e400"` 能过 `float()`，但 `round()` 会抛
        # `OverflowError`——只接 `ValueError` 时它会一路冒到界面外：
        # 源码运行是一段 Tk traceback，冻结成 windowed exe 之后
        # 只是"点了生成没反应"（stderr 已被静音）。
        raise ParameterError(
            field, L(f"{label}无法识别：{raw!r}", f"Unrecognized {label}: {raw!r}")
        ) from None


def _clamp_value(value: int, low: int, high: int, field: str, label: str) -> int:
    if value < low or value > high:
        raise ParameterError(
            field,
            L(
                f"{label}需要在 {low} 到 {high} 之间",
                f"{label} must be between {low} and {high}",
            ),
        )
    return value


def parse_rate(raw: str) -> str:
    """返回 ``+20%`` 形状；空输入按 ``+0%``。"""
    label = L("语速", "Rate")
    value = _parse_number(raw, "rate", label, "%")
    value = _clamp_value(value, RATE_MIN, RATE_MAX, "rate", label)
    return f"{value:+d}%"


def parse_volume(raw: str) -> str:
    label = L("音量", "Volume")
    value = _parse_number(raw, "volume", label, "%")
    value = _clamp_value(value, VOLUME_MIN, VOLUME_MAX, "volume", label)
    return f"{value:+d}%"


def parse_pitch(raw: str) -> str:
    label = L("音调", "Pitch")
    value = _parse_number(raw, "pitch", label, "hz")
    value = _clamp_value(value, PITCH_MIN, PITCH_MAX, "pitch", label)
    return f"{value:+d}Hz"


def parse_all(rate: str, volume: str, pitch: str) -> Tuple[str, str, str]:
    """一次解析三项；任一项出错就抛 :class:`ParameterError`。

    **先全解析、再使用**：任何一项不合法都不应该让已经开始的生成流程
    走到一半才失败（归档 `DevAesthetics` 第 15.3 节）。
    """
    return parse_rate(rate), parse_volume(volume), parse_pitch(pitch)


def describe(rate: str, volume: str, pitch: str) -> Optional[str]:
    """把参数写成人话；三项都是默认值时返回 ``None``（不必显示）。"""
    parts = []
    if rate not in ("", "+0%"):
        parts.append(L(f"语速 {rate}", f"Rate {rate}"))
    if volume not in ("", "+0%"):
        parts.append(L(f"音量 {volume}（相对原声）", f"Volume {volume} (relative)"))
    if pitch not in ("", "+0Hz"):
        parts.append(L(f"音调 {pitch}", f"Pitch {pitch}"))
    return " · ".join(parts) if parts else None


def voice_suffix(short_name: str) -> str:
    """所选语音的文件名后缀，例如 ``_en-US-AriaNeural``。

    用户 2026-10-18 定稿："默认命名要加上选择的语音，**语音后缀放在其他
    后缀前面**"：``标题_en-US-AriaNeural_语速+20%.mp3``。
    用 ``short_name`` 而不是显示名：它是程序里唯一的语音标识，也不含空格
    与标点，直接放进文件名是安全的。
    """
    value = (short_name or "").strip()
    return f"_{value}" if value else ""


def filename_suffix(rate: str, volume: str, pitch: str) -> str:
    """文件名后缀：只写**改过**的参数，按语速/音量/音调顺序。"""
    parts = []
    if rate not in ("", "+0%"):
        parts.append(L("语速", "rate") + rate)
    if volume not in ("", "+0%"):
        parts.append(L("音量", "volume") + volume)
    if pitch not in ("", "+0Hz"):
        parts.append(L("音调", "pitch") + pitch)
    return f"_{'_'.join(parts)}" if parts else ""
