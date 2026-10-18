"""配色与样式：一套逻辑像素网格 + 深浅两套调色板。

规则来自视觉规范：

* **尺寸写成逻辑像素，只换算一次**（``px()`` / ``font()``），不出现"同一个量
  在两处各写一遍"；
* **颜色优先从系统读**（深浅模式、强调色），读不到才用这里的默认值；
* 间距全部是 **4 的倍数**；
* 层级靠**分层容器**（背景 → 卡片），不是给控件自己上色；
* 深色下"浮起来"靠**提亮**，不是压暗。
"""

from __future__ import annotations

import tkinter.font as tkfont
from dataclasses import dataclass
from typing import Dict

from . import platform_win

# --------------------------------------------------------------------------- #
# 逻辑像素网格（4 的倍数）
# --------------------------------------------------------------------------- #
SPACE_1 = 4
SPACE_2 = 8
SPACE_3 = 12
SPACE_4 = 16
SPACE_5 = 20
SPACE_6 = 24

WINDOW_MIN_WIDTH = 620
WINDOW_MIN_HEIGHT = 520
# 用户定稿：在 880x720 的基础上**增宽 50%、增高 10%**。
WINDOW_DEFAULT_WIDTH = 1320
WINDOW_DEFAULT_HEIGHT = 792
BORDER_FOCUS_WIDTH = 2

# 字号（磅）。正文与按钮与系统 UI 同级 = 10pt，次要信息小一号 = 9pt。
FONT_BODY_PT = 10
FONT_SMALL_PT = 9
# 「使用提示」窗口的正文字号。**与主界面正文同号（10pt）**：
# 用户先反馈"太小"（升到 12pt），看过之后又反馈"大了"，最后定在 10pt。
# 保留这个常量是因为**它必须能单独调**：主界面那条提示条的宽度是量过的，
# 跟着一起放大就会被截断（版位自检会拦）。
FONT_HELP_PT = 10
FONT_TITLE_PT = 16
FONT_PROGRESS_PT = 13

#: 字体族优先级（用户定稿：**全局用微软雅黑 UI**）。
#:
#: 为什么它排第一：这是中文界面，而 **Segoe UI 系列不含汉字**——
#: 用 Segoe UI 时汉字要靠系统逐字回退到别的字体，结果是"中文和数字、
#: 英文的字形来自两套字体"，基线与字重都对不齐。用户实测看出来了。
#: 微软雅黑 UI 同时覆盖中英文与数字，界面才是统一的一套字形。
#:
#: 后面的候选是"这台机器上没有雅黑"时的退路（例如英文版 Windows）。
_FONT_STACK = (
    "Microsoft YaHei UI",
    "Microsoft YaHei",
    "微软雅黑",
    "Segoe UI Variable Text",
    "Segoe UI",
    "TkDefaultFont",
)


@dataclass(frozen=True)
class Palette:
    """一套主题的全部颜色。字段名即用途，没有"备用色"。

    **分层规则（v1.1.0 用户定稿）**：整个面板只有**一个底色**，
    不靠"卡片比窗口亮一档"来分层——那会变成一块一块的色块。
    层级只由两件事表达：

    * **输入区**（编辑区、参数框）用 ``surface``：比底色亮一档 + 描边，
      这是 Windows 上"这里是能打字的"的惯例；
    * **可点击按钮**用 ``surface`` + ``border_strong`` 描边，**同一套逻辑**，
      所以"能不能点"看起来是一致的。

    ``card`` 与 ``background`` 取值相同，保留字段是因为 ttk 样式与
    主题切换的代码按名字引用它。
    """

    name: str
    background: str          # 面板底色（唯一的那一层）
    card: str                # 内容层；**与 background 相同**（保持单一底色）
    surface: str             # 输入框与按钮的表面（比底色亮一档）
    surface_hover: str       # 悬停/按下
    border: str              # 输入框描边、分隔线
    border_strong: str       # 按钮描边、聚焦描边
    text: str                # 正文（浅色纯黑 / 深色纯白）
    text_secondary: str      # 次要信息
    accent: str              # 强调色：只给"推荐的那一个动作"
    accent_hover: str
    accent_text: str         # 强调色上的文字
    success: str
    error: str
    warning: str
    track: str               # 进度条/滑轨底色
    # 滚动条**自己的三个色**。为什么不复用 `surface_hover`：
    # 那个词的意思是"按钮悬停"，被滚动条借去当滑动块底色之后，
    # 两边就绑死了——改按钮悬停会把滚动条一起改坏（用户实测报回来：
    # "默认色变成浅蓝、悬停色变成灰色"，正是配反 + 绑死的结果）。
    scrollbar: str           # 滑动块（常态）
    scrollbar_hover: str     # 滑动块（悬停/按下）
    scrollbar_arrow: str     # 两端箭头
    selection: str           # 文本选中底色

    @property
    def surface_alt(self) -> str:
        """旧名字，等价于 :attr:`surface`。

        留一个属性而不是两个字段：**一个概念只有一个权威来源**，否则
        "输入框底色"会有两处定义，迟早分叉（归档 `02` 第六节）。
        """
        return self.surface

    def as_dict(self) -> Dict[str, str]:
        return {
            "name": self.name,
            "background": self.background,
            "card": self.card,
            "surface": self.surface,
            "surface_hover": self.surface_hover,
            "border": self.border,
            "border_strong": self.border_strong,
            "text": self.text,
            "text_secondary": self.text_secondary,
            "accent": self.accent,
            "accent_hover": self.accent_hover,
            "accent_text": self.accent_text,
            "success": self.success,
            "error": self.error,
            "warning": self.warning,
            "track": self.track,
            "scrollbar": self.scrollbar,
            "scrollbar_hover": self.scrollbar_hover,
            "scrollbar_arrow": self.scrollbar_arrow,
            "selection": self.selection,
        }


#: 浅色主题**悬停色**的两个可调量（色相 **不在这里**）。
#:
#: 用户两次反馈合起来才是完整要求：
#:
#: 1. "亮度和原来的浅灰悬停色一致，饱和度或者说纯度再提。你见过淡蓝色的
#:    天空吗，就是那种感觉。"
#: 2. "它的色相不能改变，还是我们现在生成语音、或者选中一些控件时固定的
#:    那个蓝色。我们要以这个蓝色的色相为基准，去把它变浅。"
#:
#: ⚠️ 第一版我为了"显得透亮"把色相从 220° 挪到 199°，结果**变成了青绿色**
#: ——用户一句"你见过青绿色的天空吗"点破了。**色相是语义，不是可调参数**：
#: 界面上的蓝只有一个色相（强调色），悬停态只能是它"变浅"，
#: 不能变成另一个颜色。所以色相从 ``palette.accent`` 现取，这里只留
#: 饱和度与明度两个旋钮。
#:
#: ⚠️ **对齐的是"感知亮度"，不是 HSV 的 V。**
#:
#: 用户第二次说"太暗了，不够亮。它的明暗和之前的那个浅灰色是不一样的"。
#: 我上一版把 V 对齐到 0.937（和原浅灰一样），以为就"同亮度"了——**错了**：
#: 蓝通道的亮度权重只有 0.114（绿是 0.587，红是 0.299），所以同样的 V，
#: 蓝看起来比灰暗得多。实测感知亮度（``0.299R+0.587G+0.114B``）：
#:
#:   * 原浅灰 ``#E9EBEF`` → **234.9**
#:   * 上一版 ``#BFCDEF``（V=0.937）→ **204.7**   ← 用户看到的"更暗"
#:   * 本版 ``#DEE7FC`` → **230.7**（差 4.2）
#:
#: 结论：想让淡蓝"看起来和浅灰一样亮"，**必须把 V 拉到接近 1.0**，
#: 同时把饱和度压低（饱和度越高 → 蓝越多 → 越暗）。
HOVER_SATURATION = 0.12
HOVER_VALUE = 0.99


LIGHT = Palette(    name="light",
    background="#F3F4F6",   # 面板：浅灰
    card="#F3F4F6",         # 与面板同色——不留色块
    surface="#FFFFFF",      # 输入框/按钮：白
    surface_hover="#E9EBEF",
    border="#D7DAE0",       # 输入框描边
    border_strong="#B4BAC4",  # 按钮描边（要能看出边界）
    text="#000000",
    text_secondary="#5D5D5D",
    accent="#0067C0",
    accent_hover="#005BA8",
    accent_text="#FFFFFF",
    success="#0F7B0F",
    error="#C42B1C",
    warning="#9D5D00",
    track="#DFE2E7",
    scrollbar="#C7CBD3",
    scrollbar_hover="#A9AFBA",
    scrollbar_arrow="#5D5D5D",
    selection="#CCE4F7",
)

DARK = Palette(
    name="dark",
    background="#191919",   # 面板：深灰
    card="#191919",         # 与面板同色
    surface="#2B2B2B",      # 输入框/按钮：比面板亮一档
    surface_hover="#363636",
    border="#3F3F3F",
    border_strong="#565656",
    text="#FFFFFF",
    text_secondary="#B0B0B0",
    accent="#4CC2FF",
    accent_hover="#6FCEFF",
    accent_text="#0A0A0A",
    success="#6CCB5F",
    error="#FF99A4",
    warning="#FCE100",
    track="#333333",
    scrollbar="#4A4A4A",
    scrollbar_hover="#5E5E5E",
    scrollbar_arrow="#B0B0B0",
    selection="#2C4A63",
)


def _mix(hex_a: str, hex_b: str, ratio: float) -> str:
    """把 ``hex_a`` 朝 ``hex_b`` 推进 ``ratio``（0~1）。"""
    ratio = max(0.0, min(1.0, ratio))

    def channel(value: str, index: int) -> int:
        return int(value[index : index + 2], 16)

    out = []
    for index in (1, 3, 5):
        a = channel(hex_a, index)
        b = channel(hex_b, index)
        out.append(round(a + (b - a) * ratio))
    return "#{:02X}{:02X}{:02X}".format(*out)


def _rgb(hex_colour: str) -> tuple:
    text = hex_colour.lstrip("#")
    return int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16)


def _to_hsv(hex_colour: str) -> tuple:
    r, g, b = (value / 255.0 for value in _rgb(hex_colour))
    high, low = max(r, g, b), min(r, g, b)
    delta = high - low
    if delta == 0:
        hue = 0.0
    elif high == r:
        hue = (60 * ((g - b) / delta)) % 360
    elif high == g:
        hue = 60 * ((b - r) / delta) + 120
    else:
        hue = 60 * ((r - g) / delta) + 240
    saturation = 0.0 if high == 0 else delta / high
    return hue, saturation, high


def _from_hsv(hue: float, saturation: float, value: float) -> str:
    saturation = max(0.0, min(1.0, saturation))
    value = max(0.0, min(1.0, value))
    chroma = value * saturation
    x = chroma * (1 - abs((hue / 60.0) % 2 - 1))
    m = value - chroma
    sector = int(hue // 60) % 6
    table = (
        (chroma, x, 0.0),
        (x, chroma, 0.0),
        (0.0, chroma, x),
        (0.0, x, chroma),
        (x, 0.0, chroma),
        (chroma, 0.0, x),
    )[sector]
    return "#{:02X}{:02X}{:02X}".format(
        *(round((channel + m) * 255) for channel in table)
    )


def _boost(hex_colour: str, saturation_scale: float, value_scale: float) -> str:
    """按倍数提高**饱和度**与**明度**，色相不变。

    用户要的是"提高浅蓝的饱和度与明度"——这两个量在 HSV 里是独立轴，
    而 ``_mix`` 那种按通道混合会连色相带明度一起动，表达不了这个要求。
    """
    hue, saturation, value = _to_hsv(hex_colour)
    return _from_hsv(hue, saturation * saturation_scale, value * value_scale)


class Theme:
    """当前主题：调色板 + 尺寸换算 + ttk 样式。

    一个实例贯穿整个程序生命周期；切换主题时重建一个并重新应用到控件。
    """

    def __init__(self, dark: bool, accent: str = "") -> None:
        self.dark = dark
        base = DARK if dark else LIGHT
        self.palette = self._apply_accent(base, accent) if accent else base
        # 悬停色**在强调色定下来之后**再派生（它要用 accent），所以顺序不能换：
        # 先 `_apply_accent`，再 `_apply_hover`。
        self.palette = self._apply_hover(self.palette, self.dark)
        self.dpi = platform_win.system_dpi()
        self._fonts: Dict[tuple, tkfont.Font] = {}
        self.ttk_style = None  # 由 apply_ttk_style 填

    # ---- 构造 --------------------------------------------------------------

    @classmethod
    def detect(cls, mode: str = "system", accent: str = "") -> "Theme":
        """``mode`` 是 ``system`` / ``light`` / ``dark`` 三者之一。"""
        if mode == "dark":
            dark = True
        elif mode == "light":
            dark = False
        else:
            dark = platform_win.system_uses_dark_theme()
        resolved_accent = accent or (platform_win.system_accent_color() or "")
        return cls(dark=dark, accent=resolved_accent)

    @staticmethod
    def _apply_accent(base: Palette, accent: str) -> Palette:
        """把系统强调色合进来，**只换强调相关的三项**，其余保持规范值。

        深色下强调色要当"淡色文字"用，所以往白推一档；浅色下直接用。
        """
        if not accent or len(accent) != 7 or not accent.startswith("#"):
            return base
        if base.name == "dark":
            accent_main = _mix(accent, "#FFFFFF", 0.35)
            accent_hover = _mix(accent, "#FFFFFF", 0.5)
            accent_text = "#0A0A0A"
        else:
            accent_main = accent
            accent_hover = _mix(accent, "#000000", 0.18)
            accent_text = "#FFFFFF"
        return Palette(
            **{
                **base.as_dict(),
                "accent": accent_main,
                "accent_hover": accent_hover,
                "accent_text": accent_text,
            }
        )

    @staticmethod
    def _apply_hover(base: Palette, dark: bool) -> Palette:
        """悬停色改为**从强调色派生的浅蓝**。

        用户反馈："鼠标悬停按钮变浅灰不太好看，换成浅蓝色。"

        为什么用 `_mix` 而不是手写一个蓝：强调色本身是从系统读的
        （``DWM\\AccentColor``），写死的蓝在用户换了系统强调色之后会和按钮的
        选中态不搭；派生出来的则永远和强调色同族。

        比例：浅色下 0.86（很淡，白底上只是"染了一层蓝"）；
        深色下 0.80（同样淡，但底色是深灰，所以朝**背景**方向推，
        避免悬停时按钮反而比底色亮太多）。

        ⚠️ 后来又按用户要求"提高饱和度与明度"做了二次增强：先派生出一个
        同族的浅蓝，再用 HSV 把饱和度和明度各提一档（浅色 2.2x / 1.06x，
        深色 1.7x / 1.35x）。**这两步分开写**，是因为"同族"与"更艳更亮"
        是两件事；用一次 `_mix` 同时表达两者只会把色相也带偏。
        """
        if dark:
            hover = _mix(base.accent, base.background, 0.80)
            hover = _boost(hover, 1.7, 1.35)
        else:
            # 浅色悬停 = **强调色变浅**：色相取自强调色本身，只动饱和度与明度。
            # 色相是"蓝"这个语义的载体，不能当调参旋钮用（踩过一次，见常量注释）。
            accent_hue, _accent_sat, _accent_val = _to_hsv(base.accent)
            hover = _from_hsv(accent_hue, HOVER_SATURATION, HOVER_VALUE)
        return Palette(**{**base.as_dict(), "surface_hover": hover})

    # ---- 尺寸 --------------------------------------------------------------

    def px(self, logical: int) -> int:
        """逻辑像素 → 物理像素。**只在这里换算一次。**"""
        return int(round(logical * self.dpi / 96.0))

    def font(self, points: int = FONT_BODY_PT, bold: bool = False, family: str = ""):
        """按磅取值、换算成像素字号的字体对象。"""
        key = (points, bold, family)
        cached = self._fonts.get(key)
        if cached is not None:
            return cached
        families = set(self._available_families())
        chosen = family or next((f for f in _FONT_STACK if f in families), "TkDefaultFont")
        size_px = max(9, int(round(points * self.dpi / 72.0)))
        font = tkfont.Font(
            family=chosen,
            size=-size_px,  # 负值 = 像素高度，避免 Tk 再按自己的比例缩一次
            weight="bold" if bold else "normal",
        )
        self._fonts[key] = font
        return font

    @staticmethod
    def _available_families():
        try:
            return tkfont.families()
        except Exception:  # noqa: BLE001 - 没有 Tk 根窗口时 stdlib 会抛
            return ()

    # ---- ttk ---------------------------------------------------------------

    def apply_ttk_style(self, root) -> None:
        """配置 ttk 控件（进度条、下拉框、滚动条）。"""
        from tkinter import ttk  # pylint: disable=import-outside-toplevel

        palette = self.palette
        style = ttk.Style(root)
        try:
            style.theme_use("clam")  # 唯一一套"每个颜色都能改"的内置主题
        except Exception:  # noqa: BLE001
            pass

        body = self.font()
        small = self.font(FONT_SMALL_PT)

        style.configure(
            ".",
            background=palette.card,
            foreground=palette.text,
            fieldbackground=palette.surface_alt,
            bordercolor=palette.border,
            lightcolor=palette.card,
            darkcolor=palette.card,
            troughcolor=palette.track,
            focuscolor=palette.accent,
            font=body,
        )
        style.configure("TFrame", background=palette.background)
        style.configure("Card.TFrame", background=palette.card)
        style.configure("TLabel", background=palette.background, foreground=palette.text)
        style.configure("Card.TLabel", background=palette.card, foreground=palette.text)
        style.configure(
            "Small.Card.TLabel",
            background=palette.card,
            foreground=palette.text_secondary,
            font=small,
        )
        style.configure(
            "Hint.Card.TLabel",
            background=palette.card,
            foreground=palette.text_secondary,
            font=small,
        )

        style.configure(
            "Accent.Horizontal.TProgressbar",
            troughcolor=palette.track,
            background=palette.accent,
            bordercolor=palette.track,
            lightcolor=palette.accent,
            darkcolor=palette.accent,
            thickness=max(6, self.px(6)),
        )
        style.configure(
            "Horizontal.TProgressbar",
            troughcolor=palette.track,
            background=palette.text_secondary,
            bordercolor=palette.track,
            lightcolor=palette.text_secondary,
            darkcolor=palette.text_secondary,
            thickness=max(6, self.px(6)),
        )

        style.configure(
            "TCombobox",
            fieldbackground=palette.surface_alt,
            background=palette.surface_alt,
            foreground=palette.text,
            # 描边交给外层 holder（ttk 去掉 downarrow 后右边框会缺）
            bordercolor=palette.surface_alt,
            lightcolor=palette.surface_alt,
            darkcolor=palette.surface_alt,
            selectbackground=palette.selection,
            selectforeground=palette.text,
            padding=self.px(4),
        )
        # 下拉弹层的外框：默认是 SystemButtonFace（浅灰），深色下会露一圈浅边。
        style.configure(
            "ComboboxPopdownFrame",
            background=palette.background,
            relief="flat",
            borderwidth=0,
        )
        # 用户 2026-10-17 给的二选一：把倒三角区域放宽/放大，或直接去掉。
        # 这里选**去掉**：readonly 的 ttk.Combobox 点击框内任何位置都会
        # `Post`（见 combobox.tcl 的 Press：readonly 时 entryPress 恒为假），
        # 所以不需要那个又窄又小的箭头矩形；整条框都是可点击的。
        style.layout(
            "TCombobox",
            [
                (
                    "Combobox.field",
                    {
                        "sticky": "nswe",
                        "children": [
                            (
                                "Combobox.padding",
                                {
                                    "sticky": "nswe",
                                    "children": [
                                        ("Combobox.textarea", {"sticky": "nswe"})
                                    ],
                                },
                            )
                        ],
                    },
                )
            ],
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", palette.surface_alt), ("disabled", palette.card)],
            foreground=[("disabled", palette.text_secondary)],
        )
        # 下拉列表是 Tk 的 listbox，只能通过 option 数据库上色
        root.option_add("*TCombobox*Listbox.background", palette.surface_alt)
        root.option_add("*TCombobox*Listbox.foreground", palette.text)
        root.option_add("*TCombobox*Listbox.selectBackground", palette.accent)
        root.option_add("*TCombobox*Listbox.selectForeground", palette.accent_text)
        root.option_add("*TCombobox*Listbox.font", body)

        for orient, name in (("vertical", "Vertical.TScrollbar"), ("horizontal", "Horizontal.TScrollbar")):
            # ⚠️ 这一处的映射**第一版配反了**：`background`（滑动块）用了
            # `surface_hover`，而 `map(active=…)`（悬停/按下）用了
            # `border_strong`——于是"默认是浅蓝、悬停反而变灰"，和用户的
            # 预期正好相反（他实测报回来）。
            #
            # 现在用滚动条**自己的三个字段**，语义一一对应：
            # 槽 = 面板色（要能沉下去）、块 = `scrollbar`、悬停 = `scrollbar_hover`、
            # 箭头 = `scrollbar_arrow`。不再挪用按钮的 `surface_hover`
            # ——那个词是"按钮悬停"，被两处共用时改一边会带坏另一边。
            style.configure(
                name,
                background=palette.scrollbar,
                troughcolor=palette.background,
                bordercolor=palette.background,
                arrowcolor=palette.scrollbar_arrow,
                lightcolor=palette.scrollbar,
                darkcolor=palette.scrollbar,
                relief="flat",
            )
            style.map(
                name,
                background=[("active", palette.scrollbar_hover), ("pressed", palette.scrollbar_hover)],
            )

        style.configure(
            "TSpinbox",
            fieldbackground=palette.surface_alt,
            background=palette.surface_alt,
            foreground=palette.text,
            arrowcolor=palette.text_secondary,
            bordercolor=palette.border_strong,
            lightcolor=palette.border,
            darkcolor=palette.border,
            padding=self.px(3),
        )
        style.configure("TSeparator", background=palette.border)

        self.ttk_style = style

    # ---- tk 控件 -----------------------------------------------------------

    def style_text_widget(self, widget) -> None:
        """把 tk.Text 设成输入框该有的样子。"""
        palette = self.palette
        widget.configure(
            background=palette.surface_alt,
            foreground=palette.text,
            insertbackground=palette.text,
            selectbackground=palette.selection,
            selectforeground=palette.text,
            highlightthickness=0,
            borderwidth=0,
            relief="flat",
            padx=self.px(8),
            pady=self.px(8),
            font=self.font(),
            spacing1=self.px(2),
            spacing3=self.px(2),
            wrap="word",
            undo=True,
            maxundo=200,
        )
        # 占位符颜色与光标颜色由控件自己用 tag 控制
        widget.tag_configure(
            "placeholder",
            foreground=palette.text_secondary,
            font=self.font(),
        )
