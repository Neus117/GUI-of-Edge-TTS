"""界面：布局、使用提示、操作与展示逻辑。

**这是唯一碰 tkinter 的模块。** 逻辑尽量留给 ``text`` / ``params`` /
``subtitles`` / ``engine`` / ``voices``，这样规则可以脱离窗口测。

三条来自规范的硬要求（都写着"为什么"）：

1. **能失败的事先做**——参数校验、语音是否选中，都在显示进度之前完成。
   进度条一旦出现就代表"这次一定会开始生成"。
2. **成功了要说清生成了什么**——两个文件的实际路径与大小，而不是一句"成功"。
3. **提示语是排版问题**——每条提示都量过宽度，宁可短，不可被截断。
"""

from __future__ import annotations

import os
import queue
import re
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, ttk
from typing import Callable, List, Optional

from . import params as params_mod
from . import icons as icons_mod
from . import platform_win
from . import raster, text as text_mod, voices as voices_mod
from .lang import (
    CHOICES,
    DISPLAY_NAMES,
    L,
    apply as apply_language,
    current_preference,
    is_chinese,
)
from .scrollbar import FlatProgress, FlatScrollbar
from .engine import Progress, SynthesisCancelled, SynthesisError, synthesize
from .settings import Settings, config_path
from .theme import (
    FONT_BODY_PT,
    FONT_HELP_PT,
    FONT_SMALL_PT,
    FONT_TITLE_PT,
    SPACE_1,
    SPACE_2,
    SPACE_3,
    SPACE_4,
    SPACE_5,
    Theme,
    WINDOW_DEFAULT_HEIGHT,
    WINDOW_DEFAULT_WIDTH,
    WINDOW_MIN_HEIGHT,
    WINDOW_MIN_WIDTH,
)
from .tooltip import Tooltip
from .version import APP_DISPLAY_NAME, APP_VERSION, APP_URL, version_string

#: 语音选择框占主窗口宽度的比例。
#: 用户 2026-10-17："再缩窄 1/3，即只保留 2/3 的宽度。"
#: 相对上一版的实际宽度（约 846px），新目标约 564px。由于 ttk.Combobox
#: 的 width 以字符为单位，换算后实际像素约为窗口的 43%（上一版的 2/3）。
VOICE_BOX_RATIO = 0.46

# 圆角半径与贝塞尔采样数：**一个概念只有一个权威来源**。
# 按钮、分段选择器、开关三个自绘控件都从这里取（用户要求"圆角统一半径 6"）。
RADIUS_BUTTON = 6
CORNER_SAMPLES = 8
# 标题栏那三颗图标按钮的边长（逻辑像素）：**正方形**（用户定稿）。
SQUARE_ICON_BUTTON = 32

#: 文字按钮的**统一最小宽度**（按汉字宽度折算的字数）。
#: 用户实测反馈："关闭按钮、各类文字按钮，都是偏窄了，统一下吧，
#: 一起适当加宽，加宽的距离要统一。"
#: 所以这里是一个共享常量，不是每个按钮各写一个数——**宽度下限只有一个来源**。
#: 统一的宽度下限（按汉字宽度折算）。**两条规则同时生效**：
#:
#: 1. ``max(下限, 文字宽)`` —— 保证短按钮（清空/关闭）不会又短又小；
#: 2. ``+ 2 x pad_x``        —— 保证**每个**文字按钮都拿到同一个增量。
#:
#: 为什么必须两条都有：只写"取较大者"时，长按钮会完全忽略 `pad_x`
#: （打开所在文件夹、生成语音一点没变宽）；只写"加法"时，短按钮会**变窄**
#: （清空从 120 掉到 102）。第一次我漏了前者，第二次我漏了后者。
#: 用户第二次反馈的原话是"每个带文字的按钮都适当宽一点点"——**每个**。
BUTTON_MIN_CHARS = 5

#: 设置窗口里**相邻两行之间**的默认间距（逻辑像素）。
#:
#: 来源是 `DevAesthetics` 21.2 的间距网格：``padding_gap = 8``
#: （4/8/12/16 里"普通行距"就是 8；4 是紧邻、12 是窗口边距）。
#: 2026-10-17 用户指出"配置文件按钮和启动提示隔得太近"——上一轮为了
#: "不要空行"把 footer 顶部设成了 0，把**默认行距**也一起丢掉了。
#: 注意：这里要的是"没有空行"（不是 0 间距），行与行之间仍应保留
#: 一个 `padding_gap`。
SETTINGS_ROW_GAP = SPACE_2

# 占位提示**只占两行**：内容比可视行数多就会被从底部裁掉。
# 文案由 `placeholder_text()` 按当前语言生成，不再写死在模块常量里。

# 根窗口的行号。**写常量而不是散落的数字**：加/删一个分区时不会错位，
# 几何探针也能按行号报"谁占了哪一段"。
ROW_HINT = 0
ROW_HEADER = 1
ROW_SETTINGS = 2
ROW_EDITOR = 3
#: 「输出目录」那一排**自己占一行**，紧贴在编辑区下方（用户定稿：
#: "放在输入框下方、灰色说明文字的下方，不要空行；并且它仍然在平时隐藏的
#: 进度条上方"）。**不要**把它塞进编辑区内部——那样会挤掉文本框的高度
#: （实测文本框从 256px 掉到 54px，占位提示直接被裁掉，门禁如实报错）。
ROW_DIRS = 4
ROW_ACTION = 5
ROW_STATUS = 6
ROW_FOOTER = 7

#: 参数校验的唯一来源：字段 → (标签, 单位, 下限, 上限, 归一化函数)
PARAM_SPECS = {
    "rate": ("语速", "%", params_mod.RATE_MIN, params_mod.RATE_MAX, params_mod.parse_rate),
    "volume": ("音量", "%", params_mod.VOLUME_MIN, params_mod.VOLUME_MAX, params_mod.parse_volume),
    "pitch": ("音调", "Hz", params_mod.PITCH_MIN, params_mod.PITCH_MAX, params_mod.parse_pitch),
}

#: 自绘提示窗的断行：中文按字断，英文/数字保持整词，句末标点不落单。
_DIALOG_TOKEN = re.compile(
    r"[$€£¥]?[A-Za-z0-9][A-Za-z0-9_./:%+\-']*|[ \t]+|.", re.S
)
_DIALOG_CLOSING = frozenset("，。！？；：、）》】」』.,!?;:)]}…")
HELP_TEXT = f"""\
Edge-TTS 把文字变成语音，并同时生成一份逐词对齐的字幕文件。

基本用法
    1  把文字粘贴或输入到编辑区
    2  选择语音（可搜索：输入 en 女 / zh-CN / 晓晓 都能过滤）
    3  点「生成语音」，选择保存位置
    →  会生成两个文件：.mp3 音频，同名 .srt 字幕

快捷键
    Ctrl+Enter    开始生成
    Ctrl+O        打开文本文件（.txt / .md / .srt）
    Ctrl+S        把编辑区内容另存为文本文件
    Ctrl+L        清空编辑区
    Ctrl+H        显示本提示
    Esc           取消生成 / 关闭本窗口

合成参数（范围）
    语速     {params_mod.RATE_MIN} 到 +{params_mod.RATE_MAX}（%）
             +30 表示快 30%，-20 表示慢 20%
    音量     {params_mod.VOLUME_MIN} 到 +{params_mod.VOLUME_MAX}（%）
             相对原声的增益；+100% 是上游上限，听感提升有限
    音调     {params_mod.PITCH_MIN} 到 +{params_mod.PITCH_MAX}（Hz）
             +20 表示高 20 赫兹
    三项留空或填 0 表示使用原声。
    超出范围会弹窗提示，并恢复为上一次的有效值。
    改过参数时，默认文件名会自动带上对应后缀
    （如 _语速+20%_音量+100%_音调-10Hz）。

常见问题
    生成失败怎么办
        先检查网络。若网络正常，多半是所选语音被上游下线，换一个语音再试。
    字幕和音频对不上
        字幕按上游返回的词边界生成；播放器需要加载同名 .srt 才会显示。
    文字里的中文标点
        生成前会自动换成英文标点，上游的断句质量更好。

设置保存在 {config_path()}
版本 {version_string()}
{APP_URL}
"""


HELP_TEXT_EN = f"""\
Edge-TTS turns text into speech and writes a word-aligned subtitle file.

Basic usage
    1  Paste or type text into the editor
    2  Choose a voice (search: en female / zh-CN / Xiaoxiao all work)
    3  Click "Generate" and choose where to save
    -> Two files are created: .mp3 audio and a same-named .srt subtitle

Shortcuts
    Ctrl+Enter    Start generating
    Ctrl+O        Open a text file (.txt / .md / .srt)
    Ctrl+S        Save the editor contents as a text file
    Ctrl+L        Clear the editor
    Ctrl+H        Show this help
    Esc           Cancel generation / close this window

Speech parameters (ranges)
    Rate      {params_mod.RATE_MIN} to +{params_mod.RATE_MAX} (%)
              +30 means 30% faster, -20 means 20% slower
    Volume    {params_mod.VOLUME_MIN} to +{params_mod.VOLUME_MAX} (%)
              Gain relative to the original; +100% is the upstream limit
    Pitch     {params_mod.PITCH_MIN} to +{params_mod.PITCH_MAX} (Hz)
              +20 means 20 Hz higher
    Leave a field blank or set it to 0 to keep the original voice.
    Out-of-range values show a warning and restore the last valid value.
    Changed parameters are appended to the default file name
    (for example _rate+20%_volume+100%_pitch-10Hz).

FAQ
    Generation failed
        Check the network first. If it is fine, the selected voice may have
        been retired upstream; try another one.
    Audio and subtitles do not match
        Subtitles use the word boundaries returned upstream; load the
        same-named .srt in your player.
    Chinese punctuation in the text
        It is converted to English punctuation before generation for better
        upstream sentence splitting.

Settings are saved in {config_path()}
Version {version_string()}
{APP_URL}
"""


def help_title() -> str:
    return L("使用提示", "Help")


def help_text() -> str:
    return HELP_TEXT if is_chinese() else HELP_TEXT_EN


def placeholder_text() -> str:
    return L(
        "把要朗读的文字粘贴到这里…\nCtrl+Enter 直接开始生成",
        "Paste the text to read here...\nCtrl+Enter starts generating",
    )


def param_label(field: str) -> str:
    return {
        "rate": L("语速", "Rate"),
        "volume": L("音量", "Volume"),
        "pitch": L("音调", "Pitch"),
    }[field]


def _rounded_rect_points(x0: int, y0: int, x1: int, y1: int, radius: int) -> list:
    """圆角矩形的顶点序列（顺时针一圈，末点回到起点）。

    每个圆角是一段**三次贝塞尔**，控制点用 ``k = 0.5523 x r`` 逼近四分之一圆
    ——这个常数不是随手取的，它是"三次贝塞尔逼近圆弧"的最小误差解。
    每段采样 :data:`CORNER_SAMPLES` 个点，顶点够密，圆角才是圆的。

    **这是整个界面唯一的圆角几何**：按钮、分段选择器、开关都调它，
    所以"圆角统一半径 6"只有一个权威来源（归档 `02` 第六节）。

    ⚠️ 第一版把四段写成"两段二次 + 两段三次"、端点顺序还对不上，画出来是
    **橄榄形**。形状类的东西必须**回读像素**验证，不能只看代码。
    """
    radius = max(0, min(radius, (x1 - x0) // 2, (y1 - y0) // 2))
    if radius <= 0:
        return [x0, y0, x1, y0, x1, y1, x0, y1]

    k = 0.5522847498 * radius
    steps = CORNER_SAMPLES

    def cubic(ax, ay, bx, by, cx, cy, dx, dy):
        out = []
        for step in range(1, steps + 1):
            t = step / steps
            inv = 1 - t
            out.append(
                (
                    inv**3 * ax + 3 * inv * inv * t * bx + 3 * inv * t * t * cx + t**3 * dx,
                    inv**3 * ay + 3 * inv * inv * t * by + 3 * inv * t * t * cy + t**3 * dy,
                )
            )
        return out

    # 每条边显式给端点：否则多边形会从最后一个角点直接连回第一个点，画出橄榄形
    path = [
        (x0 + radius, y0),                                        # 上边起点
        (x1 - radius, y0),                                        # 上边终点
        (x1 - radius, y0, x1 - radius + k, y0, x1, y0 + radius - k, x1, y0 + radius),
        (x1, y1 - radius),                                        # 右边终点
        (x1, y1 - radius, x1, y1 - radius + k, x1 - radius + k, y1, x1 - radius, y1),
        (x0 + radius, y1),                                        # 下边终点
        (x0 + radius, y1, x0 + radius - k, y1, x0, y1 - radius + k, x0, y1 - radius),
        (x0, y0 + radius),                                        # 左边终点
        (x0, y0 + radius, x0, y0 + radius - k, x0 + radius - k, y0, x0 + radius, y0),
    ]
    points: list = []
    for item in path:
        if len(item) == 2:
            points.extend(item)
        else:
            for px, py in cubic(*item):
                points.extend((px, py))
    return points


class FlatButton(tk.Canvas):
    """圆角按钮，**完全自绘**。

    为什么从 ``tk.Frame`` 换成 ``tk.Canvas``：

    * 用户报"所有按钮外的文字周围和面板之间有淡淡的色差"。像素回读证实，
      每个按钮都是一个**直角**白矩形——直角外缘在 175% 缩放下呈现出 1~2 像素
      的灰边，看上去就是"淡淡的一圈色差"。**要圆角就必须自己画**，
      而画了圆角，那圈色差同时消失；
    * ``Frame`` + ``highlightthickness`` 只能画 1 像素的直角描边，圆角与
      描边颜色都得靠外部容器，做不出"圆角 + 抗锯齿"。

    抗锯齿：圆角用**二次贝塞尔采样成多边形顶点**（每段 8 个采样点），
    顶点足够密，圆角就是圆的而不是"切角的"；描边再做一次同路径的
    ``create_line``，让边缘过渡到面板底色。**Tk 的 Canvas 不做真抗锯齿**，
    所以这里靠"采样密度 + 同路径描边"达到视觉上的平滑（规范里的
    `radius_button = 8` 就是这个值）。

    代价：键盘焦点要自己接（``takefocus`` + ``<Return>`` / ``<space>``），
    所以下面显式支持了。
    """

    #: 标准圆角半径（逻辑像素）。**三个自绘控件共用同一个来源。**
    RADIUS = RADIUS_BUTTON

    def __init__(
        self,
        master,
        text: str,
        command: Optional[Callable[[], None]] = None,
        theme: Optional[Theme] = None,
        kind: str = "neutral",  # neutral | accent | ghost
        width: int = 0,
        pad_x: int = SPACE_3,
        pad_y: int = SPACE_2,
        square: int = 0,
        draw: Optional[Callable] = None,
        bold: bool = False,
        font_delta: int = 0,
        min_chars: int = BUTTON_MIN_CHARS,
    ) -> None:
        super().__init__(
            master,
            highlightthickness=0,
            borderwidth=0,
        # ⚠️ `takefocus=0` 是**故意的**：Windows 会给"拿到原生焦点的
        # 可聚焦窗口"画一圈键盘焦点矩形（用户看到的蓝色方框），而
        # `WM_UPDATEUISTATE` 关不掉它（实测回读 `UISF_HIDEFOCUS` 仍是 False）。
        # 我们自己的按钮/开关都有自绘的焦点态，不需要系统那圈。
        takefocus=0,
            cursor="hand2",
        )
        self.command = command
        self.theme = theme
        self.kind = kind
        self._enabled = True
        self._hover = False
        self._text = text
        self._pad_x = pad_x
        self._pad_y = pad_y
        self._width = width
        #: 冻结宽度（物理像素）。非 0 时按钮宽度完全按它来，换文案也不变。
        self._frozen_width = 0
        # 正方形边长（逻辑像素）：图标按钮用它，长宽相等才是"正方"。
        self._square = square
        # 自绘图标：`draw(canvas, cx, cy, size, colour)`。
        # 有了它就不用把图标写成字符——字体里有没有那个字形、渲染成彩色还是
        # 黑白，都不在我们控制之内；画出来的才确定。
        self._draw = draw
        # 粗体：问号那颗按钮用户要求用粗体（它只有一个字符，粗体更显眼）
        self._bold = bool(bold)
        # 字号偏移：问号单独 +1pt（用户定稿）。用**偏移**而不是绝对点数，
        # 这样字体档位一变它跟着变，不会出现"只有它没跟着调"的情况。
        self._font_delta = int(font_delta)
        # 最小宽度（按字数估）：短标签的按钮（例如"关闭"两个字）在
        # 中文界面里显得又短又小，给一个下限让它和旁边的按钮成比例。
        self._min_chars = max(0, int(min_chars))
        # 把视觉样式摘掉：系统不该给自绘控件画任何边框。
        # ⚠️ 第一版只绑 `<Map>` 事件来做，结果**主窗口的按钮一个都没执行**——
        # 因为 root 在构建期间是收起的（`withdraw`），`<Map>` 不会触发，
        # 只有后开的设置窗口碰巧触发了。**"绑了事件"不等于"事件会发生"。**
        # 现在改成：apply_theme 时试一次，绑 `<Map>` 作为兜底，成功一次即止。
        self._style_detached = False
        self.bind("<Map>", self._on_first_map, add="+")
        self._shape: list = []
        #: 上一次 Configure 时的尺寸。Tk 在启动/布局阶段会为同一个尺寸
        #: 连发多次 Configure；每次都重画圆角位图纯属浪费（实测启动阶段
        #: 多出二十多次）。主题/悬停/文案变化走显式 `_paint()`，不依赖它。
        self._last_configure_size = (0, 0)

        self.bind("<Button-1>", self._on_click)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Return>", lambda _event: self._invoke())
        self.bind("<space>", lambda _event: self._invoke())
        self.bind("<FocusIn>", lambda _event: self._paint())
        self.bind("<FocusOut>", lambda _event: self._paint())
        self.bind("<Configure>", self._on_configure)
        if theme is not None:
            self.apply_theme(theme)

    def _on_first_map(self, _event=None) -> None:
        """显示出来时再试一次摘视觉样式（控件那会儿才真正有 HWND）。"""
        self._detach_style()
        return None

    def _detach_style(self) -> bool:
        """把系统视觉样式从这个子窗口上摘掉；成功一次就不再试。

        ``winfo_id()`` 在控件还没映射时会抛 ``TclError``，所以要能重试。
        """
        if self._style_detached:
            return True
        try:
            handle = self.winfo_id()
        except tk.TclError:
            return False
        if not handle:
            return False
        if platform_win.detach_visual_style(handle):
            self._style_detached = True
        return self._style_detached

    # ---- 主题 --------------------------------------------------------------

    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        self._resize_to_content()
        self._paint()
        # 每次刷主题都顺手试一次（控件这时通常已经有 HWND 了）
        self._detach_style()

    def _colors(self) -> tuple[str, str, str]:
        """返回 ``(填充色, 描边色, 文字色)``。

        **所有可点击的按钮共用这一套逻辑**（用户定稿）：填充用主题的输入区
        表面色、描边用 `border_strong`——于是"能不能点"在每个按钮上看起来
        是一致的。唯一的例外是强调按钮（生成语音），它按规范只给
        "推荐的那一个动作"。
        """
        assert self.theme is not None
        palette = self.theme.palette
        if not self._enabled:
            return palette.background, palette.border, palette.text_secondary
        if self.kind == "accent":
            background = palette.accent_hover if self._hover else palette.accent
            return background, background, palette.accent_text
        # neutral 与 ghost 统一成同一套：这是"可点击按钮"的唯一外观
        if self._hover:
            return palette.surface_hover, palette.border_strong, palette.text
        return palette.surface, palette.border_strong, palette.text

    def _on_configure(self, _event=None) -> None:
        size = (max(int(self.winfo_width()), 1), max(int(self.winfo_height()), 1))
        if size == self._last_configure_size:
            return
        self._last_configure_size = size
        self._paint()

    def _resize_to_content(self) -> None:
        """把画布尺寸定成"文字 + 内边距"，这样它没有多余的空白区域。"""
        if self.theme is None:
            return
        if self._square:
            # 正方形：长宽都取这个边长，**文字居中**。
            # 标题栏那三颗图标按钮用它——长方形的"?"看起来就是不对劲。
            side = self.theme.px(self._square)
            self.configure(width=side, height=side)
            return
        font = self.theme.font(FONT_BODY_PT + self._font_delta, bold=self._bold)
        text_width = font.measure(self._text)
        # ⚠️ **宽度 = 文字宽度 + 2 x pad_x**（不再是"取较大者"）。
        #
        # 用户第二次反馈点明了要害："每个带文字的按钮都适当宽一点点"。
        # 上一版写的是 `max(pad_x, 文字宽 + 2*SPACE_2)`——对短按钮，
        # `pad_x` 起作用；对长按钮（打开所在文件夹、生成语音），
        # **`pad_x` 被完全忽略**，于是它们一点没变宽。
        # 改成加法之后，每个按钮拿到的增量是同一个 `2 x pad_x`，**一个不漏**，
        # 而且"加宽的距离统一"这句话在公式上就成立了。
        inner = text_width + self.theme.px(self._pad_x) * 2
        if self._min_chars:
            # 用"某个汉字宽度 × 字数"当宽度下限：汉字是方块字，比按像素写死
            # 更能随字号/DPI 自动缩放。
            sample = self.theme.font(FONT_BODY_PT).measure("关")
            inner = max(inner, sample * self._min_chars + self.theme.px(SPACE_2) * 2)
        if self._frozen_width:
            # **冻结宽度（物理像素）**：显式定过就完全按它来，不再随文字变。
            # 用途：「生成语音」的文字在"生成语音/生成中…"之间切换，
            # 两者宽度不同（162 vs 158），按钮右对齐时左边缘会跟着移动 4px。
            # 注意这里**不能再乘 DPI**：`_width` 那一支走 `theme.px()` 是
            # 逻辑像素，我第一版把物理像素塞进 `_width`，被乘了 1.75 倍，
            # 于是锁了个远大于实际的值，看起来像"锁没生效"。
            inner = self._frozen_width
        elif self._width:
            inner = max(inner, self.theme.px(self._width))
        height = max(
            font.metrics("linespace") + self.theme.px(self._pad_y) * 2,
            self.theme.px(24),
        )
        self.configure(width=inner, height=height)

    # ---- 绘制 --------------------------------------------------------------

    def _paint(self) -> None:
        if self.theme is None:
            return
        self.delete("all")
        palette = self.theme.palette
        background, border, foreground = self._colors()
        width = max(int(self.winfo_width()), 1)
        height = max(int(self.winfo_height()), 1)
        radius = self.theme.px(self.RADIUS)
        inset = max(1, self.theme.px(1))

        # 画布自己的底色跟面板一致：圆角之外那四个角要露出面板色，
        # 否则深色下会在角上留下没扣干净的浅色像素（规范 23.4）。
        parent_bg = palette.background
        self.configure(background=parent_bg)

        # ⚠️ **按钮外形改成"栅格化成位图再贴"**，不再用 `create_polygon`。
        #
        # 原因：Tk 的 Canvas 不画抗锯齿，`create_polygon` 的圆角就是硬边阶梯
        # ——用户实测报回来："每个按钮的圆角还是存在明显的锯齿。"
        # 位图由 `raster` 逐像素算覆盖率生成（4x4 子采样），边缘是半透明像素，
        # 贴到画布上就是真抗锯齿。
        #
        # 描边由"描边色位图 + 内缩的填充色位图"两层实现，和原来一样。
        try:
            png = raster.cached_rounded_rect(
                width, height, radius, background, border, inset,
                background=parent_bg, supersample=2,
            )
            self._shape_photo = tk.PhotoImage(master=self, data=png)
            self.create_image(0, 0, image=self._shape_photo, anchor="nw")
        except Exception:  # noqa: BLE001
            # 兜底：位图这条路万一出问题（例如既没有 zlib 也没有 Tk 的 PNG
            # 解码器），退回多边形——**按钮必须还能看见**，宁可锯齿。
            self._shape_photo = None
            points = _rounded_rect_points(
                inset, inset, width - inset - 1, height - inset - 1, radius
            )
            self.create_polygon(points, fill=border, outline=border, width=1)
            inner = _rounded_rect_points(
                inset + 1, inset + 1, width - inset - 2, height - inset - 2, max(1, radius - 1)
            )
            self.create_polygon(inner, fill=background, outline=background, width=1)

        self.create_text(
            width / 2,
            height / 2,
            text=self._text,
            fill=foreground,
            font=self.theme.font(FONT_BODY_PT + self._font_delta, bold=self._bold),
        )
        if self._draw is not None:
            # 图标也是**栅格化成位图**：画笔只描述形状（`icons.py`），
            # 这里负责把它变成抗锯齿像素。字形路线已经证明不可靠——
            # `"⚙"` 在本机没有字形，会显示成空心方框。
            icon_size = min(width, height) * (0.48 if self._text else 0.66)
            if self._square:
                icon_size = self.theme.px(self._square) * 0.48
            icon_size = max(8.0, icon_size)
            # 位图要比图标的标称尺寸大一圈：图元最远到 ±0.52·size（太阳光点），
            # 按 icon_size+2 开画布只剩 1 像素余量——27px 下刚好够，放大渲染
            # （`tools/render_icons.py`）就会把光点裁成平口。余量见
            # `icons.ICON_BOX_SCALE`。`cx/cy` 仍取画布中心，图标依旧居中。
            side = int(round(icon_size * icons_mod.ICON_BOX_SCALE)) + 2
            # 图标位图铺在**按钮底色**上，边缘才能和按钮融合。
            # `background` 同时交给 painter：需要"挖空"的图形（齿轮的中心孔）
            # 必须拿按钮当前底色画，不能假设它是白色（规范 34.8）。
            try:
                primitives = self._draw(
                    side / 2.0, side / 2.0, icon_size, foreground, background
                )
                icon_png = raster.cached_rasterise(primitives, side, side, background)
                self._icon_photo = tk.PhotoImage(master=self, data=icon_png)
                self.create_image(width / 2, height / 2, image=self._icon_photo, anchor="center")
            except Exception:  # noqa: BLE001
                self._icon_photo = None
        # ⚠️ **按钮也不画焦点圈**（与 ToggleSwitch 一致）。
        #
        # 上一轮用户说"把点击后出现的蓝色矩形外框删掉"时，我只删了**开关**那
        # 一处的焦点圈，**漏了按钮这一处**——同一段代码有两个实例，我只改了一
        # 个。用户照样看到蓝框，而我以为修好了。教训：改一处时先把同类实例数
        # 一遍（`grep` 一下有多少处在画同一个东西）。
        self._focus_photo = None

    # ---- 交互 --------------------------------------------------------------

    def _on_enter(self, _event=None) -> None:
        self._hover = True
        self._paint()

    def _on_leave(self, _event=None) -> None:
        self._hover = False
        self._paint()

    def _on_click(self, _event=None) -> str:
        self.focus_set()
        self._invoke()
        return "break"

    def _invoke(self) -> None:
        if self._enabled and self.command is not None:
            self.command()

    def set_enabled(self, enabled: bool) -> None:
        self._enabled = bool(enabled)
        self.configure(cursor="hand2" if enabled else "arrow")
        self._paint()

    def set_text(self, text: str, repaint: bool = True) -> None:
        """换文字并重新量宽度；``repaint=False`` 供批量更新后统一重绘。"""
        self._text = text
        self._resize_to_content()
        if repaint:
            self._paint()

    def set_kind(self, kind: str) -> None:
        """切换配色（neutral / accent / ghost），不改变尺寸。"""
        if kind not in ("neutral", "accent", "ghost"):
            return
        self.kind = kind
        self._paint()

    def freeze_width(self, pixels: int) -> None:
        """把按钮宽度固定成这个**物理像素**值（换文案也不再变）。

        用于文字会变、但位置必须稳定的按钮（「生成语音」⇄「生成中…」）。
        """
        self._frozen_width = max(1, int(pixels))
        self._resize_to_content()

    def cget_text(self) -> str:
        return self._text

    def configure_text(self, text: str) -> None:
        self.set_text(text)


class ToggleSwitch(tk.Canvas):
    """开关：自绘的滑条式开关，替代 ``tk.Checkbutton``。

    为什么不用 ``Checkbutton``：它的勾选方框是**系统绘制**的，深色主题下要么
    看不见、要么是一个浅色方块（用户实测报回来）。开关的形状还自带"开/关"
    的语义，比一个需要仔细看的小方框清楚得多。
    """

    WIDTH = 40
    HEIGHT = 22
    RADIUS = RADIUS_BUTTON

    def __init__(
        self,
        master,
        value: bool = False,
        command: Optional[Callable[[bool], None]] = None,
        theme: Optional[Theme] = None,
    ) -> None:
        super().__init__(
            master, highlightthickness=0, borderwidth=0,
        # ⚠️ `takefocus=0` 是**故意的**：Windows 会给"拿到原生焦点的
        # 可聚焦窗口"画一圈键盘焦点矩形（用户看到的蓝色方框），而
        # `WM_UPDATEUISTATE` 关不掉它（实测回读 `UISF_HIDEFOCUS` 仍是 False）。
        # 我们自己的按钮/开关都有自绘的焦点态，不需要系统那圈。
        takefocus=0,
        )
        self.value = bool(value)
        self.command = command
        self.theme = theme
        self._hover = False
        self.bind("<Button-1>", lambda _e: self._toggle())
        self.bind("<Return>", lambda _e: self._toggle())
        self.bind("<space>", lambda _e: self._toggle())
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Configure>", lambda _e: self._paint())
        if theme is not None:
            self.apply_theme(theme)

    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        self.configure(
            background=theme.palette.background,
            width=theme.px(self.WIDTH),
            height=theme.px(self.HEIGHT),
            cursor="hand2",
        )
        self._paint()

    def set_value(self, value: bool) -> None:
        self.value = bool(value)
        self._paint()

    def _on_enter(self, _event=None) -> None:
        self._hover = True
        self._paint()

    def _on_leave(self, _event=None) -> None:
        self._hover = False
        self._paint()

    def _toggle(self) -> str:
        self.focus_set()
        self.value = not self.value
        self._paint()
        if self.command is not None:
            self.command(self.value)
        return "break"

    def _paint(self) -> None:
        if self.theme is None:
            return
        self.delete("all")
        palette = self.theme.palette
        self.configure(background=palette.background)
        width = max(int(self.winfo_width()), 1)
        height = max(int(self.winfo_height()), 1)
        radius = self.theme.px(self.RADIUS)
        inset = max(1, self.theme.px(1))

        track = palette.accent if self.value else palette.track
        if self._hover and not self.value:
            track = palette.surface_hover
        outline = palette.accent if self.value else palette.border_strong

        # 开关外形同样走**位图抗锯齿**（和按钮一套机制，含 2× 超采样）
        try:
            png = raster.cached_rounded_rect(
                width, height, radius, track, outline, inset,
                background=palette.background, supersample=2,
            )
            self._track_photo = tk.PhotoImage(master=self, data=png)
            self.create_image(0, 0, image=self._track_photo, anchor="nw")
        except Exception:  # noqa: BLE001
            self._track_photo = None
            points = _rounded_rect_points(inset, inset, width - inset, height - inset, radius)
            self.create_polygon(points, fill=outline, outline=outline, width=1)
            inner = _rounded_rect_points(
                inset + 1, inset + 1, width - inset - 1, height - inset - 1, max(1, radius - 1)
            )
            self.create_polygon(inner, fill=track, outline=track, width=1)

        # 滑块：**圆形**（用户定稿），开到右边、关在左边，位置本身就是状态。
        #
        # 圆形同样走位图：`create_oval` 画出来是硬边，圆越小锯齿越明显。
        # 位图圆由覆盖率算法生成，边缘是半透明像素。
        knob_size = height - inset * 2 - self.theme.px(4)
        knob_y0 = (height - knob_size) / 2
        knob_x0 = (width - knob_size - self.theme.px(3)) if self.value else self.theme.px(3)
        knob_color = palette.accent_text if self.value else palette.text_secondary
        try:
            knob_px = int(round(knob_size))
            # 滑块边缘要融进轨道，不能融进面板底色；背景传当前 track 色。
            knob_png = raster.cached_rounded_rect(
                knob_px, knob_px, knob_px / 2.0,
                knob_color, "", 0,
                background=track, supersample=2,
            )
            self._knob_photo = tk.PhotoImage(master=self, data=knob_png)
            self.create_image(
                knob_x0 + knob_size / 2,
                knob_y0 + knob_size / 2,
                image=self._knob_photo,
                anchor="center",
            )
        except Exception:  # noqa: BLE001
            self._knob_photo = None
            self.create_oval(
                knob_x0, knob_y0, knob_x0 + knob_size, knob_y0 + knob_size,
                fill=knob_color, outline=knob_color,
            )
        # ⚠️ **开关不画焦点圈**（用户定稿）。
        #
        # 这一处踩了三次，值得写清楚：
        #
        #   1. 第一版用 `create_rectangle(outline=accent)` —— 尖角蓝框；
        #   2. 改成位图圆角框 `("ellipse", …, stroke=inset)`，但 `_expand`
        #      挖空用的是 `stroke/2 = 0.5` 像素，**只挖掉半个像素**，
        #      剩下一圈实心蓝矩形；
        #   3. 删第 2 种时**只删了 `create_image` 那半段，漏了紧跟着的
        #      `create_rectangle` 分支**——两种画法写在同一段代码里，
        #      我只删了其中一个。用户照样看到蓝框，而我又以为修好了。
        #
        # 教训：**删一段"画东西"的代码时，先把同一段里所有 `create_*`
        # 数一遍**（`grep -n 'create_' 那个方法`），而不是只看自己刚写的那行。
        #
        # 开关本身已经有"开/关"这个强状态（滑块位置 + 轨道配色），
        # 不需要再叠一圈装饰。鼠标与空格/回车照旧可用。
        self._focus_photo = None


class Application:
    """主窗口。"""

    #: 这些**前缀**开头的状态描述的是"编辑区当前内容"，内容一变就过时了。
    #: 与"进程状态"（正在合成 / 生成失败）分开——后者不能被打字清掉。
    #:
    #: ⚠️ 用**前缀**而不是精确文本：`已读入 xxx.txt（1,234 字）` 里带文件名与
    #: 字数，精确匹配一定漏。第一版就是按精确文本写的，于是"已读入…"清不掉。
    EDITOR_STATUS_PREFIXES = (
        "编辑区已清空",
        "已读入",
        "已保存",
        "Editor cleared",
        "Loaded ",
        "Saved ",
        # ⚠️ **这条是用户实测报回来的**：编辑区空时点生成 → 得到这句警告 →
        # 之后粘贴了文字（状态栏显示 85 词）→ **警告还挂着**，看起来像
        # "编辑区有字却说我编辑区是空的"。
        # 它同样是"关于编辑区当前内容"的判断，内容一变就过时。
        "编辑区是空的",
        "The editor is empty",
        "界面语言已切换",
        "Language changed",
    )

    def __init__(self, root: tk.Tk, settings: Optional[Settings] = None) -> None:
        self.root = root
        self.settings = settings or Settings.load()
        apply_language(self.settings.language)
        self.theme = Theme.detect(self.settings.theme)

        self._status_text = ""
        #: 进度条的分母（估计总秒数）。`_begin_progress` 里设，`_end_progress` 里清。
        self.progress_total_seconds = 0.0
        #: 已经生成过的那份文案。用来判断"当前编辑区内容是否还是生成时那份"，
        #: 变了就要撤掉产物按钮（它们指向旧文案生成的音频）。
        self._generated_content = ""
        self.catalog = voices_mod.VoiceCatalog.fallback()
        self.catalog_error = ""
        self.voice_loading = False
        #: 关闭窗口时要能取消语音列表请求并等线程清理完 aiohttp session。
        self._voice_thread: Optional[threading.Thread] = None
        self._voice_cancel_event: Optional[threading.Event] = None
        self._synth_thread: Optional[threading.Thread] = None

        self.events: "queue.Queue[tuple[str, object]]" = queue.Queue()
        self.cancel_event: Optional[threading.Event] = None
        self.worker: Optional[threading.Thread] = None
        self._drain_id: Optional[str] = None
        #: 待执行的窗口高度结算（`after_idle` 的 id）。
        #: **同一轮里多次请求只结算一次**：生成结束时先隐藏进度条、再显示
        #: 「打开音频」和状态栏，如果各结算一次，窗口会先缩再涨——用户看到
        #: 输入框上下跳一下（2026-10-17 实测报回来）。
        self._settle_after_id: Optional[str] = None
        #: 代理输入防抖：保存配置 / 重拉语音列表。
        self._proxy_save_id: Optional[str] = None
        self._proxy_reload_id: Optional[str] = None
        self._voice_reload_pending = False
        self.generating = False
        self.result_paths: List[str] = []
        self._help_window: Optional[tk.Toplevel] = None
        self._settings_window: Optional[tk.Toplevel] = None
        self._placeholder_active = False
        #: 共用坑位当前钉住的宽度，以及钉它时窗口有多宽（用来加闸：
        #: 设 minsize 会触发 <Configure>，只看操作区宽度会自我振荡）
        self._progress_slot = 0
        self._slot_root_width = 0
        #: 「取消」相对右边缘的偏移量（= 生成语音宽 + 自己的 padx）
        self._cancel_offset = 0
        #: 正在由程序调整窗口尺寸（用来区分"我改的"和"用户拉的"）
        self._resizing = False
        #: 正在重算共用坑位（**防重入**）。
        #:
        #: 重算过程中会 `set_text()` + `update_idletasks()`，后者会**同步**
        #: 派发 Configure 事件；而 `root.bind("<Configure>")` 的 bindtag 是
        #: "."，这个窗口里**每个子控件的 bindtags 都含 "."** —— 于是按钮
        #: 自己的 Configure 又回到重算入口，递归到 RecursionError
        #: （2026-10-17 用户报的崩溃，实测 995 层）。
        #: 过滤 `event.widget is root` 是主修法，这个标志是第二道闸：
        #: 任何事件源都不该让同一次重算嵌套执行。
        self._fixing_slot = False
        #: 干净状态（没有产物按钮、没有状态文字）下的 `(窗口高度, 下段自然高度)`。
        #: 内容出现时按"下段多要了多少"把窗口加高、收起时回落同样的量——
        #: 这样**编辑区的高度始终不变**，否则多/少的高度会被 `weight=1` 的
        #: 编辑区吃掉，下面几段整体上下移动，看起来就是"凭空多了一条空行"
        #: （用户实测报回来的）。
        self._clean_window_height = 0
        self._clean_lower_height = 0
        #: 上一次 `_settle_window_height` 结算时的"下段自然高度"。
        #:
        #: **和启动基准分开**：窗口高度按"当前高度 + 下段增量"伸缩，而不是
        #: 按"启动基准 + 增量"。否则用户手动把窗口拉高之后，点一下「清空」
        #: 会被拉回启动高度——用户看到的是"输入框缩回最低高度"（2026-10-17 报）。
        self._last_lower_height = 0
        #: 编辑区初始高度（首帧量出后写进 grid 的 minsize）
        self._editor_initial_height = 0
        self._closing = False

        self._build()
        self._apply_theme()
        self._install_flat_voice_popdown()
        self._wire_shortcuts()
        self._load_voices()

        # **标题栏深浅要在这里就设上**：实测 `--settings` 启动时，
        # 设置窗口的标题栏是深色、主窗口的却是浅色——因为只有弹窗那条路径
        # 调了 `apply_dark_titlebar`，主窗口从来没有。现在统一到这一个函数里，
        # 谁创建的窗口都走它。
        self._apply_window_chrome()

        # 首帧布局稳定后：记基准、给共用坑位定宽
        self.root.after(150, self._remember_clean_height)
        # 坑位宽度随窗口宽度变化：让**窗口自己**的 Configure 来驱动。
        # **不要只靠首帧那一次**——那时候布局还没定，量出来是错的
        # （实测曾算出 108px，进度条变成一小截）。
        #
        # ⚠️ 必须用 `_on_root_configure` 过滤，不能直接绑一个 lambda：
        # `root.bind("<Configure>")` 落在 bindtag "." 上，而**每个子控件**
        # 的 bindtags 里都有 "."，于是任何按钮改尺寸都会触发它。
        # 重算里又会改「生成语音」的文字（宽度随之变），`update_idletasks()`
        # 同步派发它自己的 Configure —— 一条无底递归（实测 995 层后
        # RecursionError，用户看到"启动失败"）。
        self.root.bind("<Configure>", self._on_root_configure, add="+")
        self.root.after(200, lambda: self._fix_progress_slot(force=True))
        self.root.after(200, self._fix_voice_width)
        self.root.after(150, lambda: self._set_window_icon(self.root))
        self.root.after(80, self._drain_events)
        # 首帧布局稳定后记下"用户期望的编辑区高度"——它是这个窗口的基准，
        # 之后每次要在下方多显示一行，都靠加高窗口来腾地方，**不动编辑区**。
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    # ------------------------------------------------------------------ 构建

    def _build(self) -> None:
        """建界面。

        **整个窗口用 grid 而不是 pack**：pack 下"编辑区 expand"会把高度不够
        的锅甩给别的分区——实测 720 高的窗口里，操作区与底栏被挤到客户区外面
        （y = -337），而窗口本身看起来"只是有点空"。grid 给出显式的行权重，
        "谁可以被压缩、谁不能"一目了然，也能用几何探针回读验证。
        """
        root = self.root
        root.title(APP_DISPLAY_NAME)
        root.minsize(WINDOW_MIN_WIDTH, WINDOW_MIN_HEIGHT)
        self._center_window(WINDOW_DEFAULT_WIDTH, WINDOW_DEFAULT_HEIGHT)

        # ---- 顶层结构：整窗 grid --------------------------------------------
        #
        # 规则（用户定稿，最简单的那一种）：
        #   * **只靠拉高程序窗口来让输入框变高**——编辑区那一行 `weight=1`，
        #     窗口多出来的高度全部归它；
        #   * 拖动窗口底边时，**只有输入框的高度在变**，输入框与窗口底边之间
        #     那几段（输出目录排 / 操作区 / 状态栏 / 页脚）位置固定不动；
        #   * 下段内容变多时窗口不自动长高——那几行 `weight=0` 各占自然高度，
        #     编辑区让出空间（这是可接受的：用户明确说不需要拖动了）。
        #
        # 走过的弯路（记下来，别再犯）：我先用 `PanedWindow` 分上下两段，
        # 它的分配语义和上面这条规则对不上；又做了"抓手拖动 + 窗口高度自动
        # 补偿"，两版都改坏了别的行为（页脚被裁、高度被固定、抓手够不着）。
        # **用户放弃这个功能是对的**：需求本来就只是"拉高窗口 → 输入框变高"，
        # 而 grid 的行权重天然就是这个语义，一行代码都不用写。
        root.columnconfigure(0, weight=1)
        for row, weight in ((ROW_HINT, 0), (ROW_HEADER, 0), (ROW_SETTINGS, 0),
                            (ROW_EDITOR, 1), (ROW_DIRS, 0), (ROW_ACTION, 0),
                            (ROW_STATUS, 0), (ROW_FOOTER, 0)):
            root.rowconfigure(row, weight=weight)

        icon = platform_win.resource_path("images/Edge-TTS.ico")
        if os.path.exists(icon):
            self._set_window_icon(root)

        # 全界面的"文字→输入框/按钮 / 按钮→按钮"横向间距统一用 1 个正文空格。
        # 参数类别之间、末尾提示语前仍用 6 个空格（前一轮已定稿）。
        # 只在这里赋值一次；各处一律引用这两个名字，不再散落 SPACE_2/SPACE_3。
        body_font = self.theme.font(FONT_BODY_PT)
        self._gap_group = max(SPACE_5, body_font.measure("      "))
        self._gap_compact = max(SPACE_1, body_font.measure(" "))
        # 唯一例外：语音下拉框 → 筛选语音输入框，用户定稿单独给 2 空格。
        self._gap_filter = max(SPACE_2, body_font.measure("  "))

        # ---- 首次使用提示条 ------------------------------------------------
        # 提示条只在"用户还没关掉它"时出现；关掉之后靠编辑器里的占位提示、
        # 编辑区下方那行动态提示和「?」的完整说明接手。
        self.help_strip = tk.Frame(root, borderwidth=0, highlightthickness=1)
        self.help_strip.columnconfigure(0, weight=1)

        self.help_strip_text = tk.Label(
            self.help_strip, text="", anchor="w", justify="left", borderwidth=0
        )
        self.help_strip_text.grid(
            row=0, column=0, sticky="ew", padx=(SPACE_3, 0), pady=SPACE_2
        )

        self.help_strip_more = FlatButton(
            self.help_strip,
            L("全部提示", "All tips"),
            lambda: self.show_help(),
            kind="ghost",
            pad_x=SPACE_4,
            pad_y=SPACE_2,
        )
        self.help_strip_more.grid(row=0, column=1, padx=(self._gap_compact, 0))

        self.help_strip_close = FlatButton(
            self.help_strip,
            L("知道了", "Got it"),
            self.dismiss_hints,
            kind="ghost",
            pad_x=SPACE_4,
            pad_y=SPACE_2,
        )
        self.help_strip_close.grid(row=0, column=2, padx=(self._gap_compact, SPACE_2))

        # ---- 顶栏 ---------------------------------------------------------
        # 右侧那三颗按钮**只放图标**：标题栏要给提示条让出宽度，
        # 而"浅色/深色"与"设置"这两颗本来就没有几个字可省。
        # 图标按钮必须配悬停提示，否则就是"看起来能点却不知道是什么"。
        header = tk.Frame(root, borderwidth=0, highlightthickness=0)
        header.grid(row=ROW_HEADER, column=0, sticky="ew", padx=SPACE_5, pady=(SPACE_4, SPACE_2))
        header.columnconfigure(0, weight=1)

        self.title_label = tk.Label(
            header, text=L("文字转语音", "Text to Speech"), borderwidth=0, anchor="w"
        )
        self.title_label.grid(row=0, column=0, sticky="w")

        # 标题栏三颗按钮：**正方形**（用户定稿）。长方形的"?"看起来就是不对劲，
        # 而"正方"必须由边长定尺寸——`pad_x` 那套是按文字宽度算的，做不到。
        # 主题：**三颗图标按钮**（用户定稿）——显示器 = 跟随系统、太阳 = 浅色、
        # 月亮 = 深色。当前主题那一颗是**强调色实心**，一眼能看出现在是哪个。
        # 图标全用 Canvas 画，不写字形（emoji 在 Windows 上渲染不可控）。
        self.theme_buttons: dict = {}
        for column, (mode, title) in enumerate(
            (("system", "跟随系统"), ("light", "浅色"), ("dark", "深色")), start=1
        ):
            button = FlatButton(
                header,
                "",
                lambda value=mode: self.set_theme(value),
                kind="accent" if self.settings.theme == mode else "neutral",
                square=SQUARE_ICON_BUTTON,
                draw=icons_mod.THEME_ICONS[mode],
            )
            # sticky="e"：**必须给**。grid 会把多余空间摊给该行所有列，
            # 而 sticky 默认居中且拉伸——实测三颗图标按钮被拉成 661x52。
            button.grid(
                row=0,
                column=column,
                sticky="e",
                padx=(self._gap_compact if column > 1 else 0, 0),
            )
            self.theme_buttons[mode] = button
        self.theme_button = self.theme_buttons[self.settings.theme]

        self.settings_button = FlatButton(
            header,
            "",
            self.show_settings,
            kind="ghost",
            square=SQUARE_ICON_BUTTON,
            draw=icons_mod.SETTINGS_ICON,
        )
        self.settings_button.grid(row=0, column=4, sticky="e", padx=(self._gap_compact, 0))

        self.help_button = FlatButton(
            header,
            "?",
            lambda: self.show_help(),
            kind="ghost",
            square=SQUARE_ICON_BUTTON,
            bold=True,
            font_delta=3,
        )
        self.help_button.grid(row=0, column=5, sticky="e", padx=(self._gap_compact, 0))

        self.tooltips = [
            Tooltip(self.theme_buttons["system"], L("主题：跟随系统", "Theme: system"), self.theme),
            Tooltip(self.theme_buttons["light"], L("主题：浅色", "Theme: light"), self.theme),
            Tooltip(self.theme_buttons["dark"], L("主题：深色", "Theme: dark"), self.theme),
            Tooltip(self.settings_button, L("设置", "Settings"), self.theme),
            Tooltip(self.help_button, L("使用提示（Ctrl+H）", "Help (Ctrl+H)"), self.theme),
        ]

        # ---- 设置卡片 ------------------------------------------------------
        self.settings_card = tk.Frame(root, borderwidth=0, highlightthickness=0)
        self.settings_card.grid(row=ROW_SETTINGS, column=0, sticky="ew", padx=SPACE_5, pady=(0, SPACE_3))
        self.settings_card.columnconfigure(0, weight=1)

        voice_row = tk.Frame(self.settings_card, borderwidth=0, highlightthickness=0)
        voice_row.grid(row=0, column=0, sticky="ew", padx=SPACE_3, pady=(SPACE_3, SPACE_1))
        # col 4 是弹性空白：语音框 + 筛选框 + 计数按顺序靠左排，
        # 不再让语音框把整行剩余宽度全吃掉。
        voice_row.columnconfigure(4, weight=1)
        self.voice_row = voice_row

        self.voice_caption = tk.Label(
            voice_row, text=L("语音", "Voice"), anchor="w", borderwidth=0
        )
        self.voice_caption.grid(row=0, column=0, padx=(0, self._gap_compact))

        self.voice_box_holder = tk.Frame(voice_row, borderwidth=0, highlightthickness=1)
        self.voice_box_holder.grid(row=0, column=1, sticky="w")
        self.voice_box = ttk.Combobox(
            self.voice_box_holder, state="readonly", height=18, width=30
        )
        # 宽度（字符数）在 `_fix_voice_width()` 里按主窗口比例设置。
        # 外层 holder 只负责**四边完整**的 1px 描边：ttk 的 clam 主题在去掉
        # downarrow 后右边框会缺失（用户截图），holder 补上更可靠。
        self.voice_box.pack(fill="both", expand=True)
        self.voice_box.bind("<<ComboboxSelected>>", lambda _e: self._on_voice_selected())
        self.voice_box.bind("<FocusIn>", lambda _e: self._paint_voice_border(True), add="+")
        self.voice_box.bind("<FocusOut>", lambda _e: self._paint_voice_border(False), add="+")

        self.voice_filter = tk.Entry(voice_row, borderwidth=0, highlightthickness=1, width=12)
        # 这是唯一单独给 2 空格的间距（用户 2026-10-18 定稿）。
        self.voice_filter.grid(row=0, column=2, sticky="ew", padx=(self._gap_filter, 0))
        self.voice_filter.bind("<KeyRelease>", lambda _e: self._refresh_voice_filter())
        self.voice_filter.bind("<Return>", lambda _e: self._focus_first_voice())
        self.voice_filter.bind("<Escape>", lambda _e: self._clear_voice_filter())
        self.voice_filter.bind("<FocusIn>", lambda _e: self._on_filter_focus(True))
        self.voice_filter.bind("<FocusOut>", lambda _e: self._on_filter_focus(False))

        self.voice_count = tk.Label(voice_row, text="", anchor="w", borderwidth=0)
        self.voice_count.grid(row=0, column=3, padx=(self._gap_compact, 0))

        params_row = tk.Frame(self.settings_card, borderwidth=0, highlightthickness=0)
        params_row.grid(row=1, column=0, sticky="ew", padx=SPACE_3, pady=(SPACE_1, SPACE_3))

        # 三个参数类之间、以及末尾提示语之前仍用 6 个空格（_gap_group）。
        self._param_captions = {}
        self.rate_entry = self._make_param(params_row, 0, "rate")
        self._make_param_suffix(params_row, 2, "%")
        self.volume_entry = self._make_param(params_row, 3, "volume")
        self._make_param_suffix(params_row, 5, "%")
        self.pitch_entry = self._make_param(params_row, 6, "pitch")
        self._make_param_suffix(params_row, 8, "Hz")
        # 上一次的有效值：超范围/写错时恢复到这里，而不是留一个坏值。
        self._param_last_valid = {}
        for field, entry in (
            ("rate", self.rate_entry),
            ("volume", self.volume_entry),
            ("pitch", self.pitch_entry),
        ):
            self._param_last_valid[field] = entry.get().strip() or "0"
            entry.bind(
                "<FocusOut>",
                lambda _event, current=field: self._commit_param(current),
                add="+",
            )
            entry.bind(
                "<Return>",
                lambda _event, current=field: self._commit_param(current),
                add="+",
            )
        self.tooltips.extend(
            [
                Tooltip(
                    self.rate_entry,
                    L(
                        "语速范围 -100 到 +200（%）；可填 20、+20%、1.2x",
                        "Rate range -100 to +200 (%); 20, +20%, 1.2x accepted",
                    ),
                    self.theme,
                ),
                Tooltip(
                    self.volume_entry,
                    L(
                        "音量范围 -100 到 +100（%）；相对原声，+100% 约 +3.5 dB",
                        "Volume range -100 to +100 (%); relative, +100% is about +3.5 dB",
                    ),
                    self.theme,
                ),
                Tooltip(
                    self.pitch_entry,
                    L("音调范围 -100 到 +100（Hz）", "Pitch range -100 to +100 (Hz)"),
                    self.theme,
                ),
            ]
        )

        self.params_hint = tk.Label(params_row, text="", anchor="w", borderwidth=0)
        self.params_hint.grid(
            row=0, column=9, padx=(self._gap_group, 0), sticky="w"
        )

        # ---- 编辑区卡片 ----------------------------------------------------
        # **编辑区那一行的最小高度 = 它的初始高度**（用户定稿："初始高度=最小高度"）。
        # 首帧布局稳定后量一次写进去；窗口再小也不许把输入框压到它以下。
        self.root.after(150, self._lock_editor_min_height)
        self._editor_initial_height = 0
        self.editor_card = tk.Frame(root, borderwidth=0, highlightthickness=0)
        self.editor_card.grid(row=ROW_EDITOR, column=0, sticky="nsew", padx=SPACE_5)
        self.editor_card.rowconfigure(1, weight=1)
        self.editor_card.columnconfigure(0, weight=1)

        editor_head = tk.Frame(self.editor_card, borderwidth=0, highlightthickness=0)
        editor_head.grid(row=0, column=0, sticky="ew", padx=SPACE_3, pady=(SPACE_3, SPACE_1))
        editor_head.columnconfigure(0, weight=1)

        self.editor_caption = tk.Label(
            editor_head, text=L("要朗读的文字", "Text to read"), anchor="w", borderwidth=0
        )
        self.editor_caption.grid(row=0, column=0, sticky="w")

        self.paste_button = FlatButton(
            editor_head, L("读入文件", "Load file"), lambda: self.open_text_file(), kind="ghost", pad_x=SPACE_4, pad_y=SPACE_2
        )
        self.paste_button.grid(row=0, column=1, padx=(self._gap_compact, 0))
        self.clear_button = FlatButton(
            editor_head, L("清空", "Clear"), self.clear_text, kind="ghost", pad_x=SPACE_4, pad_y=SPACE_2
        )
        self.clear_button.grid(row=0, column=2, padx=(self._gap_compact, 0))

        # 描边颜色由 _apply_theme 按主题设置（焦点时用强调色）。这里不写字面量：
        # 这一层是"能点的地方看起来能点"的那个视觉线索（规范 20.7）。
        self.editor_border = tk.Frame(
            self.editor_card, borderwidth=0, highlightthickness=1
        )
        self.editor_border.grid(row=1, column=0, sticky="nsew", padx=SPACE_3)
        self.editor_border.rowconfigure(0, weight=1)
        self.editor_border.columnconfigure(0, weight=1)

        # height 是**下限**（Tk 按它算"最小需要多少"），实际高度由行权重决定；
        # 取 6 行是为了让窗口小到 620x520 时也还看得出这是个输入框。
        self.text = tk.Text(self.editor_border, height=6, width=60)
        self.text.grid(row=0, column=0, sticky="nsew")
        # **自绘扁平滚动条**：`ttk.Scrollbar` 在 Windows 上走原生主题绘制，
        # 两端箭头与滑块抓手纹都是"拟物"的，跟本工程扁平风格不搭
        # （用户实测反馈）。接口与 ttk 一致，`set` / `command` 用法不变。
        self.text_scroll = FlatScrollbar(
            self.editor_border, command=self.text.yview, theme=self.theme
        )
        self.text_scroll.grid(row=0, column=1, sticky="ns")
        self.text.configure(yscrollcommand=self.text_scroll.set)
        # 输入**之前**摘掉占位提示，输入之后再核对一次内容。
        # 两条都要：`<KeyPress>` 覆盖键盘与 Ctrl+V，`<<Paste>>`/`<<Cut>>`/
        # `<<Undo>>` 覆盖不走键盘的那几条路（菜单、输入法、脚本）。
        self.text.bind("<KeyPress>", self._drop_placeholder_at_edit_time)
        self.text.bind("<<Paste>>", self._drop_placeholder_at_edit_time)
        self.text.bind("<Button-2>", self._drop_placeholder_at_edit_time)
        self.text.bind("<Button-3>", self._drop_placeholder_at_edit_time)
        self.text.bind("<KeyRelease>", self._on_committed_edit_paste)
        self.text.bind("<<Paste>>", self._on_committed_edit_paste, add="+")
        self.text.bind("<<Cut>>", self._on_committed_edit_paste, add="+")
        self.text.bind("<<Undo>>", self._on_committed_edit_paste, add="+")
        self.text.bind("<<Redo>>", self._on_committed_edit_paste, add="+")
        self.text.bind("<<PasteSelection>>", self._on_committed_edit_paste, add="+")
        self.text.bind("<FocusIn>", lambda _e: self._paint_editor_border())
        self.text.bind("<FocusOut>", lambda _e: self._paint_editor_border())

        self.editor_tip = tk.Label(
            self.editor_card, text="", anchor="w", justify="left", borderwidth=0
        )
        # 底部留 0：下面那条"输出目录"排要**紧贴**它，不留空行
        self.editor_tip.grid(row=2, column=0, sticky="ew", padx=SPACE_3, pady=(SPACE_1, 0))

        # ---- 「输出目录」那一排：紧贴编辑区下方、在进度条上方 --------------
        #
        # 用户定稿："让『输出目录』这一行放在输入框下方、灰色说明文字的下方，
        # 不要空行；并且它仍然在平时隐藏的进度条上方。"
        #
        # ⚠️ 它是 **root 上独立的一行**（`ROW_DIRS`），不是编辑区内部的一行：
        # 塞进编辑区会把文本框挤扁（实测 256px → 54px，占位提示被裁掉，
        # 门禁的阳性/阴性对照当场报错）。独立成行则高度互不影响。
        self.directory_row = tk.Frame(root, borderwidth=0, highlightthickness=0)
        self.directory_row.grid(row=ROW_DIRS, column=0, sticky="ew", padx=SPACE_5, pady=(0, SPACE_2))
        self.directory_row.columnconfigure(2, weight=1)

        # 「输出目录」= 原来的「所在文件夹」改名而来，**常驻**：
        # 点它在资源管理器里打开产物/输出目录。
        self.output_dir_button = FlatButton(
            self.directory_row, L("输出目录", "Output"), self.reveal_output_dir, kind="ghost",
            pad_x=SPACE_4, pad_y=SPACE_2,
        )
        # **再次交换**（用户定稿）：「选择…」在前、「输出目录」在后。
        self.output_dir_button.grid(
            row=0, column=1, sticky="w",
            padx=(self._gap_compact, self._gap_compact),
        )

        self.choose_dir_button = FlatButton(
            self.directory_row, L("选择…", "Pick"), self.choose_output_dir, kind="neutral",
            pad_x=SPACE_4, pad_y=SPACE_2, min_chars=2,
        )
        self.choose_dir_button.grid(row=0, column=0, sticky="w")

        self.directory_label = tk.Label(self.directory_row, text="", anchor="w", borderwidth=0)
        self.directory_label.grid(row=0, column=2, sticky="w")

        # （「打开音频」不在这里——它在操作区，见后面的"同一行"那一段。
        #   这里曾经**重复创建过一次** `open_file_button`，被后面的定义覆盖，
        #   于是"放在「选择…」正下方"这个要求实际上从未生效、还把那排的间距
        #   带偏了。**同一个控件只创建一次**。）

        # 兼容旧名字：`open_folder_button` 现在指同一颗按钮（它在那一排里）。
        self.open_folder_button = self.output_dir_button

        # ---- 操作区 --------------------------------------------------------
        action = tk.Frame(root, borderwidth=0, highlightthickness=0)
        action.grid(row=ROW_ACTION, column=0, sticky="ew", padx=SPACE_5, pady=(SPACE_3, SPACE_2))
        # ⚠️ 操作区的高度**必须显式给**：这一行里的控件全用 `place` 定位
        # （为了让"进度条 / 打开音频 / 生成语音"在三种状态下坐标不动），
        # 而 `place` 的子控件**不参与父容器的尺寸计算**——不给高度的话
        # 整个操作区只有 1px，下面的状态栏、页脚会被顶上来看不见（实测）。
        # 高度取「生成语音」的自然高度，在 `_fix_progress_slot` 里设。
        action.grid_propagate(False)
        # ⚠️ 第 0 列要 `weight=1`（否则没人填满宽度，进度条会缩成 1px）。
        # **第 1/2 列是空的，只用来"占位"**：`minsize` 分别等于「取消」和
        # 「生成语音」的宽度。它们自己用 `place` 定位（见下面），grid 不知道
        # 它们有多宽；不占位的话，第 0 列会把整行剩余宽度全吃掉，进度条和
        # 百分比就**钻到按钮底下**去了（实测：holder 1111px，取消从 981 开始，
        # 百分比文字 1034 起——完全被盖住）。
        action.columnconfigure(0, weight=1)
        action.columnconfigure(1, minsize=0)
        action.columnconfigure(2, minsize=0)
        # ⚠️ **行权重也必须给**：操作区里真正参与 grid 的只有
        # `progress_holder`（请求高度 1px），另外两颗按钮都是 `place` 的。
        # 行权重为 0 时，这一行只有 1px 高，holder 也就 1px ——
        # 于是进度条（35px）和「打开音频」（58px）只露出中间一条线，
        # 用户看到的就是"进度条展不开 / 打开音频不显示"（2026-10-17 实测）。
        # 给行权重 1 + holder `sticky="nsew"`，holder 才会铺满 58px。
        action.rowconfigure(0, weight=1)
        self.action_bar = action

        # ---- 同一行：[进度条 / 打开音频] [取消] [生成语音] -------------------
        #
        # 用户定稿的显示逻辑（三者**同一行**）：
        #   平时      → 进度条与「打开音频」都隐藏
        #   生成中    → 显示进度条
        #   生成完毕  → 隐藏进度条、显示「打开音频」
        #
        # 能共用同一个位置，是因为**进度条和「打开音频」在时间上互斥**，
        # 永远不会同时出现。
        #
        # ## 布局怎么做到"三种状态一颗按钮都不动"
        #
        # 关键是让**每一列的宽度都固定**，不随"此刻谁可见"变化：
        #
        #   col 0  weight=1，`minsize` = 它自己的初始宽度
        #          → 永远撑着"进度条 / 打开音频"的坑位，吸收窗口宽度的变化
        #   col 1  「取消」+ 一个**常驻的占位控件**（宽度 = 2×需求宽度）
        #          → 「取消」显不显示，这一列都占同样的宽度
        #   col 2  「生成语音」，`sticky="e"` 右对齐
        #
        # ⚠️ 走过的弯路，记下来别重犯：我先用"量出可用宽度、把 col 0 的
        # `minsize` 设成那个值"的写法，结果 `<Configure>` 会自我反馈振荡
        # （设 minsize → 触发 Configure → 再设一次），列宽在 1106↔959 之间
        # 反复跳，进度条跟着抖。**让控件自己撑住宽度，比算宽度可靠。**
        self.progress_holder = tk.Frame(action, borderwidth=0, highlightthickness=0, height=1)
        self.progress_holder.grid(row=0, column=0, sticky="nsew", padx=(0, SPACE_3))

        # 「取消」与「生成语音」一样锚在右边缘（位置由 `_fix_progress_slot`
        # 统一设定），不用 grid——避免两套布局机制互相干扰。
        self.cancel_button = FlatButton(
            action, L("取消", "Cancel"), self.cancel_generation, kind="neutral"
        )

        self.generate_button = FlatButton(
            action, L("生成语音", "Generate"), self.start_generation, kind="accent",
            pad_x=SPACE_5, pad_y=SPACE_2,
        )
        # ⚠️ 「生成语音」用 **`place` 相对右边缘定位**，不用 grid。
        #
        # 为什么：它的 x 坐标必须**在三种状态下完全一致**（用户要求
        # "进度条 / 打开音频 / 生成语音 全是同一行的内容"，切换时按钮不能动）。
        # 试过把它放进 grid 的右列，但 grid 在"生成时多出一个「取消」"的情况下
        # 分配会变，坑位宽度实测 963↔959，按钮跟着移 4px——查了四轮都在这个
        # 分配细节上打转。**锚定到右边缘就不依赖列分配了**，一次到位。
        self.generate_button.place(relx=1.0, rely=0.5, anchor="e")

        # 进度条与「打开音频」都 `place` 在坑位里：它们不参与 grid 的尺寸计算，
        # 所以"谁可见"不会影响列宽。
        self.progress = FlatProgress(self.progress_holder, theme=self.theme)
        self.progress.place(x=0, rely=0.5, anchor="w", relwidth=1.0)

        self.open_file_button = FlatButton(
            self.progress_holder, L("打开音频", "Open audio"), self.open_result, kind="ghost",
            pad_x=SPACE_4, pad_y=SPACE_2,
        )
        # 平时必须隐藏：它只在生成完成后出现（用户定稿的第 1 条）
        self.open_file_button.place_forget()

        # （「打开音频」不在这里——它搬到了上面那一排的「选择…」正下方）

        # ⚠️ **平时必须把它们藏起来**（用户实测报回来的严重观感问题：
        # "我没有粘贴文字，也没有启动转语音，这个空进度条和取消按钮放在这里
        # 是什么意思"）。
        #
        # 这两句原本就在，是我上一轮做整块替换时**连同它们一起删掉了**——
        # 替换锚点覆盖的范围比我想的大。判据：启动后进度条不可见。
        self.progress.place_forget()
        self.cancel_button.place_forget()

        # ---- 状态栏（状态文字 + 字数，合成一个紧贴左下的块）------------------
        #
        # 这一处的取舍走过五圈，结论记在这里（判据：两行之间**不能有人工空档**）：
        #   * 统计放右边            → 破坏"状态栏信息都在左下"的视觉连续性
        #   * 统计 row0 / 状态 row1 → 方向反了（统计跑到顶上）
        #   * 状态区锁 3 行高        → 状态只有一行时中间留 60px 空白
        #   * 两行都 weight=1       → 空的那一行也分走一半高度（空状态栏 76px）
        #   * 只锁卡片总高度         → 与内容高度对不齐，统计抖 4px
        #
        # 走对的写法：两行放进一个内部 Frame，块自己贴左下角——
        # 块内 `pack` 顺序排列，两行天然紧贴；状态为空时 `pack_forget()`
        # 让块自动变矮；整块贴左下，多余空间只落在下方。
        self.status_card = tk.Frame(root, borderwidth=0, highlightthickness=0)
        self.status_card.grid(row=ROW_STATUS, column=0, sticky="ew", padx=SPACE_5, pady=(0, 0))
        self.status_card.columnconfigure(0, weight=1)

        self.status_block = tk.Frame(self.status_card, borderwidth=0, highlightthickness=0)
        self.status_block.grid(row=0, column=0, sticky="sw", padx=(SPACE_3, 0))
        # 进度详情（"已生成 13.0 / 约 45 秒音频 · 75.9 KB"）**放这里而不是
        # 操作区**：操作区那一行的高度由「生成语音」的 58px 决定，进度条 +
        # 百分比 + 详情三样叠起来要 78px，会把整行撑高、按钮跟着变高——
        # 那正是用户不要的。状态区本来就支持按内容增高（有窗口补偿兜着）。
        self.progress_detail = tk.Label(
            self.status_block, text="", anchor="w", justify="left",
            borderwidth=0, wraplength=720,
        )
        # ⚠️ **不要在这里 pack**：它只在生成过程中显示，而空标签也会占一行
        # 高度。第一版建好就 pack，启动时状态区凭空多 30px（实测
        # status_card 90px 而不是 60px），下面几段被挤、页脚被裁。
        # 显隐统一由 `_show_progress_detail()` 管。
        self.status_label = tk.Label(
            self.status_block, text="", anchor="w", justify="left", borderwidth=0, wraplength=720
        )
        self.counts_label = tk.Label(
            self.status_block, text="", anchor="w", justify="left", borderwidth=0, wraplength=720
        )
        self.counts_label.pack(side=tk.BOTTOM, anchor="w", fill="x")

        #: 只有「打开音频」是"生成完成后才显示"的产物按钮。
        #: 「所在文件夹」已改名成「输出目录」、常驻，并搬到下面那一排里了
        #: （用户定稿：那一排 = 输出目录按钮 + 选择按钮 + 灰色路径）。
        self.result_buttons = (self.open_file_button,)

        # ---- 底部：只剩版本号 ----------------------------------------------
        # 版本号紧贴状态栏：中间不留空行（用户定稿："右下角版本标识符和状态栏
        # 之间不要空行，不然留白太多，很丑"）。所以 `pady` 的顶部为 0，
        # 底部只留一点点贴边余量。
        self.footer = tk.Frame(root, borderwidth=0, highlightthickness=0)
        self.footer.grid(row=ROW_FOOTER, column=0, sticky="ew", padx=SPACE_5, pady=(0, SPACE_1))
        self.footer.columnconfigure(0, weight=1)

        self.version_label = tk.Label(self.footer, text="", anchor="e", borderwidth=0)
        self.version_label.grid(row=0, column=0, sticky="e")

        # 所有控件都建好之后再做"需要读别的控件"的初始化
        self.version_label.configure(text=f"{APP_DISPLAY_NAME} {APP_VERSION}")
        self._update_directory_label()
        self._set_placeholder()
        self._update_counts()
        self._update_hint_strip()

    # ------------------------------------------------------------ 使用提示

    # 这条提示**量过宽度**：窗口默认 880 逻辑像素，提示条扣掉两颗按钮后可用
    # 约 545 像素（10pt 下）。这句话约 300 像素，留得下余量；
    # 原来那句 700+ 像素的会被截断——**被截断的提示等于没有提示**
    # （规范 20.8：文案长度是排版问题，不是文案问题）。
    def _hint_strip_text(self) -> str:
        return L(
            "三步：粘贴文字 → 选语音 → 点「生成语音」",
            "Three steps: paste text → choose a voice → Generate",
        )

    def _filter_placeholder(self) -> str:
        return L("筛选语音", "Filter voices")

    def _update_hint_strip(self) -> None:
        """提示条：显示或收起，**只看一个开关**。

        文案量过宽度：窗口默认 880 逻辑像素，提示条可用宽度约 860-按钮；
        这句话在 10pt 下约 620 像素，**放得下**（原来那句 700+ 会被截断）。
        """
        if self.settings.show_hints:
            self.help_strip_text.configure(text=self._hint_strip_text())
            self.help_strip.grid(
                row=ROW_HINT, column=0, sticky="ew", padx=SPACE_5, pady=(SPACE_4, 0)
            )
        else:
            self.help_strip.grid_remove()

    def _update_filter_placeholder(self) -> None:
        current = self.voice_filter.get().strip()
        old = ("", "筛选语音", "Filter voices")
        if current in old:
            self.voice_filter.delete(0, tk.END)
            if not self.voice_filter.focus_get() == self.voice_filter:
                self.voice_filter.insert(0, self._filter_placeholder())
        self._style_voice_filter()

    def _on_filter_focus(self, focused: bool) -> None:
        """筛选框的占位提示：**看起来能点**是它存在的理由（规范 20.7）。"""
        placeholder = self._filter_placeholder()
        if focused and self.voice_filter.get() == placeholder:
            self.voice_filter.delete(0, tk.END)
        elif not focused and not self.voice_filter.get().strip():
            self.voice_filter.insert(0, placeholder)
        self._style_voice_filter()

    def _paint_voice_border(self, focused: bool = False) -> None:
        """语音框外层 holder 的 1px 四边描边（ttk 的右边框不可靠）。"""
        try:
            palette = self.theme.palette
            color = palette.accent if focused else palette.border_strong
            self.voice_box_holder.configure(
                background=palette.surface_alt,
                highlightbackground=color,
                highlightcolor=color,
            )
        except (tk.TclError, AttributeError):
            return

    def _style_voice_filter(self) -> None:
        """占位提示是**提示**，不是值：灰色、小字号，与正文输入区分开。

        用户 2026-10-17："筛选语音四个字和按钮/标题颜色、明暗、大小完全一样，
        会分不清它是按钮还是提示。" 有内容时恢复正文色/正文字号。
        """
        placeholder = self.voice_filter.get().strip() in (
            "筛选语音", "Filter voices"
        )
        palette = self.theme.palette
        self.voice_filter.configure(
            foreground=palette.text_secondary if placeholder else palette.text,
            font=self.theme.font(FONT_SMALL_PT if placeholder else FONT_BODY_PT),
        )
        self._sync_filter_height()

    def _sync_filter_height(self) -> None:
        """让筛选框高度与语音选择框对齐；占位小字号时用 ipady 补回来。"""
        try:
            target = self.voice_box_holder.winfo_reqheight()
            if target <= 1:
                target = self.voice_box.winfo_reqheight()
            current = self.voice_filter.winfo_reqheight()
            pad = max(0, (target - current) // 2)
            info = self.voice_filter.grid_info()
            if int(info.get("ipady") or 0) != pad:
                self.voice_filter.grid_configure(ipady=pad)
        except (tk.TclError, TypeError, ValueError):
            return

    def dismiss_hints(self) -> None:
        self.settings.show_hints = False
        self._save_settings()
        self._update_hint_strip()
        self.set_status(
            L(
                "已收起使用提示。需要时点右上角的「?」，或按 Ctrl+H。",
                "Tips hidden. Click ? or press Ctrl+H to show them again.",
            ),
            "info",
        )

    def show_hints_again(self) -> None:
        self.settings.show_hints = True
        self._save_settings()
        self._update_hint_strip()

    def _make_param(self, parent, column: int, field: str) -> tk.Entry:
        caption = tk.Label(parent, text=param_label(field), anchor="w", borderwidth=0)
        self._param_captions[field] = caption
        # 类别之间留 6 个空格；标签与自己的输入框之间统一 1 个空格。
        caption.grid(
            row=0,
            column=column,
            padx=(0 if column == 0 else self._gap_group, self._gap_compact),
            sticky="w",
        )
        # 上下限最多 4 个字符（-100 / +200），留出光标位置即可，不按 6 字宽。
        entry = tk.Entry(
            parent, width=4, borderwidth=0, highlightthickness=1, justify="right"
        )
        entry.grid(row=0, column=column + 1, sticky="w")
        return entry

    def _make_param_suffix(self, parent, column: int, text_value: str) -> tk.Label:
        """参数输入框后面的单位（``%`` / ``Hz``），紧贴输入框。"""
        suffix = tk.Label(parent, text=text_value, anchor="w", borderwidth=0)
        suffix.grid(row=0, column=column, padx=(self._gap_compact, 0), sticky="w")
        return suffix

    def _center_window(self, width: int, height: int) -> None:
        """定尺寸并居中。

        **不要在内容建好之前调 ``update_idletasks()``**：那会让 Tk 按"当前
        需要的尺寸"重算窗口，把这个 geometry 顶掉（实测 880x720 变成 517x443）。
        屏幕尺寸直接问 Tk，不需要先布局。
        """
        screen_w = self.root.winfo_screenwidth()
        screen_h = self.root.winfo_screenheight()
        width = min(width, max(WINDOW_MIN_WIDTH, screen_w - 80))
        height = min(height, max(WINDOW_MIN_HEIGHT, screen_h - 120))
        x = max(0, (screen_w - width) // 2)
        y = max(0, (screen_h - height) // 3)
        self.root.geometry(f"{width}x{height}+{x}+{y}")
        if os.environ.get("ETTS_DEBUG_GEOMETRY"):
            # 诊断输出不能有能力把程序弄崩：冻结成 windowed exe 时没有 stdout
            platform_win.report(
                f"[geometry] screen={screen_w}x{screen_h} want={width}x{height}+{x}+{y} "
                f"tk_says={self.root.winfo_geometry()}"
            )

    # ------------------------------------------------------------------ 主题

    def _apply_theme(self) -> None:
        """把主题刷到**整棵控件树**上。

        为什么是"走一遍树"而不是"手写一份控件清单"：清单漏了谁，谁就永远
        用系统默认色——实测"语速 % / 音量 % / 音调 Hz"三个标签就是这样漏掉
        的，在深色主题下变成浅色块（用户实测报回来）。**清单会漏，遍历不会。**

        需要自己处理子控件的复合控件（`FlatButton`）与 ttk 控件跳过遍历：
        前者的子 label 由它自己上色，后者的样式由 ttk style 管。
        """
        palette = self.theme.palette
        theme = self.theme
        root = self.root

        # ⚠️ **根窗口自己也要设色**，这一步踩过一次：
        # `_theme_widget_tree` 只遍历**子控件**，根窗口不在其中。于是深色主题下
        # 子控件全是深色，唯独根窗口是 `SystemButtonFace`（浅色）——它从
        # 分区之间的间隙、以及四周留白里露出来，看起来就是"面板没有变深"，
        # 而每个控件单独看都是对的。用户实测报回来的就是这个现象。
        root.configure(background=palette.background)

        theme.apply_ttk_style(root)

        body = theme.font(FONT_BODY_PT)
        small = theme.font(FONT_SMALL_PT)
        title = theme.font(FONT_TITLE_PT, bold=True)

        # ---- 第一步：整棵树 ------------------------------------------------
        self._theme_widget_tree(
            root,
            frame_bg=palette.background,
            label_bg=palette.background,
            label_fg=palette.text,
            font=body,
        )

        # ---- 第二步：需要额外待遇的几个控件 --------------------------------
        theme.style_text_widget(self.text)

        for entry in (self.rate_entry, self.volume_entry, self.pitch_entry, self.voice_filter):
            entry.configure(
                background=palette.surface,
                foreground=palette.text,
                insertbackground=palette.text,
                selectbackground=palette.selection,
                selectforeground=palette.text,
                highlightbackground=palette.border,
                highlightcolor=palette.accent,
                font=body,
                relief="flat",
            )
        self.voice_filter.configure(width=14)

        # 面板只有一种底色，所以"信息条"不再用色块，只用一条描边。
        self.help_strip.configure(
            background=palette.background,
            highlightbackground=palette.border_strong,
            highlightcolor=palette.border_strong,
            highlightthickness=theme.px(1),
        )
        self.help_strip_text.configure(
            background=palette.background, foreground=palette.text, font=body
        )
        # ⚠️ **不再给状态栏描边**：它现在是一行信息（左边状态、右边字数），
        # 不是一块"卡片"。空着的时候那圈边框是最扎眼的东西（用户实测反馈
        # "状态栏是空的，不够美观"）。这里显式设 0，否则 `_apply_theme`
        # 会把建控件时设的 0 又改回 1 像素。
        self.status_card.configure(
            background=palette.background,
            highlightbackground=palette.background,
            highlightcolor=palette.background,
            highlightthickness=0,
        )
        self.status_label.configure(
            background=palette.background, foreground=palette.text, font=small,
            wraplength=theme.px(560),
        )
        self.editor_border.configure(background=palette.background)

        self.title_label.configure(
            background=palette.background, foreground=palette.text, font=title
        )
        self.directory_label.configure(
            background=palette.background, foreground=palette.text_secondary, font=small
        )
        self.counts_label.configure(
            background=palette.background, foreground=palette.text_secondary, font=small
        )
        self.version_label.configure(
            background=palette.background, foreground=palette.text_secondary, font=small
        )
        self._set_caption(self.voice_caption, L("语音", "Voice"), body)
        self._set_caption(self.editor_caption, L("要朗读的文字", "Text to read"), body)
        for label in (self.params_hint, self.editor_tip, self.voice_count):
            label.configure(
                background=palette.background,
                foreground=palette.text_secondary,
                font=small,
            )
        # 进度详情并入状态区，用与状态/统计同一套次要文字样式
        self.progress_detail.configure(
            background=palette.background, foreground=palette.text_secondary, font=small
        )
        # 自绘进度条：换主题后自己重画（轨道与填充色都取自 palette）
        self.progress.theme = self.theme
        self.progress._paint()
        # 输入框的扁平滚动条也必须跟着换主题——它不在按钮树里，
        # 上一版漏了这一行，切浅色后仍是深色/黑色（用户 2026-10-17 报）。
        self.text_scroll.apply_theme(theme)

        # 筛选框的占位提示：只在没聚焦且没内容时显示
        if self.voice_filter.get().strip() in ("", "筛选语音", "Filter voices"):
            self.voice_filter.delete(0, tk.END)
            if self.root.focus_get() is not self.voice_filter:
                self.voice_filter.insert(0, self._filter_placeholder())
        self._style_voice_filter()
        # 语音框与筛选框使用同一种 1px 描边；语音框外层 holder 负责补右边。
        self.voice_filter.configure(
            highlightbackground=palette.border_strong,
            highlightcolor=palette.accent,
        )
        self._paint_voice_border(self.root.focus_get() is self.voice_box)

        # ---- 第三步：按钮（同一套逻辑，除了生成按钮） ----------------------
        # **遍历，不写清单。** 这一处已经栽过三次：
        #   1. 手写清单漏了三个参数标签；
        #   2. 弹窗按钮不在清单里，永远是系统色；
        #   3. 新增的三颗主题图标按钮不在清单里，于是只有被
        #      `_update_theme_button()` 单独照顾到的那一颗拿到了主题，
        #      另两颗停在画布默认尺寸（661x463）。
        # 现在走一遍控件树把按钮收集起来——**漏不了**。
        for button in self._collect_buttons(root):
            button.apply_theme(theme)
        for button in self._collect_buttons(self._settings_window) if (
            self._settings_window is not None and self._settings_window.winfo_exists()
        ) else []:
            button.apply_theme(theme)
        switch = getattr(self, "_hints_switch", None)
        if switch is not None and switch.winfo_exists():
            switch.apply_theme(theme)

        # 提示框也要跟着换色，否则悬停时冒出上一套主题的颜色
        for tooltip in getattr(self, "tooltips", []):
            tooltip.update(theme=theme)

        self._paint_editor_border()
        self._update_theme_button()
        self._apply_voice_popdown_theme(theme)
        self._refresh_voice_values(keep_selection=True)
        self._update_counts()
        self._update_tip()
        self._fix_voice_width()

    def _apply_voice_popdown_theme(self, theme: Theme) -> None:
        """下拉弹层的滚动条与 listbox 跟着主题换色。

        ⚠️ listbox 是 ttk 用 Tcl 提前建好的：**option_add 不会改已存在的
        控件**，所以切到深色后它仍会是浅色。这里直接 `configure` 回读路径。
        """
        bar = getattr(self, "_voice_pop_scrollbar", None)
        if bar is not None and bar.winfo_exists():
            bar.apply_theme(theme)
        listbox = getattr(self, "_voice_popdown_listbox", None)
        if not listbox:
            return
        palette = theme.palette
        try:
            self.root.tk.call(
                listbox, "configure",
                "-background", palette.surface_alt,
                "-foreground", palette.text,
                "-selectbackground", palette.accent,
                "-selectforeground", palette.accent_text,
                "-font", theme.font(FONT_BODY_PT),
            )
        except tk.TclError:
            pass

    def _install_flat_voice_popdown(self) -> None:
        """把 ttk 下拉列表自带的拟物滚动条换成输入框同款扁平滚动条。

        ttk 的 combobox 弹层是它自己用 Tcl 建的（`.popdown.f`），滚动条固定叫
        `.f.sb`，`ConfigureListbox` 只会对它做 `grid` / `grid remove`。
        所以这里**保持同一个控件路径名**：销毁旧的 ttk scrollbar，在同一个
        路径上创建 `FlatScrollbar`，再把 listbox 的 `yscrollcommand` 指过来。
        ttk 的展开/收起逻辑完全不用改。

        ⚠️ 弹层里的 frame 不是 tkinter 创建的，`nametowidget()` 查不到它
        （`KeyError: 'popdown'`）。用一个"只有 tk/_w/children 的代理"当父控件，
        让 `FlatScrollbar` 仍然能在正确的 Tcl 路径下建出来。
        """
        try:
            popdown = str(
                self.root.tk.call("ttk::combobox::PopdownWindow", self.voice_box._w)
            )
            frame = popdown + ".f"
            listbox = frame + ".l"
            self.root.tk.call("destroy", frame + ".sb")

            class _TclFrame:
                pass

            proxy = _TclFrame()
            proxy.tk = self.root.tk
            proxy._w = frame
            proxy.master = None
            proxy.children = {}
            bar = FlatScrollbar(
                proxy,
                command=lambda *args: self.root.tk.call(listbox, "yview", *args),
                theme=self.theme,
                name="sb",
            )
            scroll_command = self.root.register(bar.set)
            self.root.tk.call(listbox, "configure", "-yscrollcommand", scroll_command)
            self.root.tk.call(
                "grid", "configure", bar._w,
                "-row", 0, "-column", 1, "-sticky", "ns", "-padx", 0, "-pady", 1,
            )
            self.root.tk.call("grid", "remove", bar._w)
            self._voice_pop_scrollbar = bar
            self._voice_popdown_listbox = listbox
            self._apply_voice_popdown_theme(self.theme)
        except Exception:  # noqa: BLE001 - 换不上就退回 ttk 自带滚动条
            self._voice_pop_scrollbar = None

    @staticmethod
    def _collect_buttons(widget) -> list:
        """从 ``widget`` 往下收集**所有自绘按钮**。

        **为什么不写清单**：这一处栽过三次（漏参数标签、漏弹窗按钮、
        漏新增的主题图标按钮），所以改成遍历。任何新建的 ``FlatButton``
        只要挂在窗口上就会被收到——**漏不了**。
        """
        found: list = []
        stack = [widget]
        while stack:
            current = stack.pop()
            for child in current.winfo_children():
                if isinstance(child, FlatButton):
                    found.append(child)
                stack.append(child)
        return found

    def _theme_widget_tree(self, widget, frame_bg: str, label_bg: str, label_fg: str, font) -> None:
        """递归给容器与文字上色。

        ``frame_bg`` 给 Frame，``label_bg`` / ``label_fg`` 给 Label——
        两者分开是因为同一个容器里可能既有"画在面板上"的文字，
        也有"画在输入框上"的文字。
        """
        for child in widget.winfo_children():
            name = type(child).__name__
            if name == "FlatButton":
                # 它的子 label 由 FlatButton.apply_theme 自己管
                continue
            if name in ("TCombobox", "TProgressbar", "TScrollbar", "TSpinbox", "TSeparator"):
                continue  # ttk 的样式走 style.configure
            try:
                if name == "Text":
                    child.configure(
                        background=self.theme.palette.surface,
                        foreground=self.theme.palette.text,
                        insertbackground=self.theme.palette.text,
                        selectbackground=self.theme.palette.selection,
                        selectforeground=self.theme.palette.text,
                    )
                    self._theme_widget_tree(
                        child,
                        frame_bg=self.theme.palette.surface,
                        label_bg=self.theme.palette.surface,
                        label_fg=self.theme.palette.text,
                        font=font,
                    )
                    continue
                if name == "Entry":
                    child.configure(
                        background=self.theme.palette.surface,
                        foreground=self.theme.palette.text,
                        insertbackground=self.theme.palette.text,
                        selectbackground=self.theme.palette.selection,
                        selectforeground=self.theme.palette.text,
                    )
                    continue
                if name == "Label":
                    child.configure(background=label_bg, foreground=label_fg, font=font)
                    continue
                if name in ("Frame", "Toplevel"):
                    child.configure(background=frame_bg)
                    if int(child.cget("highlightthickness") or 0) > 0:
                        child.configure(
                            highlightbackground=self.theme.palette.border,
                            highlightcolor=self.theme.palette.border,
                        )
                else:
                    child.configure(background=frame_bg)
            except tk.TclError:
                continue
            self._theme_widget_tree(
                child, frame_bg=frame_bg, label_bg=label_bg, label_fg=label_fg, font=font
            )

    def _set_caption(self, label: tk.Label, text_value: str, font) -> None:
        label.configure(
            text=text_value,
            background=self.theme.palette.background,
            foreground=self.theme.palette.text,
            font=font,
        )

    def _paint_editor_border(self) -> None:
        palette = self.theme.palette
        focused = self.root.focus_get() is self.text
        color = palette.accent if focused else palette.border_strong
        self.editor_border.configure(
            highlightbackground=color, highlightcolor=color, highlightthickness=self.theme.px(1)
        )

    # ---- 版位自检 ----------------------------------------------------------
    #
    # 两件事只在**真实窗口里、用真实字体**才能量准，所以放在这里而不是工具里：
    #   ① 提示语放不放得下（被截断的提示等于没有提示）；
    #   ② 占位文字**完整占几行**（Tk 的 Text 不做垂直居中，内容比可视行数多
    #      就会被裁掉，而"看起来还在"最容易骗过截图）。
    # 判据都是回读到的像素值，不是"我觉得够宽"。

    def measure_text_px(self, text_value: str, font) -> int:
        """这段文字在当前字体下需要多少（逻辑）像素宽。"""
        import tkinter.font as tkfont  # pylint: disable=import-outside-toplevel

        return tkfont.Font(root=self.root, font=font).measure(text_value)

    def layout_findings(self) -> List[str]:
        """返回"版位上有问题"的清单；空列表表示都对。"""
        findings: List[str] = []
        body = self.theme.font(FONT_BODY_PT)

        # 判据是"提示条**容器**分给文字多少宽度"。用 label 自己的宽度是错的：
        # Tk 的 Label 会跟着文字长，于是"需要 700、分到 700"永远相等——
        # 第一版就是这么把一条被截断的提示判成没问题的（量错了对象）。
        strip_width = self.help_strip_text.master.winfo_width()
        needed = self.measure_text_px(self._hint_strip_text(), body)
        if self.settings.show_hints and needed > strip_width + 2:
            findings.append(
                L(
                    f"提示条文字需要 {needed} px，容器只有 {strip_width} px：会被截断",
                    f"Hint strip needs {needed} px but has {strip_width} px: it will be clipped",
                )
            )

        # 占位文字必须**完整显示**：Tk 的 Text 不做垂直居中，内容比可视行数多
        # 就会被从底部裁掉，而"看起来还在"最容易骗过截图。
        # 判据用 ``yview()``：内容全部放得下时它返回 ``(0.0, 1.0)``，
        # 有溢出时上界一定小于 1。**不要用 dlineinfo 数行数**——
        # 越出视口的行它返回 None，于是"被裁掉的那几行"根本数不到
        # （第一版就是这么把 8 行占位符判成"没问题"的）。
        if self._placeholder_active:
            top, bottom = self.text.yview()
            if top > 0.001 or bottom < 0.999:
                findings.append(
                    L(
                        f"编辑区占位文字放不下（yview={top:.3f}..{bottom:.3f}）：会被裁掉",
                        f"Editor placeholder does not fit (yview={top:.3f}..{bottom:.3f}): it will be clipped",
                    )
                )

        tip_width = self.editor_tip.winfo_width()
        tip_needed = self.measure_text_px(self.editor_tip.cget("text"), self.theme.font(FONT_SMALL_PT))
        if tip_needed > tip_width + 2:
            findings.append(
                L(
                    f"编辑区下方提示需要 {tip_needed} px，只有 {tip_width} px：会被截断",
                    f"Editor tip needs {tip_needed} px but has {tip_width} px: it will be clipped",
                )
            )
        return findings

    def _line_height(self, widget) -> int:
        """控件当前字体的行高（物理像素）；取不到返回 0。"""
        import tkinter.font as tkfont  # pylint: disable=import-outside-toplevel

        try:
            return int(tkfont.Font(root=self.root, font=widget.cget("font")).metrics("linespace"))
        except Exception:  # noqa: BLE001
            return 0

    def _lowest_display_line(self, widget) -> int:
        """控件里**真正画到的最低点**（相对控件顶部，物理像素）。

        比"行数 × 行高"可靠：它读的是 Tk 自己算出来的显示行位置
        （``dlineinfo``），换行、行距、空白行都算在里面。
        """
        lowest = 0
        index = 1
        try:
            while True:
                info = widget.dlineinfo(f"{index}.0")
                if info is None:
                    break
                lowest = max(lowest, int(info[1]) + int(info[3]))
                index += 1
                if index > 200:  # 保险丝：别在异常状态下转圈
                    break
        except Exception:  # noqa: BLE001
            return lowest
        return lowest

    def _update_theme_button(self) -> None:
        """把三颗主题按钮的选中态刷一遍。

        **"当前是哪一个"由按钮自己的外观表达**（选中的是强调色实心），
        不再靠文字标签——三颗图标按钮各自固定一个含义，不该再变。
        """
        current = self.settings.theme if self.settings.theme in ("system", "light", "dark") else "system"
        self.theme_button = getattr(self, "theme_buttons", {}).get(current, self.theme_button)
        for mode, button in getattr(self, "theme_buttons", {}).items():
            kind = "accent" if mode == current else "neutral"
            if button.kind != kind:
                button.kind = kind
                button.apply_theme(self.theme)
            else:
                button._paint()  # noqa: SLF001 - 同一套自绘逻辑，重画即最新

    def set_theme(self, mode: str) -> None:
        """把主题切到 ``mode``（三颗图标按钮各自调它，不再循环切换）。

        点当前那颗是幂等的——**不做"点了没反应"以外的任何事**，
        免得用户以为点错了。
        """
        if mode not in ("system", "light", "dark") or mode == self.settings.theme:
            return
        self.settings.theme = mode
        self.theme = Theme.detect(mode)
        self._apply_theme()
        self._refresh_open_dialogs()
        self._apply_window_chrome()
        self._save_settings()

    def toggle_theme(self) -> None:
        """保留一个循环切换的入口（键盘可达性 / 旧调用点）。"""
        order = ["system", "light", "dark"]
        current = self.settings.theme if self.settings.theme in order else "system"
        self.set_theme(order[(order.index(current) + 1) % len(order)])

    def _apply_window_chrome(self) -> None:
        """把所有**已经打开的窗口**的标题栏深浅同步到当前主题。

        ⚠️ 只设主窗口是不够的：实测切到浅色之后，主窗口的
        `DWMWA_USE_IMMERSIVE_DARK_MODE` 变成 0，而设置窗口仍然是 1——
        **用户看到的就是"设置窗口的标题栏没跟着主题变"**（他实测报回来）。
        这里遍历所有 Toplevel，一个都不漏。
        """
        self.root.update_idletasks()
        targets = [self.root]
        for window in self.root.winfo_children():
            if isinstance(window, tk.Toplevel) and window.winfo_exists():
                targets.append(window)
        for window in targets:
            try:
                window.update_idletasks()
            except tk.TclError:
                continue
            self._set_window_icon(window, tk_fallback=False)
            hwnd = platform_win.window_id_of(window)
            if hwnd:
                platform_win.apply_dark_titlebar(hwnd, self.theme.dark)

    def _refresh_open_dialogs(self) -> None:
        """主题变了：把已经打开的弹窗**重新按新主题设色**。

        不这么做的话，用户点"深色"时只有主窗口变，设置窗口自己还是旧主题——
        而那正是他正在看的那个窗口。
        """
        settings_window = getattr(self, "_settings_window", None)
        if settings_window is not None and settings_window.winfo_exists():
            palette = self.theme.palette
            settings_window.configure(background=palette.background)
            self._theme_widget_tree(
                settings_window,
                frame_bg=palette.background,
                label_bg=palette.background,
                label_fg=palette.text,
                font=self.theme.font(FONT_BODY_PT),
            )
            switch = getattr(self, "_hints_switch", None)
            if switch is not None and switch.winfo_exists():
                switch.apply_theme(self.theme)
        help_window = getattr(self, "_help_window", None)
        if help_window is not None and help_window.winfo_exists():
            # 提示窗口是只读文字，整体重建比逐个改色可靠（它没有状态）
            help_window.destroy()
            self._help_window = None
            self.show_help()

    # ------------------------------------------------------------------ 设置

    def _save_settings(self) -> None:
        self.settings.voice = self._selected_voice_name() or self.settings.voice
        # 关闭/保存时不允许把非法参数写进配置文件：静默退回上一次有效值。
        for field, entry in (
            ("rate", self.rate_entry),
            ("volume", self.volume_entry),
            ("pitch", self.pitch_entry),
        ):
            try:
                PARAM_SPECS[field][4](entry.get())
            except params_mod.ParameterError:
                fallback = self._param_last_valid.get(field, "0")
                entry.delete(0, tk.END)
                entry.insert(0, fallback)
        self.settings.rate = self.rate_entry.get().strip()
        self.settings.volume = self.volume_entry.get().strip()
        self.settings.pitch = self.pitch_entry.get().strip()
        proxy_var = getattr(self, "_proxy_var", None)
        if proxy_var is not None:
            self.settings.proxy = proxy_var.get().strip()
        try:
            self.settings.save()
        except OSError as exc:
            self.set_status(L(f"设置无法保存：{exc}", f"Could not save settings: {exc}"), "error")

    def _restore_settings_to_widgets(self) -> None:
        for field, entry, value in (
            ("rate", self.rate_entry, self.settings.rate),
            ("volume", self.volume_entry, self.settings.volume),
            ("pitch", self.pitch_entry, self.settings.pitch),
        ):
            entry.delete(0, tk.END)
            entry.insert(0, value or "0")
            try:
                normalized = PARAM_SPECS[field][4](entry.get())
                entry.delete(0, tk.END)
                entry.insert(0, self._param_display(field, normalized))
            except params_mod.ParameterError:
                entry.delete(0, tk.END)
                entry.insert(0, "0")
            self._param_last_valid[field] = entry.get().strip() or "0"
        self._update_params_hint()

    # ------------------------------------------------------------------ 语音

    def _load_voices(self) -> None:
        """后台拉语音列表。**在拿到之前界面照常可用**（用兜底清单）。"""
        self._restore_settings_to_widgets()
        self._refresh_voice_values(keep_selection=True)
        self._start_voice_fetch()

    def _start_voice_fetch(self) -> None:
        """按当前代理拉一次语音列表；代理改变后也会重跑。"""
        if self.voice_loading:
            self._voice_reload_pending = True
            return
        self._voice_reload_pending = False
        self.voice_loading = True
        self.voice_count.configure(text=L("加载中…", "Loading..."))
        self.set_status(L("正在获取语音列表…", "Loading voices..."), "info")

        proxy = self.settings.proxy_or_none()
        cancel = threading.Event()
        self._voice_cancel_event = cancel

        def worker() -> None:
            try:
                catalog = voices_mod.VoiceCatalog(
                    voices_mod.fetch_voices(
                        proxy=proxy, timeout=20.0, cancel=cancel
                    ),
                    loaded=True,
                )
            except voices_mod.VoiceFetchCancelled:
                return
            except Exception as exc:  # noqa: BLE001 - 网络/上游的任何失败都只影响列表
                if not cancel.is_set():
                    self.events.put(("voices_error", exc))
                return
            if not cancel.is_set():
                self.events.put(("voices", catalog))

        thread = threading.Thread(target=worker, name="voice-loader", daemon=True)
        self._voice_thread = thread
        thread.start()

    def _refresh_voice_values(self, keep_selection: bool = True) -> None:
        query = self._voice_filter_text()
        self._visible_voices = self.catalog.search(query) if query else list(self.catalog)
        self.voice_box.configure(values=[v.display for v in self._visible_voices])
        selected = self.settings.voice
        index = 0
        for position, voice in enumerate(self._visible_voices):
            if voice.short_name == selected:
                index = position
                break
        if self._visible_voices:
            self.voice_box.current(index)
        else:
            self.voice_box.set("")
        self._update_voice_count()

    def _update_voice_count(self) -> None:
        total = len(self.catalog)
        shown = len(getattr(self, "_visible_voices", []))
        if self.catalog_error:
            label = L("列表未加载", "Not loaded")
        elif not self.catalog.loaded:
            label = L(f"暂用 {shown} 项", f"Using {shown}")
        elif self._voice_filter_text():
            label = f"{shown} / {total}"
        else:
            label = L(f"共 {total} 项", f"{total} voices")
        self.voice_count.configure(text=label)
        # 计数文字宽度变了，语音框的可用宽度也要跟着重算
        self.root.after_idle(self._fix_voice_width)

    def _voice_filter_text(self) -> str:
        """筛选词；占位提示不算用户输入。"""
        value = self.voice_filter.get().strip()
        return "" if value in ("筛选语音", "Filter voices") else value

    def _refresh_voice_filter(self) -> None:
        self._refresh_voice_values()
        hint = voices_mod.VoiceCatalog(self._visible_voices).search(self._voice_filter_text())
        if self._voice_filter_text() and not hint:
            self.set_status(
                L(
                    f"没有匹配「{self._voice_filter_text()}」的语音",
                    f'No voices match "{self._voice_filter_text()}"',
                ),
                "warning",
            )
        else:
            self.set_status("", "info")

    def _clear_voice_filter(self) -> None:
        self.voice_filter.delete(0, tk.END)
        self._style_voice_filter()
        self._refresh_voice_values()

    def _focus_first_voice(self) -> None:
        self.voice_box.focus_set()
        if self._visible_voices:
            self.voice_box.current(0)
            self._on_voice_selected()
            self.voice_box.event_generate("<Button-1>")

    def _selected_voice(self) -> Optional[voices_mod.Voice]:
        index = self.voice_box.current()
        visible = getattr(self, "_visible_voices", [])
        if 0 <= index < len(visible):
            return visible[index]
        return None

    def _selected_voice_name(self) -> str:
        voice = self._selected_voice()
        return voice.short_name if voice else ""

    def _on_voice_selected(self) -> None:
        voice = self._selected_voice()
        if voice is not None:
            self.settings.voice = voice.short_name
            self._save_settings()
            self.set_status("", "info")

    # ------------------------------------------------------------------ 文本

    # ---- 占位提示 ----------------------------------------------------------
    #
    # ⚠️ **这里踩过一个真缺陷，成因值得记下来。**
    #
    # 第一版把占位提示当成普通文本插进去，并绑 `<<Modified>>` 来"发现用户
    # 开始打字"。守卫写的是：
    #
    #     if not self.text.edit_modified():   # ← 旗子被自己清了
    #         return
    #
    # 但 `_on_modified` 结尾会调 `edit_modified(False)`，**而那本身又会触发
    # 一次 `<<Modified>>`**。两次通知的先后由 Tk 决定：旗子先被清掉时，
    # 用户那次真实的 Ctrl+V 就被守卫挡在外面——占位提示留在原地，而粘贴的
    # 内容插到了它**前面**，于是校验说"编辑区是空的"。
    #
    # 现在的做法是**不靠这面旗子**：直接比"控件里的文本是否还是那句占位符"，
    # 并在用户真正改动的那些事件上检查。判据是内容，不是状态位。
    #
    # 另外把插入点放到占位提示的**末尾**：不然 Ctrl+V 会插到提示前面。

    def _set_placeholder(self) -> None:
        """把占位提示放进去，并把插入点放到它的**末尾**。

        插入点放在末尾是因为：不放的话 Tk 把它留在 1.0，于是 Ctrl+V 会把
        内容插到提示**前面**（第一版就是这个现象）。
        """
        self.text.configure(state="normal")
        self.text.delete("1.0", tk.END)
        self.text.insert("1.0", placeholder_text())
        self.text.tag_add("placeholder", "1.0", "end-1c")
        self.text.mark_set("insert", "end-1c")
        self._placeholder_active = True
        self.text.edit_modified(False)

    def _placeholder_range(self) -> Optional[tuple]:
        """占位提示在控件里占据的范围；已经被删掉时返回 ``None``。"""
        ranges = self.text.tag_ranges("placeholder")
        if len(ranges) >= 2:
            return (str(ranges[0]), str(ranges[1]))
        return None

    def _drop_placeholder_at_edit_time(self, _event=None) -> None:
        """在 **Tk 处理这次输入之前** 把占位提示删掉。

        这是关键顺序：如果等事件处理完再删，Ctrl+V 的内容会先插进占位提示
        中间（实测插到了它前面），再删就得从用户内容里挑出提示，容易伤到
        用户的东西。绑 ``<KeyPress>`` 与 ``<<Paste>>`` 都是在**默认处理之前**
        触发的，所以这里删掉它就等于"占位提示不存在"。
        """
        if not self._placeholder_active:
            return
        span = self._placeholder_range()
        if span is None:
            self._placeholder_active = False
            return
        self.text.delete(span[0], span[1])
        self.text.tag_remove("placeholder", "1.0", tk.END)
        self.text.mark_set("insert", "1.0")
        self._placeholder_active = False
        self.text.edit_modified(False)

    def _clear_editor_status(self) -> None:
        """编辑区内容一变，就把"描述编辑区旧状态"的那句状态清掉。

        **修的是一个真 bug**：`clear_text()` 设了"编辑区已清空"，但之后
        用户打字、粘贴、读入文件，**没有任何一处把这句话撤掉**——于是编辑区
        里明明有 1500 多字，状态栏还写着"编辑区已清空"（用户实测报回来）。

        做法是把"编辑区状态"与"进程状态"分开：只有下面这几句是**关于编辑区
        当前内容**的，内容一变就过时了。而"正在合成…"/"生成失败"这类是
        **进程状态**，不能被打字清掉——那会把正在进行的反馈抹掉。
        """
        if self._status_text.startswith(self.EDITOR_STATUS_PREFIXES):
            # ⚠️ 不要清成空串：空串会让状态行 `pack_forget()`，状态区少一行、
            # 窗口跟着缩 30px——用户粘贴/打字时看到"状态栏闪一下、输入框跳一下"
            # （2026-10-17 报）。换成**同样一行**的短状态，高度不变。
            self.set_status(L("编辑区内容已更新", "Editor content updated"), "info")

    # （抓手拖动方案已按用户要求**整体移除**：那套东西做不到、还改坏了别的
    #   行为。现在的规则最简单——编辑区那一行 `weight=1`，窗口拉高就归它，
    #   下段各占自然高度、位置固定不动。）

    def _lock_editor_min_height(self) -> None:
        """把"编辑区初始高度"锁成那一行的最小高度。

        用户定稿："初始高度=最小高度"。`grid` 的 `minsize` 正是这个语义：
        窗口还能缩，但**那一行不会再矮于这个值**，输入框因此不会被压扁。

        只做一次；之后窗口高度变化都不再改它（上一版我每次窗口变化都改，
        结果把用户拉的尺寸锁死了）。
        """
        if self._closing or self._editor_initial_height:
            return
        height = self.editor_card.winfo_height()
        if height <= 1:
            # 首帧还没算完，再等一次
            self.root.after(80, self._lock_editor_min_height)
            return
        self._editor_initial_height = height
        self.root.rowconfigure(ROW_EDITOR, minsize=height)

    def _on_committed_edit_paste(self, _event=None) -> None:
        """粘贴/剪切/撤销**之后**再核对一次内容（有输入法、脚本粘贴这类路径
        不会走 ``<KeyPress>``）。"""
        if self._placeholder_active:
            span = self._placeholder_range()
            content = self.text.get("1.0", "end-1c")
            if span is None or content.strip() != placeholder_text().strip():
                # 内容变了：把残留的占位提示摘掉，只留用户的东西
                if span is not None:
                    self.text.delete(span[0], span[1])
                    self.text.tag_remove("placeholder", "1.0", tk.END)
                self._placeholder_active = False
                self.text.edit_modified(False)
        self._update_counts()
        # 内容变了 → 撤掉"编辑区已清空 / 已读入 X"这类旧状态
        self._clear_editor_status()
        # 内容变了 → 上一轮生成的那两个按钮**也必须消失**：
        # 它们指向的音频是按**旧文案**生成的，文案一改就不再对应
        # （用户实测："跑完一条后改动或清空编辑区，打开音频/所在文件夹
        # 没消失也点不动"）。
        self._hide_results_if_stale()

    def _hide_results_if_stale(self) -> None:
        """当前文案与"已生成的那份"不一致时，撤掉产物按钮。

        **判据是内容，不是"有没有编辑过"**：如果用户改了又改回原文案，
        产物仍然对得上，按钮就该留着。
        """
        if not self.result_paths:
            return
        if self.get_text() != self._generated_content:
            self._clear_results()

    def _lower_natural_height(self) -> int:
        """下段（那一排 + 操作区 + 状态栏 + 页脚）的自然高度。"""
        total = 0
        for row in (ROW_DIRS, ROW_ACTION, ROW_STATUS, ROW_FOOTER):
            for widget in self.root.grid_slaves(row=row):
                try:
                    total += widget.winfo_reqheight()
                except tk.TclError:
                    continue
                pady = widget.grid_info().get("pady") or (0, 0)
                try:
                    total += int(pady[1])
                except (TypeError, IndexError):
                    pass
        return total

    def _on_root_configure(self, event) -> None:
        """只有**根窗口自己**的 Configure 才重算坑位。

        ## 为什么必须判 `event.widget`

        Tk 的 bindtags 是 ``(控件名, 控件类, 所属顶层窗口名, "all")``。
        `root.bind(...)` 绑的是**顶层窗口名**（"."），而窗口里每个子控件的
        bindtags 都含 "." —— 所以子控件改尺寸也会进这个回调。

        `_fix_progress_slot_inner()` 会切换「生成语音 / 生成中…」的文字
        （两者宽度不同），再 `update_idletasks()` **同步**派发那个按钮的
        Configure。于是：重算 → 改文字 → 同步 Configure → 重算 → …
        实测递归到 995 层后 `RecursionError`，tkinter 在报告异常时又因
        栈已耗尽再抛一次，最终从 `mainloop()` 冒出来，用户看到的是
        "启动失败"对话框 + `GUI-of-Edge-TTS-crash.log`。

        修法有两层，这是第一层：**只认根窗口的尺寸变化**。
        """
        if event.widget is self.root:
            self._fix_progress_slot()
            self._fix_voice_width()

    def _fix_voice_width(self) -> None:
        """把语音选择框限制在上一版宽度的 2/3（约窗口宽度的 43%）。

        为什么不是写死像素：窗口和 DPI 都会变；按比例 + 可用宽度双重约束，
        窄窗口下自动让出空间给筛选框/计数，不会把右边的控件挤出去。
        """
        try:
            root_width = self.root.winfo_width()
            row_width = self.voice_row.winfo_width()
            if root_width <= 1:
                return
            if row_width <= 1:
                # 首帧还没布局：用窗口宽度减去两侧留白估算，避免先窄后宽
                row_width = max(
                    260,
                    root_width
                    - self.theme.px(SPACE_5) * 2
                    - self.theme.px(SPACE_3) * 2,
                )
            fixed = (
                self.voice_caption.winfo_reqwidth()
                + self.voice_filter.winfo_reqwidth()
                + self.voice_count.winfo_reqwidth()
                + self._gap_compact * 2
                + self._gap_filter
            )
            target = min(
                int(root_width * VOICE_BOX_RATIO),
                max(180, row_width - fixed),
            )
            char_width = max(1, self.theme.font(FONT_BODY_PT).measure("0"))
            chars = max(14, int(target / char_width))
            if int(self.voice_box.cget("width")) != chars:
                self.voice_box.configure(width=chars)
            self._sync_filter_height()
        except tk.TclError:
            return

    def _fix_progress_slot(self, force: bool = False) -> None:
        """钉住操作区两列的宽度，让三种状态下按钮坐标完全不动。

        * col 0 = "进度条 / 打开音频"的坑位
        * col 1 = 「取消」的常驻宽度（它隐藏时这一列也占着）

        算法（全部用**与显隐无关**的量）：

            cancel_need = 取消按钮的 reqwidth + 它的 padx
            col1        = cancel_need
            col0        = 操作区总宽 − cancel_need − 生成语音的 reqwidth

        ⚠️ 为什么必须由"**窗口宽度**"驱动，而不是操作区的 `<Configure>`：
        设 `minsize` 本身就会触发一次 `<Configure>`，用它驱动会自我反馈振荡
        （实测列宽 1106↔959 反复跳、进度条跟着抖）。改成只认窗口宽度、
        且宽度没变就直接返回，就不会回环。

        走过的其他弯路一并记下：
          * 用常量拼间距 → 漏掉「取消」的 padx，差 4px；
          * 先 `update_idletasks()` 再读 `grid_info()["padx"]` → 读回来是 0
            （重算布局后配置也变了），还是差 4px；
          * col0 的 `minsize` 不减掉 col1 的常驻宽度 → 两列之和超出容器，
            grid 只能压 col0，生成时进度条窄 4px。

        ⚠️ 第二道闸是**防重入**（:attr:`_fixing_slot`）：重算内部会
        `update_idletasks()`，那会同步派发事件；无论事件来自谁，同一次
        重算都不该嵌套执行第二次。第一道闸（`_on_root_configure` 过滤
        事件源）管"别人的 Configure"，这一道管"我自己的副作用"。
        """
        if self._closing or self._fixing_slot:
            return
        self._fixing_slot = True
        try:
            self._fix_progress_slot_inner(force)
        except Exception:  # noqa: BLE001
            # 这个方法在**窗口初始化早期**就会被 <Configure> 调到，那时容器
            # 尺寸可能还是 0，`update_idletasks()` 抛的异常不一定是 TclError。
            # 它只负责"算几个布局数字"，失败了等下一条 <Configure> 再来，
            # **不该把异常抛回 Tk 的事件循环**（那会打印一堆无从下手的堆栈）。
            return
        finally:
            self._fixing_slot = False

    def _fix_progress_slot_inner(self, force: bool) -> None:
        root_width = self.root.winfo_width()
        if not force and root_width == self._slot_root_width and self._progress_slot:
            return
        # 先读「取消」自己的间距（逻辑单位换成物理像素）
        cancel_extra = self._gap_compact
        # ⚠️ **先定住「生成语音」的宽度，再读它。**
        #
        # 它的文字在"生成语音"和"生成中…"之间切换，两者宽度不同
        # （实测 162 vs 158）。按钮锚在右边缘 → 变窄时**左边缘右移 4px**。
        # 我先前一直以为这是列宽问题，查了四轮才定位到是按钮自己变窄。
        #
        # 顺序很重要：锁宽度必须在**算 `_cancel_offset` 之前**。
        # 反过来的话，「取消」会按旧的（较窄的）宽度定位，也偏 4px。
        generate_need = 0
        try:
            # 量宽度时不要逐次绘制：否则语言切换/生成中会看到「生成语音」
            # 与「生成中…」来回闪。全部量完、定好宽度，最后只画一次。
            self.generate_button.set_text(L("生成语音", "Generate"), repaint=False)
            self.generate_button.update_idletasks()
            wide = self.generate_button.winfo_reqwidth()
            self.generate_button.set_text(L("生成中…", "Generating..."), repaint=False)
            self.generate_button.update_idletasks()
            wide = max(wide, self.generate_button.winfo_reqwidth())
            self.generate_button.set_text(
                L("生成中…", "Generating...") if self.generating
                else L("生成语音", "Generate"),
                repaint=False,
            )
            self.generate_button.freeze_width(wide)
            self.generate_button.update_idletasks()
            generate_need = self.generate_button.winfo_width() or wide
            self.generate_button._paint()  # noqa: SLF001 - 批量重绘收尾
        except Exception:  # noqa: BLE001 - 量宽度失败不该影响界面可用
            generate_need = 0

        try:
            self.root.update_idletasks()
            total = self.action_bar.winfo_width()
            if total <= 1:
                return  # 还没布局，等下一次
            cancel_need = self.cancel_button.winfo_reqwidth() + cancel_extra
            if not generate_need:
                generate_need = self.generate_button.winfo_width()
            #: 「取消」相对右边缘的偏移 = 生成按钮的宽度 + 它自己的间距
            self._cancel_offset = generate_need + cancel_extra
            # **第 0/1/2 列的宽度就是这一行的三块**：
            #   col0 = 进度条/打开音频，col1 = 取消，col2 = 生成语音。
            # 后两块只占位（真按钮是 `place` 的），这样 col0 不会把多出来的
            # 宽度吃掉——旧代码用 `total - cancel - generate - gap*2` 并给
            # col0 `weight=1`，结果 col0 被撑到 1111px，进度条和百分比一直
            # 钻到「取消」底下（实测百分比文字被按钮完全盖住）。
            col0 = max(120, total - cancel_need - generate_need)
        except tk.TclError:
            return

        # 操作区高度 = 按钮高度（`place` 的子控件撑不起父容器）
        try:
            self.action_bar.configure(height=max(40, self.generate_button.winfo_reqheight()))
        except tk.TclError:
            pass

        self._slot_root_width = root_width
        self._progress_slot = col0
        self.action_bar.columnconfigure(0, minsize=col0)
        self.action_bar.columnconfigure(1, minsize=cancel_need)
        self.action_bar.columnconfigure(2, minsize=generate_need)
        wrap = max(240, self.status_card.winfo_width() - self.theme.px(SPACE_3) * 2)
        for label in (self.status_label, self.counts_label, self.progress_detail):
            label.configure(wraplength=wrap)

    def _content_bottom(self) -> int:
        """最底一行的下沿（相对根窗口），**含页脚那一行自己的 pady**。

        只用来回答一个问题："内容现在是不是已经装不下了？"
        判据用 `grid_bbox`（它含 pady）而不是"窗口高度"——窗口高度是
        **结果**，装不下的时候它恰恰是错的那个数（2026-10-17 实测：
        窗口 792，页脚底边 849）。
        """
        bottom = 0
        try:
            bbox = self.root.grid_bbox(0, ROW_FOOTER)
            if bbox and bbox[3]:
                bottom = int(bbox[1] + bbox[3])
        except tk.TclError:
            pass
        for widget in self.root.grid_slaves():
            try:
                bottom = max(bottom, widget.winfo_y() + widget.winfo_height())
            except tk.TclError:
                continue
        return bottom

    def _remember_clean_height(self) -> None:
        """记下启动时的基准：窗口高度与下段自然高度。只记一次。

        ⚠️ 判据只看"有没有产物"，**不要看状态文字**。我第一版加了
        `if self.status_label.cget("text"): return`，结果启动时状态栏本来就有
        "正在获取语音列表…"，基准永远记不上（实测 clean_h 一直是 0，
        补偿从不生效、页脚被裁）。

        基准的语义是"**启动布局**"，本来就和当时的文案无关。

        ## 2026-10-17：基准必须"先让内容装得下"再记

        旧写法直接读 `winfo_height()`。在 175% DPI 下默认窗口 792 装不下
        内容（页脚底边 849），于是基准记成 `792 / 256` 这一对**自相矛盾**的
        数：公式认为"下段该占 256"，但 792 根本放不下。之后状态栏再长高时，
        `_settle_window_height` 只补 **增量**，那 57px 的先天缺口永远补不回来
        —— 用户看到的就是"状态栏该展开时展不开"。

        所以这里先把两个会变的东西定下来：
          1. 先跑一遍 `_fix_progress_slot(force=True)`：操作区的高度是显式设的
             （按钮是 `place`，不参与父容器计算），不先设就量不到 58px；
          2. 内容底边超出窗口时，按用户的高度规则**先加高窗口**，再记基准。
        """
        if self._closing or self._clean_window_height:
            return
        # 1) 让操作区/坑位先量准（重复调用是幂等的）
        self._fix_progress_slot(force=True)
        self.root.update_idletasks()
        height = self.root.winfo_height()
        if height <= 1:
            return
        # 2) 内容装不下就先长高——基准不能建立在一个装不下的窗口上
        overflow = self._content_bottom() - height
        if overflow > 0:
            with platform_win.suspend_redraw(self.root):
                self.root.geometry(
                    f"{self.root.winfo_width()}x{height + overflow}"
                    f"+{self.root.winfo_x()}+{self.root.winfo_y()}"
                )
                self.root.update_idletasks()
            height = self.root.winfo_height()
        self._clean_window_height = height
        self._clean_lower_height = self._lower_natural_height()
        self._last_lower_height = self._clean_lower_height

    def _schedule_settle(self) -> None:
        """请求一次窗口高度结算；**同一轮只排一次**。

        生成结束的路径是"隐藏进度条 → 显示打开音频/三行状态"，中间如果
        各结算一次，窗口会先缩后涨，输入框看起来跳了一下。把请求合并到
        一个 `after_idle` 里，等界面状态全部落定后只量一次。
        """
        if self._closing or self._settle_after_id is not None:
            return
        self._settle_after_id = self.root.after_idle(self._run_scheduled_settle)

    def _run_scheduled_settle(self) -> None:
        self._settle_after_id = None
        self._settle_window_height()

    def _settle_window_height(self) -> None:
        """让窗口高度跟着下段内容走，**输入框高度和用户拉过的窗口都不动**。

        公式（单一公式，双向跟随）：

            ``窗口高度 = 当前高度 + (下段现在需要的 − 上次结算时下段需要的)``

        ## 为什么用"当前高度"，不用"启动基准高度"

        用户会把窗口拉高、把输入框调到喜欢的大小。如果每次都用
        ``启动基准 + 增量``，那么他点一下「清空」——下段少了一行/一个按钮——
        窗口就会被拉回启动高度，**输入框也跟着缩回最低高度**。
        用户 2026-10-17 报的就是这个："点清空只想清文字，不想输入框缩回去。"

        用"当前高度 + 下段增量"就自然保留了用户拉出来的那部分高度：
        下段少 56px，窗口就少 56px，输入框高度不变。

        * 状态栏从一行变三行 → 下段 +90px → 窗口加高 90px，编辑区不动；
        * 状态清空、产物按钮收起 → 下段 −56px → 窗口回落 56px，编辑区不动。

        ⚠️ 不要在这里按"当前内容溢出量"补高度：内容收起时，grid 会先把
        空出来的高度给编辑区（`weight=1`），下一轮 after_idle 还没跑完时
        `_content_bottom()` 仍读到旧值——补一次就把窗口永久抬高 56px
        （实测 905→961→1017 逐轮变高）。溢出检查只在启动记基准时做一次。
        """
        if not self._clean_window_height or not self._last_lower_height or self._closing:
            return
        self.root.update_idletasks()
        lower = self._lower_natural_height()
        delta = lower - self._last_lower_height
        if delta == 0:
            return
        # 先记下"已结算到这个下段高度"，这样一次内容变化只结算一次；
        # 后面重复的 after_idle 调用不会再叠加同一个增量。
        self._last_lower_height = lower
        # 最大化/最小化时窗口高度由用户与系统控制，程序不要改。
        try:
            if self.root.state() != "normal":
                return
        except tk.TclError:
            pass
        current = self.root.winfo_height()
        want = max(current + delta, self.root.minsize()[1] or 0)
        if abs(want - current) < 2:
            return
        self._resizing = True
        try:
            with platform_win.suspend_redraw(self.root):
                self.root.geometry(
                    f"{self.root.winfo_width()}x{want}"
                    f"+{self.root.winfo_x()}+{self.root.winfo_y()}"
                )
                self.root.update_idletasks()
        finally:
            self._resizing = False

    def _place_cancel(self) -> None:
        """把「取消」摆在「生成语音」左边（两者都锚在右边缘）。

        这样它的位置只取决于"生成语音有多宽"，与 grid 的列分配无关——
        实测 grid 分配在"生成时多一个控件"的情况下会变，按钮会移 4px。
        """
        self.cancel_button.place(
            in_=self.action_bar, relx=1.0, rely=0.5, anchor="e",
            x=-self._cancel_offset,
        )

    def _show_result_buttons(self, visible: bool) -> None:
        """产物按钮的显隐。

        ⚠️ 用 `place`/`place_forget`，**不是** `grid`/`grid_remove`：
        这颗按钮住在"进度条 / 打开音频"的共用坑位里，用 `place` 是为了让它
        **不参与 grid 的尺寸计算**——否则它一出现就会改变列宽，把旁边两颗
        按钮挤动。显隐方式必须和布局方式配套，混用会直接报 TclError。
        """
        if visible:
            self.open_file_button.place(x=0, rely=0.5, anchor="w")
        else:
            self.open_file_button.place_forget()

    def _clear_results(self) -> None:
        """收起产物按钮并清掉结果状态。"""
        self.result_paths = []
        self._generated_content = ""
        self._show_result_buttons(False)
        self._schedule_settle()

    def get_text(self) -> str:
        if self._placeholder_active:
            return ""
        return self.text.get("1.0", tk.END).strip()

    def clear_text(self) -> None:
        self._set_placeholder()
        self._update_counts()
        # 清空 = 文案没了 → 上一轮的产物按钮也必须收起来（它指向旧文案的音频）
        self._clear_results()
        self.set_status(L("编辑区已清空", "Editor cleared"), "info")

    def _update_counts(self) -> None:
        """字数与时长的文案。

        用户同意"中英分开算"：**英文按词、中文按字**，时长各用自己的语速。
        算法在 `text_mod.describe_length` 里——**单位和语速都随语言变**，
        因为"一个单位该数什么"本身就不同（英文按字符数会虚高两三倍，
        中文按词数又数不出东西）。
        """
        content = self.get_text()
        pieces = (
            [text_mod.describe_length(content)]
            if content
            else [L("0 字", "0 characters")]
        )
        parts = text_mod.request_parts(content)
        if parts > 1:
            pieces.append(L(f"将分 {parts} 次请求", f"Will use {parts} requests"))
        self.counts_label.configure(text=" · ".join(pieces))
        self._update_tip()

    def _update_tip(self) -> None:
        """编辑区下面那行提示。

        **提示语长度是排版问题**：这里只放三条之内、点得出结果的短句，
        完整的说明在「?」那个窗口里（否则窄窗口下会被截断）。
        """
        if self._placeholder_active or not self.get_text():
            text = L(
                "Ctrl+Enter 生成 · Ctrl+O 读入文件 · Ctrl+H 全部提示",
                "Ctrl+Enter generate · Ctrl+O open file · Ctrl+H all tips",
            )
        elif self.generating:
            text = L(
                "生成中，可以点右边「取消」；已下载的部分会被丢弃",
                "Generating; use Cancel on the right. Downloaded parts are discarded.",
            )
        else:
            text = L(
                "Ctrl+Enter 生成 · Ctrl+S 另存文本 · Ctrl+L 清空",
                "Ctrl+Enter generate · Ctrl+S save text · Ctrl+L clear",
            )
            if self.catalog_error:
                text = L(
                    "语音列表没加载成功，用的是内置语音 · 按 Ctrl+H 看怎么办",
                    "Voice list failed to load; using built-in voices · Ctrl+H for help",
                )
        self.editor_tip.configure(text=text)

    def open_text_file(self) -> None:
        path = filedialog.askopenfilename(
            parent=self.root,
            title=L("打开文本文件", "Open text file"),
            filetypes=[
                (L("文本文件", "Text files"), "*.txt *.md *.srt"),
                (L("所有文件", "All files"), "*.*"),
            ],
        )
        if not path:
            return
        self.load_text_file(path)

    def set_editor_content(self, content: str) -> None:
        """把内容放进编辑区（读入文件、命令行载入都走这里）。

        **占位提示一定先摘干净**：不然用户内容会和它混在一起——那正是
        这一版修掉的那个缺陷。
        """
        self._placeholder_active = False
        self.text.tag_remove("placeholder", "1.0", tk.END)
        self.text.delete("1.0", tk.END)
        if content:
            self.text.insert("1.0", content)
        self.text.mark_set("insert", "end-1c")
        self.text.edit_modified(False)
        self._update_counts()

    def load_text_file(self, path: str) -> bool:
        """把文件内容读进编辑区。**编不出来就说清楚为什么**，不要安静地什么都不做。

        UTF-8 读不了时退到 GBK：中文 Windows 上另存为的 .txt 常常是 GBK，
        而"打不开"对用户是零信息。
        """
        try:
            data = Path(path).read_text(encoding="utf-8")
        except UnicodeDecodeError:
            try:
                data = Path(path).read_text(encoding="gbk")
            except (OSError, UnicodeDecodeError) as exc:
                self.set_status(
                    L(f"读不出这个文件：{exc}", f"Could not read this file: {exc}"),
                    "error",
                )
                self.show_error(
                    L("无法读取", "Cannot read"),
                    L(
                        f"这个文件读不出来：\n{path}\n{exc}",
                        f"Could not read this file:\n{path}\n{exc}",
                    ),
                )
                return False
        except OSError as exc:
            self.set_status(
                L(f"读不出这个文件：{exc}", f"Could not read this file: {exc}"),
                "error",
            )
            self.show_error(
                L("无法读取", "Cannot read"),
                L(
                    f"这个文件读不出来：\n{path}\n{exc}",
                    f"Could not read this file:\n{path}\n{exc}",
                ),
            )
            return False

        self.set_editor_content(data)
        self.set_status(
            L(
                f"已读入 {Path(path).name}（{len(data):,} 字）",
                f"Loaded {Path(path).name} ({len(data):,} characters)",
            ),
            "success",
        )
        return True

    def save_text_file(self) -> None:
        path = filedialog.asksaveasfilename(
            parent=self.root,
            title=L("另存为文本文件", "Save text as"),
            defaultextension=".txt",
            filetypes=[(L("文本文件", "Text files"), "*.txt"), (L("所有文件", "All files"), "*.*")],
        )
        if not path:
            return
        try:
            Path(path).write_text(self.get_text(), encoding="utf-8")
        except OSError as exc:
            self.show_error(
                L("保存失败", "Save failed"),
                L(f"写不进这个位置：\n{path}\n{exc}", f"Could not write here:\n{path}\n{exc}"),
            )
            return
        self.set_status(L(f"已保存 {path}", f"Saved {path}"), "success")

    def _set_window_icon(self, window: tk.Toplevel, tk_fallback: bool = True) -> None:
        """给每个 Toplevel 设置**主题色标题栏图标 + 主图标任务栏图标**。

        标题栏用当前主题的 light/dark ICO；任务栏/Alt-Tab 始终用主
        `Edge-TTS.ico`（用户 2026-10-18 定稿）。

        先用 Win32 `WM_SETICON` 按当前 DPI 的 28/56 等真实尺寸取 ICO 帧；
        Tk 的 `iconbitmap` 只取一个帧，175% 下会被拉伸得发糊。

        `tk_fallback=False` 用于**切主题**：`iconbitmap` 会重置 DWM 标题栏，
        让刚设好的深色标题栏又变回浅色，所以切换时只走 Win32。
        """
        main_icon = platform_win.resource_path("images/Edge-TTS.ico")
        theme_name = "dark" if self.theme.dark else "light"
        theme_icon = platform_win.resource_path(f"images/Edge-TTS_{theme_name}.ico")
        if not os.path.exists(theme_icon):
            theme_icon = main_icon
        if not os.path.exists(theme_icon):
            return
        if tk_fallback:
            try:
                window.iconbitmap(theme_icon)
            except tk.TclError:
                pass
        handles = platform_win.set_window_icon(
            platform_win.window_id_of(window), theme_icon, main_icon
        )
        if handles:
            window._icon_handles = handles  # type: ignore[attr-defined]

    def _dialog_warning_icon(self, parent) -> tk.Label:
        """自绘警告三角：抗锯齿位图，黑色线条，面积约 4 个正文字符。

        Tk Canvas 不做抗锯齿（旧版三角有锯齿），所以这里用工程里的
        `raster` 覆盖率栅格化：先画实心外三角，再用透明内三角挖空；
        感叹号由抗锯齿线段 + 圆头 + 圆点组成，整组按三角形重心垂直居中。
        """
        font = self.theme.font(FONT_BODY_PT)
        char_w = max(1, font.measure("0"))
        line_h = max(1, font.metrics("linespace"))
        # 用户 2026-10-18：再放大到上一版的两倍。
        side = max(80, int(round(2 * (4 * char_w * line_h) ** 0.5)))
        palette = self.theme.palette
        colour = palette.text

        margin = max(4.0, side * 0.08)
        stroke = max(2.0, side * 0.06)
        cx = side / 2.0
        apex = (cx, margin)
        left = (margin, side - margin)
        right = (side - margin, side - margin)
        centroid_y = (apex[1] + left[1] + right[1]) / 3.0
        scale = max(0.55, 1.0 - (2.4 * stroke) / max(1.0, side - 2.0 * margin))
        inner = [
            (cx + (x - cx) * scale, centroid_y + (y - centroid_y) * scale)
            for x, y in (apex, left, right)
        ]
        inner_points = tuple(value for point in inner for value in point)

        length = side * 0.20
        gap = side * 0.055
        dot_radius = side * 0.045
        total = length + gap + 2.0 * dot_radius
        line_top = centroid_y - total / 2.0
        line_bottom = line_top + length
        dot_y = line_bottom + gap + dot_radius

        primitives = [
            ("polygon", tuple(apex + left + right), colour),
            ("polygon", inner_points, raster.CLEAR),
            ("line", cx, line_top, cx, line_bottom, stroke, colour),
            # 线段两端加圆头，避免方头切口
            (
                "ellipse",
                cx - stroke / 2.0, line_top - stroke / 2.0,
                cx + stroke / 2.0, line_top + stroke / 2.0,
                0, colour, None,
            ),
            (
                "ellipse",
                cx - stroke / 2.0, line_bottom - stroke / 2.0,
                cx + stroke / 2.0, line_bottom + stroke / 2.0,
                0, colour, None,
            ),
            (
                "ellipse",
                cx - dot_radius, dot_y - dot_radius,
                cx + dot_radius, dot_y + dot_radius,
                0, colour, None,
            ),
        ]
        png = raster.rasterise(primitives, side, side)
        photo = tk.PhotoImage(master=parent, data=png)
        label = tk.Label(
            parent,
            image=photo,
            background=palette.background,
            borderwidth=0,
            highlightthickness=0,
        )
        label.image = photo  # type: ignore[attr-defined] - 防止 PhotoImage 被回收
        return label

    def _wrap_dialog_text(self, text: str, max_width: int) -> str:
        """CJK 友好的断行：中文按字、英文/数字整词、句末标点不落单。

        Tk Label 的 wraplength 按空白断行，遇到 "HTTPS" + 一长串中文时
        会把 "HTTPS" 单独扔一行、句号又另起一行。这里自己按像素量宽度。
        """
        font = self.theme.font(FONT_BODY_PT)
        lines: list = []
        paragraphs = [part.strip() for part in text.splitlines() if part.strip()]
        # 错误信息偶尔是 "HTTPS\n证书校验失败…"：极短的首行不单独占一行。
        merged: list = []
        for paragraph in paragraphs:
            if merged and len(merged[-1]) <= 8:
                merged[-1] = f"{merged[-1]} {paragraph}"
            else:
                merged.append(paragraph)
        for paragraph in merged:
            line = ""
            pending_space = False
            break_at = -1
            for token in _DIALOG_TOKEN.findall(paragraph):
                if token.isspace():
                    if line:
                        pending_space = True
                        break_at = len(line)
                    continue
                if token in _DIALOG_CLOSING and line:
                    # 标点跟着上一行，绝不单独成行。
                    line += token
                    pending_space = False
                    break_at = len(line)
                    continue
                separator = " " if pending_space and line else ""
                candidate = line + separator + token
                if not line or font.measure(candidate) <= max_width:
                    line = candidate
                else:
                    # 优先在最近的逗号/句号/空格后断，不要把中文词或
                    # "HTTPS" 从中间劈开（用户 2026-10-18 报的排版）。
                    moved = False
                    if break_at > 0:
                        head = line[:break_at].rstrip()
                        tail = line[break_at:].strip()
                        if tail and font.measure(head) >= max_width * 0.30:
                            lines.append(head)
                            line = tail + (" " if pending_space else "") + token
                            if font.measure(line) > max_width:
                                lines.append(line.rstrip())
                                line = token
                            pending_space = False
                            break_at = -1
                            moved = True
                    if not moved:
                        lines.append(line.rstrip())
                        line = token
                pending_space = False
            if line:
                lines.append(line.rstrip())
        return "\n".join(lines)

    def _show_dialog(
        self,
        title: str,
        message: str,
        *,
        kind: str = "warning",
        ask: bool = False,
        yes_text: Optional[str] = None,
    ) -> bool:
        """自绘模态提示窗，替代原生 messagebox。

        原生 Windows MessageBox 有三样东西改不了：按钮区的浅灰分隔带、
        系统感叹号图标、按钮颜色。这里用 Toplevel + FlatButton 自己画：
        没有分隔带，正文/按钮同一底色，确定键是强调蓝，标题图标是程序图标。
        """
        palette = self.theme.palette
        window = tk.Toplevel(self.root)
        window.withdraw()
        window.title(title)
        window.configure(background=palette.background)
        window.transient(self.root)
        window.resizable(False, False)
        self._set_window_icon(window)

        line_gap = self.theme.font(FONT_BODY_PT).metrics("linespace")
        body = tk.Frame(window, background=palette.background)
        # 左右硬边距：正文的 wrap 宽度也小于可用宽度，文字不会贴边。
        body.pack(
            fill=tk.BOTH,
            expand=True,
            padx=SPACE_5 + SPACE_4,
            pady=(SPACE_5 + SPACE_4, SPACE_5),
        )
        # 需求：正文之间不要空行；去掉连续空行，保留单换行。
        clean = "\n".join(line for line in message.splitlines() if line.strip())
        icon = self._dialog_warning_icon(body)
        icon.pack(anchor=tk.CENTER, pady=(0, line_gap))
        label = tk.Label(
            body,
            text=self._wrap_dialog_text(clean, self.theme.px(300)),
            anchor=tk.CENTER,
            justify=tk.CENTER,
            wraplength=0,
            background=palette.background,
            foreground=palette.text,
            font=self.theme.font(FONT_BODY_PT),
        )
        label.pack(fill="x")

        buttons = tk.Frame(body, background=palette.background)
        # 正文与按钮之间空两行（用户 2026-10-18："再加一条空行"）。
        buttons.pack(fill="x", pady=(line_gap * 2, 0))
        result = {"value": False}

        def finish(value: bool) -> None:
            result["value"] = value
            try:
                window.grab_release()
            except tk.TclError:
                pass
            window.destroy()

        ok = FlatButton(
            buttons,
            yes_text or L("确定", "OK"),
            lambda: finish(True),
            theme=self.theme,
            kind="accent",
            pad_x=SPACE_4,
            pad_y=SPACE_2,
        )
        ok.pack(side=tk.RIGHT)
        if ask:
            cancel = FlatButton(
                buttons,
                L("取消", "Cancel"),
                lambda: finish(False),
                theme=self.theme,
                kind="neutral",
                pad_x=SPACE_4,
                pad_y=SPACE_2,
            )
            cancel.pack(side=tk.RIGHT, padx=(0, self._gap_compact))
        window.bind("<Return>", lambda _e: finish(True))
        window.bind("<Escape>", lambda _e: finish(False))
        window.protocol("WM_DELETE_WINDOW", lambda: finish(False))
        window.update_idletasks()
        self._place_toplevel(window, 360, fit=True, fixed_width=True)
        self._apply_window_chrome()
        self._reveal_popup(window)
        window.grab_set()
        window.focus_set()
        ok.focus_set()
        self.root.wait_window(window)
        return bool(result["value"])

    def show_warning(self, title: str, message: str) -> bool:
        return self._show_dialog(title, message, kind="warning")

    def show_error(self, title: str, message: str) -> bool:
        return self._show_dialog(title, message, kind="error")

    def ask_yes_no(self, title: str, message: str) -> bool:
        return self._show_dialog(title, message, kind="warning", ask=True)

    def _reveal_popup(self, window: tk.Toplevel) -> None:
        """把已完成布局的弹窗一次性显示出来。

        弹窗显示也是一次“窗口状态变更”：先锁住这个窗口，再 deiconify +
        结算布局，最后解锁重画。用户只会看到最终内容，不会看到空白/黑条。
        """
        with platform_win.suspend_redraw(window):
            window.deiconify()
            window.update_idletasks()

    def _place_toplevel(
        self,
        window: tk.Toplevel,
        width: int,
        height: int = 0,
        fit: bool = False,
        fixed_width: bool = False,
        exact: bool = False,
    ) -> None:
        """把子窗口摆在主窗口中间，并夹到屏幕内。

        **不要用 ``.geometry("600x600")`` 了事**：那样会开在屏幕左上角
        （实测提示窗口开在 0,0），用户会以为程序跳出去了一扇不知哪来的窗。

        ``fit=True`` 时**高度按内容算**，不吃 ``height``——设置窗口就吃过这个
        亏：写死 460 逻辑像素，而内容只占一半，下面两百多像素全是留白。
        ``fixed_width=True`` 用于自绘提示窗：高度按内容，但左右要按指定宽度
        撑开（否则 Tk 只按文字自然宽度开窗，显得很窄）。
        """
        self._set_window_icon(window)
        self.root.update_idletasks()
        window.update_idletasks()
        if exact:
            width_px = int(width)
            height_px = int(height)
        elif fit:
            # **高度交给 Tk**：只给宽度和位置，末尾不写高度，Tk 就按内容的
            # 自然尺寸定高。实测写死高度会让设置窗口只分到内容所需的一半，
            # 下面一半全是留白（用户报的"高度过剩太多"就是这个）。
            if fixed_width:
                width_px = max(self.theme.px(width), window.winfo_reqwidth())
            else:
                # 不能拿 theme.px(width) 定位：设置窗口实际只按内容取 781，
                # 却按 1085 算中心，于是默认偏左（用户截图）。
                width_px = max(
                    window.winfo_reqwidth(), int(window.minsize()[0])
                )
            height_px = window.winfo_reqheight()
        else:
            width_px = self.theme.px(width)
            height_px = self.theme.px(height)
        main_x = self.root.winfo_rootx()
        main_y = self.root.winfo_rooty()
        main_w = self.root.winfo_width()
        main_h = self.root.winfo_height()
        # `wm geometry` 的 x/y 是外框位置，`winfo_rootx/y` 是客户区位置；
        # 两者差一圈标题栏/边框。不扣掉这圈，设置窗口会往右下偏。
        frame_offset_x = max(0, main_x - self.root.winfo_x())
        frame_offset_y = max(0, main_y - self.root.winfo_y())
        screen_w = window.winfo_screenwidth()
        screen_h = window.winfo_screenheight()
        # 横向、纵向都以主窗体中心为准（用户 2026-10-18 定稿：设置/提示
        # 都要居中；旧代码纵向用了 1/3，所以设置窗口总在左下）。
        # 子窗口比主窗体高时也照样以主窗体中心对齐，超出屏幕的部分再由
        # 下面的夹取处理。
        x = main_x + (main_w - width_px) // 2
        y = main_y + (main_h - height_px) // 2
        x -= frame_offset_x
        y -= frame_offset_y
        x = max(0, min(x, screen_w - width_px - frame_offset_x))
        max_y = screen_h - height_px - frame_offset_y - self.theme.px(48)
        if max_y < 0:
            max_y = max(0, screen_h - height_px - frame_offset_y)
        y = max(0, min(y, max_y))
        # exact / fixed_width / 普通尺寸都显式写 width x height；fit 的高度
        # 已经由 reqheight 得到。这样窗口只会以最终大小出现一次。
        window.geometry(f"{width_px}x{height_px}+{x}+{y}")
        # 记下"我们主动要求的尺寸"：审计工具靠它判断"有没有写死一个偏大的
        # 高度"。窗口被 `withdraw()` 时读不到实际尺寸，而审计**不允许开窗**
        # （会打断用户），所以需要一个不依赖可见性的判据来源。
        window.requested_geometry = (  # type: ignore[attr-defined]
            (width_px, height_px) if (not fit or fixed_width) else None
        )

    # ------------------------------------------------------------------ 提示

    def show_help(self) -> None:
        if self._help_window is not None and self._help_window.winfo_exists():
            self._help_window.lift()
            self._help_window.focus_set()
            return
        palette = self.theme.palette
        window = tk.Toplevel(self.root)
        window.withdraw()
        self._help_window = window
        window.title(help_title())
        window.configure(background=palette.background)
        window.transient(self.root)
        window.minsize(460, 420)
        # 尺寸与位置都由 _place_toplevel 定，免得开在屏幕角落。
        self._place_toplevel(window, 620, 600)
        # 面板只有一种底色：不再套一层"比窗口亮一档"的卡片
        frame = tk.Frame(window, borderwidth=0, highlightthickness=0, background=palette.background)
        frame.pack(fill=tk.BOTH, expand=True, padx=SPACE_4, pady=SPACE_4)
        frame.rowconfigure(1, weight=1)
        frame.columnconfigure(0, weight=1)

        heading = tk.Label(
            frame,
            text=help_title(),
            anchor="w",
            background=palette.background,
            foreground=palette.text,
            font=self.theme.font(FONT_TITLE_PT, bold=True),
        )
        heading.grid(row=0, column=0, sticky="ew", padx=SPACE_4, pady=(SPACE_4, SPACE_2))

        # 正文字号比主界面正文大 1pt：这是一篇要读的文字，不是扫一眼就走的栏目。
        # 不给更高的字号是因为**提示窗口本身够宽**，字号再大只会让行更长、
        # 阅读反而吃力（用户实测后定的这一档）。
        help_font = self.theme.font(FONT_HELP_PT)
        line_pad = max(2, self.theme.px(3))
        body = tk.Text(
            frame,
            wrap="word",
            borderwidth=0,
            highlightthickness=0,
            spacing1=line_pad,
            spacing3=line_pad,
        )
        body.grid(row=1, column=0, sticky="nsew", padx=SPACE_4)
        body.insert("1.0", help_text())
        body.configure(
            background=palette.background,
            foreground=palette.text,
            font=help_font,
            selectbackground=palette.selection,
            selectforeground=palette.text,
            padx=0,
            pady=0,
        )
        body.configure(state="disabled")

        scroll = FlatScrollbar(frame, command=body.yview, theme=self.theme)
        scroll.grid(row=1, column=1, sticky="ns", padx=(0, SPACE_2))
        body.configure(yscrollcommand=scroll.set)

        footer = tk.Frame(frame, background=palette.background)
        footer.grid(row=2, column=0, columnspan=2, sticky="e", padx=SPACE_4, pady=SPACE_3)
        # 「知道了」是**中性按钮**：这一屏上真正的主按钮是主窗口的「生成语音」，
        # 按规范强调色只给"推荐的那一个动作"。
        close = FlatButton(
            footer, L("知道了", "Got it"), window.destroy, theme=self.theme, kind="neutral"
        )
        close.pack()
        window.bind("<Escape>", lambda _e: window.destroy())
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        window.update_idletasks()
        self._apply_window_chrome()
        self._reveal_popup(window)
        window.focus_set()

    # ------------------------------------------------------------------ 设置窗口

    def show_settings(self) -> None:
        """设置窗口。

        写进去的每一项**立即生效并立即落盘**——没有"确定/取消"这一对按钮。
        理由是这里的每一项都是可逆的显示偏好，加一个"确定"只会让人以为
        "点了确定才生效"，而实际上改主题这种事当场就该看见。
        """
        if self._settings_window is not None and self._settings_window.winfo_exists():
            self._settings_window.lift()
            self._settings_window.focus_set()
            return

        palette = self.theme.palette
        window = tk.Toplevel(self.root)
        # 先藏起来，等内容/位置都算好再显示。
        window.withdraw()
        self._settings_window = window
        window.title(L("设置", "Settings"))
        window.configure(background=palette.background)
        window.transient(self.root)
        window.resizable(False, False)
        # 高度按内容算：写死高度会让下面两百多像素全是留白（用户实测报回来）
        window.minsize(520, 0)

        # 面板只有一种底色：不再套一层"比窗口亮一档"的卡片
        card = tk.Frame(window, borderwidth=0, highlightthickness=0, background=palette.background)
        card.pack(fill=tk.BOTH, expand=True, padx=SPACE_4, pady=SPACE_4)
        card.columnconfigure(1, weight=1)

        def caption(row: int, text_value: str) -> tk.Label:
            label = tk.Label(
                card,
                text=text_value,
                anchor="w",
                background=palette.background,
                foreground=palette.text,
                font=self.theme.font(FONT_BODY_PT),
            )
            label.grid(
                row=row, column=0, sticky="w",
                padx=(SPACE_3, self._gap_compact), pady=(SETTINGS_ROW_GAP, 0),
            )
            return label

        def hint(row: int, text_value: str) -> tk.Label:
            label = tk.Label(
                card,
                text=text_value,
                anchor="w",
                justify="left",
                background=palette.background,
                foreground=palette.text_secondary,
                font=self.theme.font(FONT_SMALL_PT),
            )
            label.grid(row=row, column=1, sticky="w", padx=(0, SPACE_3))
            return label

        # 主题**不在这里**：它在主界面标题栏那三颗图标按钮上（用户定稿）。
        # 同一个开关出现在两个地方，迟早会出现"两边不一致"。

        # 设置窗口的**行距**（用户 2026-10-17 定稿）：
        #   网络代理（标题 + 输入框）
        #   灰色说明
        #   配置文件按钮（紧贴说明，**不空行**）
        #   路径说明（紧贴按钮，只保留路径）
        #   ← 空一行
        #   启动时显示使用提示（左对齐）
        #   ← 空一行
        #   关闭（右对齐）
        #
        # "空一行" = 一整个正文行高（`line_gap`），不是 `group_pad` 那种
        # 两行高的类间距，也不是 0。行内紧贴用 `SPACE_1`（4）。
        line_gap = self.theme.font(FONT_BODY_PT).metrics("linespace")

        # ---- 第①类：网络代理 ----
        # ⚠️ "标题"和"输入框"**必须在同一行里垂直居中**，而这一点会被
        # `pady` 破坏：第一版把 `pady=(group_pad, 0)` 加在**输入框**上，
        # 于是这一行被撑高，标题被留在行顶、输入框在行中——
        # 两者中心差了约 30px（用户实测看出来了："要与标题水平居中对齐"）。
        # 现在改成：把类间距给**行**（`card.rowconfigure`），
        # 行内两个控件都从同一个 y 开始，`sticky="ew"` 让它们各自在行内居中。
        self._settings_proxy_caption = caption(0, L("网络代理", "Proxy"))        # 字号用 `FONT_BODY_PT`（与标题同号）——"要能容纳和标题一样字号的内容"。
        # 原来用 `FONT_SMALL_PT`，框比标题矮、内容也小一号。
        self._proxy_var = tk.StringVar(value=self.settings.proxy)
        proxy_entry = tk.Entry(
            card,
            width=32,
            borderwidth=0,
            highlightthickness=1,
            background=palette.surface,
            foreground=palette.text,
            insertbackground=palette.text,
            highlightbackground=palette.border,
            highlightcolor=palette.accent,
            font=self.theme.font(FONT_BODY_PT),
            textvariable=self._proxy_var,
        )
        # ⚠️ **不要加 `ipady`**：用户先要"比标题略高"，看到实际效果后改成
        # "和标题一致就可以了"。同号字体下 Entry 的自然高度本来就等于标题
        # 的行高，加内边距反而把它撑高。这里保持零内边距。
        proxy_entry.grid(row=0, column=1, sticky="ew", padx=(0, SPACE_3))
        # 关键：以前只在 FocusOut/Return 时保存代理。用户输入后直接点窗口 ×
        # 时 FocusOut 不一定触发，代理从未写进 settings（实测配置里 proxy 仍为空）。
        # 现在用 StringVar 实时同步，失焦只是强制保存/立刻重拉列表。
        self._proxy_var.trace_add("write", self._on_proxy_text_changed)
        proxy_entry.bind("<FocusOut>", lambda _e: self._on_settings_proxy(proxy_entry.get()))
        proxy_entry.bind("<Return>", lambda _e: self._on_settings_proxy(proxy_entry.get()))
        # ⚠️ 行号必须比 caption 大：第一版这里写的是 `hint(1, …)` 而 caption 在
        # row 2，于是说明文字跑到了标题**上面**（grid 行号乱序）。
        self._settings_proxy_hint = hint(1, L(
            "留空表示使用系统代理。格式如 http://127.0.0.1:7897",
            "Blank = system proxy. Example: http://127.0.0.1:7897",
        ))

        # ---- 第②类：配置文件 ----
        # 按钮直接放在网络代理的灰色说明下一行（`SPACE_1` 紧贴，不空行）；
        # 路径说明在按钮下方，**只显示路径**（用户 2026-10-17：删掉"配置文件："）。
        self._settings_config_button = open_config = FlatButton(
            card,
            # 名字太长（用户定稿："整个按钮名字太长了，换成配置文件"）。
            # 它的作用就是"打开配置文件所在目录"，靠"配置文件"这个词
            # 已经能定位，不需要把动作也写进按钮名。
            L("配置文件", "Config file"),
            lambda: platform_win.reveal_in_explorer(str(config_path()), select=True),
            theme=self.theme,
            kind="ghost",
            pad_x=SPACE_4,
            pad_y=SPACE_2,
        )
        # 按钮放在网络代理说明下一行；用户连续两次要求"再多一点"：
        # 从紧贴的 SPACE_1 调到整行行高（line_gap），形成明确的分隔。
        open_config.grid(
            row=2, column=0, columnspan=2, sticky="w", padx=SPACE_3,
            pady=(line_gap, 0),
        )
        path_label = tk.Label(
            card,
            text=str(config_path()),
            anchor="w",
            background=palette.background,
            foreground=palette.text_secondary,
            font=self.theme.font(FONT_SMALL_PT),
        )
        path_label.grid(
            row=3, column=0, columnspan=2, sticky="w", padx=SPACE_3,
            pady=(SPACE_1, 0),
        )

        # ---- 第③类：启动提示（最下面，和上面的内容左对齐）----
        # **自绘开关**，不用 tk.Checkbutton —— 原生勾选框的方块与对勾由系统
        # 绘制，深色下要么看不见、要么是个浅色块。开关的"开/关"由滑块位置
        # 表达，比一个要看仔细的小方框清楚。
        hint_row = tk.Frame(card, background=palette.background)
        hint_row.grid(
            row=4, column=0, columnspan=2, sticky="w", padx=SPACE_3,
            pady=(line_gap, 0),
        )
        self._hints_switch = ToggleSwitch(
            hint_row,
            value=self.settings.show_hints,
            command=self._on_settings_hints,
            theme=self.theme,
        )
        self._hints_switch.pack(side=tk.LEFT)
        self._settings_hints_label = hint_label = tk.Label(
            hint_row,
            text=L("启动时显示使用提示", "Show help on startup"),
            anchor="w",
            background=palette.background,
            foreground=palette.text,
            font=self.theme.font(FONT_BODY_PT),
        )
        hint_label.pack(side=tk.LEFT, padx=(self._gap_compact, 0))

        # ---- 第④类：界面语言（中文 / English，语言名不翻译）----
        language_row = tk.Frame(card, background=palette.background)
        language_row.grid(
            row=5, column=0, columnspan=2, sticky="w", padx=SPACE_3,
            pady=(line_gap, 0),
        )
        self._settings_language_caption = language_caption = tk.Label(
            language_row,
            text=L("界面语言", "Language"),
            anchor="w",
            background=palette.background,
            foreground=palette.text,
            font=self.theme.font(FONT_BODY_PT),
        )
        language_caption.pack(side=tk.LEFT)
        buttons = tk.Frame(language_row, background=palette.background)
        buttons.pack(side=tk.LEFT, padx=(self._gap_compact, 0))
        active = self.settings.language or current_preference()
        self._settings_language_buttons = {}
        for value in CHOICES:
            button = FlatButton(
                buttons,
                DISPLAY_NAMES[value],
                lambda selected=value: self._choose_language(selected),
                theme=self.theme,
                kind="accent" if value == active else "neutral",
                pad_x=SPACE_4,
                pad_y=SPACE_2,
            )
            button.pack(side=tk.LEFT, padx=(0 if value == CHOICES[0] else self._gap_compact, 0))
            self._settings_language_buttons[value] = button

        # ---- 关闭（最下面，右对齐）----
        # 与语言行之间**隔一行**；底部留 `SPACE_3` 的窗口内边距。
        self._settings_close_button = close = FlatButton(
            card, L("关闭", "Close"), window.destroy, theme=self.theme, kind="accent",
            pad_x=SPACE_4, pad_y=SPACE_2,
        )
        close.grid(
            row=6, column=0, columnspan=2, sticky="e", padx=SPACE_3,
            pady=(line_gap, SPACE_3),
        )

        window.bind("<Escape>", lambda _e: window.destroy())
        window.protocol("WM_DELETE_WINDOW", window.destroy)
        window.update_idletasks()
        # **固定设置窗口尺寸**：以中文内容量为基准（英文提示已经缩短到同样
        # 宽度）。之后切语言不再改宽/改高，也就不会有任何缩放黑条。
        fixed_w = window.winfo_reqwidth()
        fixed_h = window.winfo_reqheight()
        self._settings_fixed_size = (fixed_w, fixed_h)
        window.minsize(fixed_w, fixed_h)
        window.maxsize(fixed_w, fixed_h)
        self._place_toplevel(window, fixed_w, fixed_h, exact=True)
        window.update_idletasks()
        self._apply_window_chrome()
        self._reveal_popup(window)
        window.focus_set()


    def _on_proxy_text_changed(self, *_args) -> None:
        """代理输入实时同步；保存/重拉列表做防抖，避免每敲一键都写盘。"""
        if self._closing:
            return
        value = self._proxy_var.get().strip()
        if value == self.settings.proxy:
            return
        self.settings.proxy = value
        if self._proxy_save_id is not None:
            try:
                self.root.after_cancel(self._proxy_save_id)
            except tk.TclError:
                pass
        self._proxy_save_id = self.root.after(250, self._flush_proxy_save)
        if self._proxy_reload_id is not None:
            try:
                self.root.after_cancel(self._proxy_reload_id)
            except tk.TclError:
                pass
        self._proxy_reload_id = self.root.after(700, self._reload_voices_for_proxy)

    def _flush_proxy_save(self) -> None:
        self._proxy_save_id = None
        if not self._closing:
            self._save_settings()

    def _reload_voices_for_proxy(self) -> None:
        if self._proxy_reload_id is not None:
            try:
                self.root.after_cancel(self._proxy_reload_id)
            except tk.TclError:
                pass
            self._proxy_reload_id = None
        if self._closing:
            return
        self._start_voice_fetch()

    def _maybe_reload_pending_voices(self) -> None:
        if self._voice_reload_pending and not self._closing:
            self._start_voice_fetch()

    def _on_settings_proxy(self, value: str) -> None:
        value = value.strip()
        changed = value != self.settings.proxy
        if changed:
            self.settings.proxy = value
        self._save_settings()
        if changed:
            self._reload_voices_for_proxy()

    def _on_settings_hints(self, value: bool) -> None:
        was_visible = bool(self.help_strip.winfo_manager())
        self.settings.show_hints = bool(value)
        self._save_settings()
        self._update_hint_strip()
        # 运行中重新打开提示条时，顶部会新增一段固定高度；窗口必须同步
        # 长高，否则下半段（状态栏、页脚版本号）会被挤出客户区。
        # 这里只按“内容底边超出窗口”补差，不重算布局，也不动编辑区高度。
        if self.settings.show_hints and not was_visible:
            # 提示条刚 grid 进去时，下半段还没完成 reflow；立即量 overflow
            # 只能量到旧底边（实测只长 10px，页脚仍被裁）。等一次 idle，
            # 布局落定后再按“内容底边超出窗口”补差。
            self.root.after(30, self._grow_window_to_content)

    def _grow_window_to_content(self) -> None:
        """提示条新增后，按它实际占用的高度把窗口长高一次。"""
        if self._closing or not self.settings.show_hints:
            return
        if not self.help_strip.winfo_manager():
            return
        try:
            if self.root.state() != "normal":
                return
            pady = self.help_strip.grid_info().get("pady") or (0, 0)
            top_pad = int(pady[0]) if isinstance(pady, (tuple, list)) else int(pady)
        except (tk.TclError, TypeError, ValueError):
            return
        self.root.update()
        if self._content_bottom() <= self.root.winfo_height():
            return
        extra = self.help_strip.winfo_reqheight() + top_pad
        if extra <= 0:
            return
        self._resizing = True
        try:
            # 主窗口长高也必须冻结：否则窗口先变大、内容后重排，新增的
            # 底部区域会先显示一条黑色未绘制带。
            with platform_win.suspend_redraw(self.root):
                self.root.geometry(
                    f"{self.root.winfo_width()}x{self.root.winfo_height() + extra}"
                    f"+{self.root.winfo_x()}+{self.root.winfo_y()}"
                )
                self.root.update_idletasks()
        finally:
            self._resizing = False

    def _choose_language(self, value: str) -> None:
        """设置窗口里切语言：立刻生效，并把设置窗口按新语言重建。"""
        if value not in CHOICES:
            return
        active = self.settings.language or current_preference()
        if value == active:
            return
        self.settings.language = value
        apply_language(value)
        self._save_settings()
        self.retranslate()
        # **不再销毁/重建设置窗口**：新建 Toplevel 时 native 窗口会先以
        # 默认尺寸出现一帧，用户能看到左上角闪一个小窗。设置窗口原地
        # 重译，既没有新 HWND，也不会打断代理输入框/焦点。
        self._retranslate_settings()

    def _retranslate_settings(self) -> None:
        """设置窗口原地换语言；尺寸固定，不重建、不缩放。"""
        window = self._settings_window
        if window is None or not window.winfo_exists():
            return
        with platform_win.suspend_redraw(window):
            window.title(L("设置", "Settings"))
            self._settings_proxy_caption.configure(text=L("网络代理", "Proxy"))
            self._settings_proxy_hint.configure(
                text=L(
                    "留空表示使用系统代理。格式如 http://127.0.0.1:7897",
                    "Blank = system proxy. Example: http://127.0.0.1:7897",
                )
            )
            self._settings_config_button.set_text(
                L("配置文件", "Config file"), repaint=False
            )
            self._settings_hints_label.configure(
                text=L("启动时显示使用提示", "Show help on startup")
            )
            self._settings_language_caption.configure(text=L("界面语言", "Language"))
            active = self.settings.language or current_preference()
            for value, button in self._settings_language_buttons.items():
                button.set_kind("accent" if value == active else "neutral")
            self._settings_close_button.set_text(L("关闭", "Close"), repaint=False)
            window.update_idletasks()
            self._settings_config_button._paint()  # noqa: SLF001 - 批量重绘
            self._settings_close_button._paint()  # noqa: SLF001

    def retranslate(self) -> None:
        """切语言时**整段冻结重绘**，只呈现切换前/后的两帧。

        不能靠逐个按钮 ``update_idletasks`` 来消残影：Tk 的中间布局状态
        本来就会送到屏幕，旧按钮的像素可能从新的缝隙里露出来。Windows 的
        ``LockWindowUpdate`` 把整棵窗口树锁住，等所有文字/宽度/状态都改完、
        几何也结算完，再一次性解锁并重画。
        """
        with platform_win.suspend_redraw(self.root):
            self._retranslate()

    def _retranslate(self) -> None:
        # 静态标签
        self.title_label.configure(text=L("文字转语音", "Text to Speech"))
        self.voice_caption.configure(text=L("语音", "Voice"))
        for field, caption in getattr(self, "_param_captions", {}).items():
            caption.configure(text=param_label(field))
        self.editor_caption.configure(text=L("要朗读的文字", "Text to read"))
        self.help_strip_text.configure(text=self._hint_strip_text())
        # 按钮（FlatButton 会按新文字重新量宽度）。先只改文字与请求宽度、
        # **不立即绘制**：否则每个按钮都会先用旧宽度画一帧，紧接着网格重排
        # 再画一帧——「选择…」变宽时，旁边会闪过一条旧按钮的白色残影。
        # 全部改完、让 Tk 结算一次几何，再统一重绘。
        self.help_strip_more.set_text(L("全部提示", "All tips"), repaint=False)
        self.help_strip_close.set_text(L("知道了", "Got it"), repaint=False)
        self.paste_button.set_text(L("读入文件", "Load file"), repaint=False)
        self.clear_button.set_text(L("清空", "Clear"), repaint=False)
        self.choose_dir_button.set_text(L("选择…", "Pick"), repaint=False)
        self.output_dir_button.set_text(L("输出目录", "Output"), repaint=False)
        self.generate_button.set_text(
            L("生成中…", "Generating...") if self.generating else L("生成语音", "Generate"),
            repaint=False,
        )
        self.cancel_button.set_text(L("取消", "Cancel"), repaint=False)
        self.open_file_button.set_text(L("打开音频", "Open audio"), repaint=False)
        # 占位/筛选/提示/计数
        if self._placeholder_active:
            self._set_placeholder()
        self._update_filter_placeholder()
        self._update_params_hint()
        self._update_tip()
        self._update_counts()
        self._update_voice_count()
        self._update_directory_label()
        self._refresh_voice_values(keep_selection=True)
        # 工具提示
        self._refresh_tooltips()
        # 状态栏：旧语言的状态句不再可靠；生成中不要覆盖实时进度提示。
        if not self.generating:
            self.set_status(L("界面语言已切换。", "Language changed."), "info")
        # 帮助窗口是只读长文，重建比逐行替换可靠；设置窗口由调用方重建。
        help_window = self._help_window
        if help_window is not None and help_window.winfo_exists():
            self._help_window = None
            help_window.destroy()
            self.root.after(0, self.show_help)
        # 先结算几何（按钮请求宽度、状态栏显隐都变了），再统一重绘按钮。
        self.root.update_idletasks()
        for button in (
            self.help_strip_more,
            self.help_strip_close,
            self.paste_button,
            self.clear_button,
            self.choose_dir_button,
            self.output_dir_button,
            self.generate_button,
            self.cancel_button,
            self.open_file_button,
        ):
            button._paint()  # noqa: SLF001 - 批量重绘，避免旧宽度残影
        # 按钮文字宽度/语音框宽度都随语言变，布局数字要重算。
        self.root.after(0, lambda: self._fix_progress_slot(force=True))
        self.root.after(0, self._fix_voice_width)

    def _refresh_tooltips(self) -> None:
        """更新 Tooltip 文案；图标按钮没有可见文字，提示必须跟着语言走。"""
        texts = [
            L("主题：跟随系统", "Theme: system"),
            L("主题：浅色", "Theme: light"),
            L("主题：深色", "Theme: dark"),
            L("设置", "Settings"),
            L("使用提示（Ctrl+H）", "Help (Ctrl+H)"),
            L("语速范围 -100 到 +200（%）", "Rate range -100 to +200 (%)"),
            L("音量范围 -100 到 +100（%）", "Volume range -100 to +100 (%)"),
            L("音调范围 -100 到 +100（Hz）", "Pitch range -100 to +100 (Hz)"),
        ]
        for tip, text_value in zip(getattr(self, "tooltips", []), texts):
            tip.update(text_value, self.theme)

    # ------------------------------------------------------------------ 状态

    def set_status(self, message: str, kind: str = "info") -> None:
        # 记下来：编辑区一动，就要判断这句是不是"关于编辑区旧状态"的
        self._status_text = message
        palette = self.theme.palette
        color = {
            "info": palette.text,
            "success": palette.success,
            "error": palette.error,
            "warning": palette.warning,
        }.get(kind, palette.text)
        self._show_status(message, color)
        self.result_paths = [] if kind in ("info", "error", "warning") else self.result_paths

    def _show_progress_detail(self, visible: bool) -> None:
        """进度详情那一行的显隐（隐藏时整行收起，不留高度）。"""
        visible_now = bool(self.progress_detail.winfo_manager())
        if visible and not visible_now:
            self.progress_detail.pack(side=tk.TOP, anchor="w", fill="x")
        elif not visible and visible_now:
            self.progress_detail.pack_forget()
        if visible != visible_now:
            self._schedule_settle()

    def _show_status(self, message: str, color: str) -> None:
        """把状态文字放进"状态 + 统计"那个紧凑块里。

        ⚠️ 没有消息时 `pack_forget()`：空着也占一个行高的话，底部就一直挂着
        一块空白（实测空状态栏 76px）。收起来之后块自动变矮，
        统计就紧贴在它下面。

        ⚠️ **已经显示/隐藏时不要重复 pack**：生成过程中每个进度事件都会
        调到这里；重复 pack 会让 Tk 重排状态区，表现为"状态栏闪一下"。
        只在**第一次显示或最后隐藏**时动布局。
        """
        was_visible = bool(self.status_label.winfo_manager())
        old_text = self.status_label.cget("text")
        self.status_label.configure(text=message, foreground=color)
        if message and not was_visible:
            self.status_label.pack(side=tk.TOP, anchor="w", fill="x", before=self.counts_label)
        elif not message and was_visible:
            self.status_label.pack_forget()
        # 状态行数变了 → 窗口跟着伸缩，**编辑区高度不变**
        if message != old_text or was_visible != bool(message):
            self._schedule_settle()

    def set_result_status(self, message: str, paths: List[str]) -> None:
        self.result_paths = paths
        self._show_status(message, self.theme.palette.success)
        self._show_result_buttons(True)
        self._schedule_settle()

    def _param_display(self, field: str, normalized: str) -> str:
        """把 ``+20%`` / ``-10Hz`` 还原成输入框里的纯数字。"""
        value = normalized
        if value.startswith("+"):
            value = value[1:]
        if field == "pitch":
            value = value.removesuffix("Hz")
        else:
            value = value.removesuffix("%")
        return value or "0"

    def _commit_param(self, field: str) -> bool:
        """校验/归一化一个参数；非法就恢复上次有效值并弹窗。"""
        if self._closing:
            return False
        entry = {
            "rate": self.rate_entry,
            "volume": self.volume_entry,
            "pitch": self.pitch_entry,
        }[field]
        parser = PARAM_SPECS[field][4]
        try:
            normalized = parser(entry.get())
        except params_mod.ParameterError as exc:
            self._restore_param(field, exc)
            return False
        display = self._param_display(field, normalized)
        if entry.get().strip() != display:
            entry.delete(0, tk.END)
            entry.insert(0, display)
        self._param_last_valid[field] = display
        self._update_params_hint()
        return True

    def _restore_param(self, field: str, error: params_mod.ParameterError) -> None:
        """把非法输入恢复到上一次有效值，并明确告诉用户范围。"""
        previous = self._param_last_valid.get(field, "0")
        entry = {
            "rate": self.rate_entry,
            "volume": self.volume_entry,
            "pitch": self.pitch_entry,
        }[field]
        entry.delete(0, tk.END)
        entry.insert(0, previous)
        self._update_params_hint()
        if self._closing:
            return
        label, unit, low, high, _parser = PARAM_SPECS[field]
        detail = (
            f"{error.message}\n"
            if ("无法识别" in error.message or "Unrecognized" in error.message)
            else ""
        )
        self.show_warning(
            L("参数超出范围", "Parameter out of range"),
            L(
                f"{param_label(field)}必须在 {low} 到 +{high}{unit} 之间。\n"
                f"{detail}"
                f"已恢复为上一次的有效值：{previous}{unit}。",
                f"{param_label(field)} must be between {low} and +{high}{unit}.\n"
                f"{detail}"
                f"Restored the last valid value: {previous}{unit}.",
            ),
        )
        entry.focus_set()
        entry.select_range(0, tk.END)

    def _remember_params(self, rate: str, volume: str, pitch: str) -> None:
        for field, normalized in (
            ("rate", rate),
            ("volume", volume),
            ("pitch", pitch),
        ):
            self._param_last_valid[field] = self._param_display(field, normalized)

    def _update_params_hint(self) -> None:
        try:
            rate, volume, pitch = params_mod.parse_all(
                self.rate_entry.get(), self.volume_entry.get(), self.pitch_entry.get()
            )
        except params_mod.ParameterError:
            self.params_hint.configure(text="")
            return
        description = params_mod.describe(rate, volume, pitch)
        self.params_hint.configure(text=description or L("原声", "Original"))

    # ------------------------------------------------------------------ 生成

    def _validate(self) -> Optional[tuple]:
        content = self.get_text()
        if not content:
            self.set_status(
                L(
                    "编辑区是空的——先粘贴要朗读的文字。",
                    "The editor is empty — paste the text to read first.",
                ),
                "warning",
            )
            self.text.focus_set()
            return None
        voice = self._selected_voice()
        if voice is None:
            self.set_status(
                L(
                    "还没有选择语音。等语音列表加载完，或在右上角筛选后选一个。",
                    "No voice is selected. Wait for the list to load, or filter and choose one.",
                ),
                "warning",
            )
            self.voice_box.focus_set()
            return None
        try:
            rate, volume, pitch = params_mod.parse_all(
                self.rate_entry.get(), self.volume_entry.get(), self.pitch_entry.get()
            )
        except params_mod.ParameterError as exc:
            self.set_status(exc.message, "warning")
            self._restore_param(exc.field, exc)
            return None
        self._remember_params(rate, volume, pitch)
        return content, voice, rate, volume, pitch

    def start_generation(self) -> None:
        """按钮与 Ctrl+Enter 都走这里。

        **顺序就是判据**：校验 → 问路径 → 才开始显示进度。
        用户在任何一步取消，屏幕上都不会出现进度条（规范 15.3）。
        """
        if self.generating:
            return
        validated = self._validate()
        if validated is None:
            return
        content, voice, rate, volume, pitch = validated

        # 保存对话框必须在进度出现之前问完：用户取消时就当什么都没发生。
        # **优先用内容标题**：同一段文字生成过之后 `last_file_name` 会被记住，
        # 但用户再粘一篇新内容时，旧文件名和内容毫无关系。所以默认名每次都从
        # 当前正文提取；只有提取不出来时才退回上次的名字。
        base_name = self._suggest_file_name(content)
        if base_name:
            base_name = text_mod.add_filename_suffix(
                base_name,
                params_mod.filename_suffix(rate, volume, pitch),
            )
        initial_name = (
            base_name
            or self.settings.last_file_name
            or "speech.mp3"
        )
        path = self._ask_save_path(initial_name)
        if not path:
            return

        audio_path = path if path.lower().endswith(".mp3") else f"{path}.mp3"
        self.settings.last_file_name = Path(audio_path).name
        self.settings.output_dir = str(Path(audio_path).parent)
        self._save_settings()
        self.start_generation_to(content, voice, rate, volume, pitch, audio_path)

    def start_generation_to(
        self,
        content: str,
        voice,
        rate: str,
        volume: str,
        pitch: str,
        audio_path: str,
    ) -> None:
        """已经拿到全部输入之后真正开跑。

        单独拆出来是为了**让"用户真实走的那条路"可以被自动核对**：
        ``tools/e2e_smoke.py`` 会把文字和语音填进真实控件，只把保存对话框
        换成一个已知路径，剩下的启动、进度、收尾、状态栏全部走真实代码。
        """
        # 把"估计总时长"传进去当进度条的分母。这个数**已经显示给用户看了**
        # （状态栏那句"约 52 秒语音"），所以按它算百分比是诚实的：
        # 用户看到的分子分母是同一个估计值。
        self._begin_progress(voice, rate, volume, pitch, text_mod.estimate_seconds(content))
        self.cancel_event = threading.Event()
        proxy = self.settings.proxy_or_none()

        def on_progress(progress: Progress) -> None:
            self.events.put(("progress", progress))

        def worker() -> None:
            try:
                result = synthesize(
                    text=content,
                    voice=voice.short_name,
                    audio_path=audio_path,
                    rate=rate,
                    volume=volume,
                    pitch=pitch,
                    proxy=proxy,
                    cancel=self.cancel_event,
                    on_progress=on_progress,
                )
                self.events.put(("done", result))
            except SynthesisCancelled:
                self.events.put(("cancelled", audio_path))
            except SynthesisError as exc:
                self.events.put(("failed", str(exc)))
            except Exception as exc:  # noqa: BLE001 - 兜底：后台线程不能静默死掉
                self.events.put(("failed", f"{type(exc).__name__}: {exc}"))

        self.worker = threading.Thread(target=worker, name="synthesis", daemon=True)
        self._synth_thread = self.worker
        self.worker.start()

    @staticmethod
    def _suggest_file_name(content: str) -> str:
        """根据正文提取一个默认文件名（用户仍可在保存对话框里改）。

        实现在 `text.py`：纯本地、无模型、无新依赖，只扫正文开头几段。
        提取不出来时返回空串，由调用方退回上次的文件名。
        """
        return text_mod.suggest_filename(content)

    def _ask_save_path(self, initial_name: str) -> str:
        try:
            path = filedialog.asksaveasfilename(
                parent=self.root,
                title=L("保存到", "Save to"),
                defaultextension=".mp3",
                initialfile=initial_name,
                initialdir=self.settings.resolved_output_dir(),
                filetypes=[
                    (L("MP3 音频", "MP3 audio"), "*.mp3"),
                    (L("所有文件", "All files"), "*.*"),
                ],
            )
        except tk.TclError:
            return ""
        return path or ""

    def _begin_progress(self, voice, rate, volume, pitch, estimated_seconds: float = 0.0) -> None:
        self.generating = True
        # 进度条的分母：估计总时长（秒）。<=0 时退回不确定态。
        self.progress_total_seconds = max(0.0, float(estimated_seconds))
        self.generate_button.set_enabled(False)
        self.generate_button.set_text(L("生成中…", "Generating..."))
        self.cancel_button.set_enabled(True)
        self.progress.place(x=0, rely=0.5, anchor="w", relwidth=1.0)
        self._place_cancel()
        # **真进度条，不是等待装饰**（用户定稿："是真正的进度条，而不是一个
        # 等待装饰"）。原来的 `mode="indeterminate"` + `start(18)` 是一段
        # 来回滑动的动画，看起来就是"转圈等待"。
        # 现在改成确定态：`已生成秒数 / 估计总秒数`，百分比直接显示。
        # 自绘进度条本身就是确定态、没有动画，**没有 stop()/mode 这回事**
        # （`ttk.Progressbar` 才需要），直接归零即可。
        self.progress.configure(maximum=1000, value=0)
        self.progress.set_value(0, "0%")
        description = params_mod.describe(rate, volume, pitch)
        detail = L(f"语音 {voice.short_name}", f"Voice {voice.short_name}")
        if description:
            detail = f"{detail} · {description}"
        self.progress_detail.configure(text=detail)
        self._show_progress_detail(True)
        self.set_status(L("正在连接服务端…", "Connecting to the server..."), "info")
        # 开新一轮就先撤掉上一轮的产物按钮（它们已经不该在那儿了）
        self._clear_results()
        self._set_inputs_enabled(False)

    def _set_inputs_enabled(self, enabled: bool) -> None:
        state = "readonly" if enabled else "disabled"
        self.voice_box.configure(state=state)
        for widget in (self.rate_entry, self.volume_entry, self.pitch_entry, self.voice_filter):
            widget.configure(state="normal" if enabled else "disabled")
        self.text.configure(state="normal" if enabled else "disabled")
        self.generate_button.set_enabled(enabled)
        # ⚠️ 产物按钮也必须在这里跟着变：`_begin_progress` 会禁用它们，
        # 而第一版的恢复列表里**没有它们**，于是生成结束后它们永远停在
        # disabled ——用户看到"打开音频/所在文件夹点不动"（实测报回来）。
        for button in (self.paste_button, self.clear_button,
                       self.open_file_button, self.open_folder_button):
            button.set_enabled(enabled)

    def cancel_generation(self) -> None:
        if not self.generating or self.cancel_event is None:
            return
        self.cancel_event.set()
        self.cancel_button.set_enabled(False)
        self.set_status(
            L("正在取消…已下载的部分会被丢弃", "Cancelling... downloaded parts will be discarded"),
            "warning",
        )

    def _end_progress(self) -> None:
        self.generating = False
        self.cancel_event = None
        self.progress.place_forget()
        self.cancel_button.place_forget()
        self._show_progress_detail(False)
        self.progress_total_seconds = 0.0
        self.cancel_button.grid_remove()
        self.generate_button.set_text(L("生成语音", "Generate"))
        self._set_inputs_enabled(True)

    def _drain_events(self) -> None:
        """每 80ms 把后台线程的消息搬进界面。

        **tkinter 不是线程安全的**：后台线程只往队列里放东西，界面改动全部
        发生在这里（主线程）。
        """
        try:
            while True:
                kind, payload = self.events.get_nowait()
                self._handle_event(kind, payload)
        except queue.Empty:
            pass
        if not self._closing:
            # 记住这个 id：窗口销毁时要撤掉它，否则 Tk 会在窗口已经没了之后
            # 再调回来一次，终端上留下 `while executing "..."` 的噪音。
            try:
                self._drain_id = self.root.after(80, self._drain_events)
            except tk.TclError:
                self._drain_id = None

    def _handle_event(self, kind: str, payload) -> None:
        if kind == "voices":
            self.catalog = payload
            self.catalog_error = ""
            self.voice_loading = False
            self._refresh_voice_values(keep_selection=True)
            self._update_voice_count()
            self.set_status(
                L(
                    f"语音列表已就绪（{len(self.catalog)} 项）",
                    f"Voice list ready ({len(self.catalog)} voices)",
                ),
                "success",
            )
            self._maybe_reload_pending_voices()
        elif kind == "voices_error":
            self.catalog_error = str(payload)
            self.voice_loading = False
            self._update_voice_count()
            self.set_status(
                L(
                    "语音列表没能从服务端获取，暂用内置的 4 个常用语音。"
                    "检查网络或代理设置后重试（改代理会自动重拉）。",
                    "Could not fetch the voice list; using 4 built-in voices. "
                    "Check the network or proxy (changing it reloads automatically).",
                ),
                "warning",
            )
            self._maybe_reload_pending_voices()
        elif kind == "progress":
            self._on_progress(payload)
        elif kind == "done":
            self._on_done(payload)
        elif kind == "failed":
            self._end_progress()
            self.set_status(L(f"生成失败：{payload}", f"Generation failed: {payload}"), "error")
            self._clear_results()
            self.show_error(L("生成失败", "Generation failed"), str(payload))
        elif kind == "cancelled":
            self._end_progress()
            self.set_status(
                L("已取消，没有留下任何文件。", "Cancelled; no files were left behind."),
                "warning",
            )

    def _on_progress(self, progress: Progress) -> None:
        if self.generating:
            seconds = progress.audio_milliseconds / 1000.0
            # 分子 = 已生成音频秒数（上游给的真实值）；
            # 分母 = 估计总时长（与状态栏"约 N 秒语音"同一个数）。
            # **夹到 99%**：估计总会偏一点，不许在还没完成时先显示 100%。
            total = self.progress_total_seconds
            if total > 0:
                ratio = min(0.99, seconds / total)
                self.progress.set_value(int(ratio * 1000), f"{ratio * 100:.0f}%")
            else:
                self.progress.set_value(self.progress.cget("value"), "")
            self.progress_detail.configure(
                text=(
                    L(
                        f"已生成 {seconds:0.1f} / 约 {total:.0f} 秒音频 · "
                        f"{progress.audio_bytes / 1024:0.1f} KB",
                        f"Generated {seconds:0.1f} / ~{total:.0f} sec · "
                        f"{progress.audio_bytes / 1024:0.1f} KB",
                    )
                    if total > 0
                    else L(
                        f"已生成 {seconds:0.1f} 秒音频 · {progress.audio_bytes / 1024:0.1f} KB",
                        f"Generated {seconds:0.1f} sec · {progress.audio_bytes / 1024:0.1f} KB",
                    )
                )
            )
            if progress.last_text:
                self.set_status(
                    L(f"正在合成：{progress.last_text}", f"Synthesizing: {progress.last_text}"),
                    "info",
                )

    def _on_done(self, result) -> None:
        self._end_progress()
        # 记下"这份产物是按哪段文案生成的"
        self._generated_content = self.get_text()
        size_mb = result.audio_bytes / (1024 * 1024)
        # 路径统一成 Windows 写法（用户实测："路径格式都不统一"——
        # 同一个状态栏里 `D:/Temp/02.mp3` 与 `D:\Temp.srt` 混着出现）
        lines = [
            L(
                f"完成：{text_mod.display_path(result.audio_path)}（{size_mb:0.2f} MB）",
                f"Done: {text_mod.display_path(result.audio_path)} ({size_mb:0.2f} MB)",
            )
        ]
        paths = [result.audio_path]
        if result.subtitle_path:
            lines.append(
                L(
                    f"字幕：{text_mod.display_path(result.subtitle_path)}"
                    f"（{result.cue_count} 条）",
                    f"Subtitles: {text_mod.display_path(result.subtitle_path)}"
                    f" ({result.cue_count} cues)",
                )
            )
            paths.append(result.subtitle_path)
        else:
            lines.append(
                L(
                    "这次没有生成字幕（服务端没有返回词边界）。",
                    "No subtitles were generated (the server returned no word boundaries).",
                )
            )
        lines.append(L(f"用时 {result.elapsed_seconds:0.1f} 秒", f"Took {result.elapsed_seconds:0.1f} sec"))
        self.set_result_status("\n".join(lines), paths)

    def reveal_output_dir(self) -> None:
        """「输出目录」按钮：在资源管理器里打开**产物所在目录**。

        常驻按钮（用户定稿）：它不依赖"这一次生成成功"，任何时候都能点——
        用户想找之前生成的音频时，不必先跑一次生成。
        目录取"本次实际保存的位置"（生成过就用它），否则用设置里的默认目录。
        """
        from pathlib import Path as _Path  # pylint: disable=import-outside-toplevel

        if self.result_paths:
            target = self.result_paths[0]
        else:
            target = self.settings.resolved_output_dir()
        path = _Path(target)
        folder = path if path.is_dir() else path.parent
        if not folder.exists():
            self.set_status(
                L(
                    f"这个目录还不存在：{text_mod.display_path(str(folder))}",
                    f"This folder does not exist yet: {text_mod.display_path(str(folder))}",
                ),
                "warning",
            )
            return
        platform_win.reveal_in_explorer(str(folder), select=path.is_file())

    def choose_output_dir(self) -> None:
        """「选择…」按钮：选默认输出目录（原来在设置窗口里的那个）。"""
        chosen = filedialog.askdirectory(
            parent=self.root,
            title=L("选择默认输出目录", "Choose default output folder"),
            initialdir=self.settings.resolved_output_dir(),
        )
        if not chosen:
            return
        # `askdirectory` 返回的是**正斜杠**（tkinter 一律正斜杠），存之前
        # 规范成 Windows 写法，这样配置里、界面上、状态栏里三处一致。
        self.settings.output_dir = text_mod.display_path(chosen)
        self._save_settings()
        self._update_directory_label()
        self.set_status(
            L(
                f"输出目录已改为 {text_mod.display_path(chosen)}",
                f"Output folder changed to {text_mod.display_path(chosen)}",
            ),
            "success",
        )

    def _update_directory_label(self) -> None:
        """刷新那行灰色路径。"""
        if hasattr(self, "directory_label"):
            self.directory_label.configure(
                text=text_mod.display_path(self.settings.resolved_output_dir())
            )

    def open_result(self) -> None:
        if not self.result_paths:
            return
        try:
            os.startfile(self.result_paths[0])  # type: ignore[attr-defined]  # noqa: S606
        except (OSError, AttributeError) as exc:
            self.set_status(L(f"打不开这个文件：{exc}", f"Could not open this file: {exc}"), "error")

    def reveal_result(self) -> None:
        if not self.result_paths:
            return
        platform_win.reveal_in_explorer(self.result_paths[0], select=True)

    # ------------------------------------------------------------------ 快捷键

    def _wire_shortcuts(self) -> None:
        bindings = {
            "<Control-Return>": lambda _e: self.start_generation(),
            "<Control-KP_Enter>": lambda _e: self.start_generation(),
            "<Control-o>": lambda _e: self.open_text_file(),
            "<Control-s>": lambda _e: self.save_text_file(),
            "<Control-l>": lambda _e: self.clear_text(),
            "<Control-h>": lambda _e: self.show_help(),
            "<Escape>": lambda _e: self._on_escape(),
        }
        for sequence, handler in bindings.items():
            self.root.bind_all(sequence, handler)

    def _on_escape(self) -> None:
        if self._help_window is not None and self._help_window.winfo_exists():
            self._help_window.destroy()
            return
        if self.generating:
            self.cancel_generation()

    # ------------------------------------------------------------------ 关闭

    def on_close(self) -> None:
        if self.generating:
            if not self.ask_yes_no(
                L("退出", "Quit"),
                L(
                    "正在生成语音。现在退出会丢弃已经下载的部分，确定退出吗？",
                    "Speech is being generated. Quitting now discards downloaded parts. Quit anyway?",
                ),
            ):
                return
            if self.cancel_event is not None:
                self.cancel_event.set()
        self._closing = True
        # 先取消语音列表请求，再等两个后台线程把 aiohttp/async loop 清理完；
        # 不等的话进程退出时会出现 "Unclosed client session / Event loop is closed"
        # 的噪音（用户 2026-10-18 在终端里看到的就是这些）。
        if self._voice_cancel_event is not None:
            self._voice_cancel_event.set()
        for thread, timeout in (
            (self._synth_thread, 3.0),
            (self._voice_thread, 2.0),
        ):
            if thread is not None and thread.is_alive():
                thread.join(timeout=timeout)
        # 先撤掉轮询再销毁窗口：留下一个待触发的 after 会让 Tk 在窗口没了之后
        # 又调回来一次（终端上就是那句 `while executing "…_drain_events"`）。
        if self._drain_id is not None:
            try:
                self.root.after_cancel(self._drain_id)
            except tk.TclError:
                pass
            self._drain_id = None
        if self._settle_after_id is not None:
            try:
                self.root.after_cancel(self._settle_after_id)
            except tk.TclError:
                pass
            self._settle_after_id = None
        for attribute in ("_proxy_save_id", "_proxy_reload_id"):
            after_id = getattr(self, attribute)
            if after_id is not None:
                try:
                    self.root.after_cancel(after_id)
                except tk.TclError:
                    pass
                setattr(self, attribute, None)
        try:
            self._save_settings()
        except Exception:  # noqa: BLE001 - 关闭时不再打扰用户
            pass
        self.root.destroy()
