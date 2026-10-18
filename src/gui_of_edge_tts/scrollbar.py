"""扁平滚动条：一条纯色圆角"滑块"，没有箭头、没有浮雕。

## 为什么要自己画

用户反馈：**"把滚动条换成纯色条状控件，让它更简洁一些。现在看起来和整个
风格不搭配，整个风格是偏扁平的，它有点拟物化。"**

Tk 的 ``ttk.Scrollbar`` 在 Windows 上走的是原生主题（``vista``）绘制，
两端的箭头、滑块上的抓手纹、trough 的立体边框都是**主题画出来的**——
可以用 ``style.element`` 去改，但那些元素的可调项很有限，改不掉"拟物"的底子。

所以自绘一条：**trough 就是面板底色，thumb 是一根圆角色条**。
边缘的抗锯齿复用 :mod:`raster` 那套位图（和按钮同一套机制）。

## 接口对齐

对外暴露和 ``ttk.Scrollbar`` 一样的 ``set(first, last)``，
所以调用方只需要把 ``ttk.Scrollbar`` 换成本类，其余（``yview``/``command``）
不用动：

    bar = FlatScrollbar(parent, orient="vertical", command=text.yview)
    text.configure(yscrollcommand=bar.set)
"""

from __future__ import annotations

import tkinter as tk
from typing import Callable, Optional

from . import raster
from .theme import FONT_PROGRESS_PT, SPACE_2, Theme


class FlatScrollbar(tk.Canvas):
    """纯色条状滚动条（自绘）。

    * **无箭头**：两端什么都不画——这是"扁平"的关键；
    * **无浮雕**：不给 trough 描边，thumb 也不留高光；
    * **thumb 是圆角条**：宽度不到 trough 的一半，居中放置；
    * 悬停/拖动时 thumb 变深，这是唯一的反馈（扁平的表达方式）。
    """

    #: thumb 的宽度占 trough 的比例。太宽会显得笨重，太窄点不中。
    THUMB_RATIO = 0.56
    #: thumb 的最小长度（物理像素）：内容很长时它不能细成一根线。
    MIN_THUMB = 24
    #: thumb 四周留的空隙（逻辑像素）。**留白是"圆得看得见"的前提**：
    #: 贴着 trough 边缘画时，圆角与直边在视觉上分不出来。
    THUMB_PAD = 1

    def __init__(
        self,
        master,
        command: Callable,
        theme: Theme,
        orient: str = "vertical",
        **kwargs,
    ) -> None:
        super().__init__(
            master,
            highlightthickness=0,
            borderwidth=0,
            takefocus=0,
            **kwargs,
        )
        self.command = command
        self.theme = theme
        self.orient = orient
        self._first = 0.0
        self._last = 1.0
        self._hover = False
        self._dragging = False
        self._drag_offset = 0.0
        self._thumb_span: tuple = (0.0, 0.0)   # trough 内的 (起点, 终点)，像素

        self.bind("<Button-1>", self._on_press)
        self.bind("<B1-Motion>", self._on_drag)
        self.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Enter>", self._on_enter)
        self.bind("<Leave>", self._on_leave)
        self.bind("<Configure>", lambda _e: self._paint())
        self.apply_theme(theme)

    # ---- 主题 --------------------------------------------------------------

    def apply_theme(self, theme: Theme) -> None:
        self.theme = theme
        palette = theme.palette
        thickness = max(8, theme.px(10))
        if self.orient == "vertical":
            self.configure(background=palette.background, width=thickness)
        else:
            self.configure(background=palette.background, height=thickness)
        self._paint()

    # ---- 对外接口（与 ttk.Scrollbar.set 一致）------------------------------

    def set(self, first, last) -> None:
        """由被滚动控件的 ``*scrollcommand`` 回调。"""
        self._first = float(first)
        self._last = float(last)
        self._paint()

    # ---- 交互 --------------------------------------------------------------

    def _thumb_pixels(self) -> tuple:
        """算出 thumb 在画布上的 (起点, 终点)。"""
        length = self.winfo_height() if self.orient == "vertical" else self.winfo_width()
        if length <= 1:
            return 0.0, 0.0
        span = max(0.0, self._last - self._first)
        if span >= 1.0:
            return 0.0, float(length)      # 不需要滚动：滑块铺满
        start = self._first * length
        size = max(float(self.MIN_THUMB), span * length)
        size = min(size, float(length))
        end = min(start + size, float(length))
        start = max(0.0, end - size)
        return start, end

    def _on_press(self, event) -> str:
        length = self.winfo_height() if self.orient == "vertical" else self.winfo_width()
        position = event.y if self.orient == "vertical" else event.x
        start, end = self._thumb_span
        if start <= position <= end and end > start:
            # 按在滑块上：进入拖动，记下按下点相对滑块起点的偏移
            self._dragging = True
            self._drag_offset = position - start
        else:
            # 按在轨道上：翻一页（和原生滚动条一致的行为）
            self._page(position)
        self._paint()
        return "break"

    def _on_drag(self, event) -> str:
        if not self._dragging:
            return "break"
        length = self.winfo_height() if self.orient == "vertical" else self.winfo_width()
        position = event.y if self.orient == "vertical" else event.x
        span = max(1e-6, self._last - self._first)
        size = self._thumb_span[1] - self._thumb_span[0]
        available = max(1.0, length - size)
        # 滑块位置 → 内容比例，再交给被滚动控件
        fraction = max(0.0, min(1.0, (position - self._drag_offset) / available))
        self.command("moveto", str(fraction))
        return "break"

    def _on_release(self, _event) -> str:
        self._dragging = False
        self._paint()
        return "break"

    def _page(self, position: float) -> None:
        start, end = self._thumb_span
        # ⚠️ 命令是**三个参数**：`("scroll", 数量, "pages")`。
        # 第一版写成了 `("scroll", "1", "pages", "pages")`（四个），
        # Tk 直接抛 `wrong # args: should be "... yview scroll number
        # units|pages|pixels"` ——**点轨道翻页整个是坏的**。
        # 证据：`Text.yview` 自己的实现就是 `self.tk.call(self._w, 'yview',
        # *args)`，而原生 scrollbar 传的正是三参数形式。
        self.command("scroll", 1 if position > end else -1, "pages")

    def _on_enter(self, _event=None) -> None:
        self._hover = True
        self.configure(cursor="hand2")
        self._paint()

    def _on_leave(self, _event=None) -> None:
        self._hover = False
        self._paint()

    # ---- 绘制 --------------------------------------------------------------

    def _paint(self) -> None:
        self.delete("all")
        palette = self.theme.palette
        self.configure(background=palette.background)
        width = max(int(self.winfo_width()), 1)
        height = max(int(self.winfo_height()), 1)
        start, end = self._thumb_pixels()
        self._thumb_span = (start, end)
        if end - start < 1:
            return

        # 扁平：**不画 trough 的边框**，thumb 就是一根圆角色条。
        # 两端做成**完整胶囊**：半径取"厚度的一半"（= 完全半圆端），
        # 四周再留 `THUMB_PAD` 的空隙，圆角才看得出来。
        colour = palette.scrollbar_hover if (self._hover or self._dragging) else palette.scrollbar
        pad = self.theme.px(self.THUMB_PAD)
        thickness = max(6, self.theme.px(6))
        radius = thickness // 2
        # ⚠️ 长度必须 **>= 2 x 半径**，否则圆角会被 `raster` 夹成直角——
        # 胶囊变方块。实测踩过：滑块本来就短（`MIN_THUMB`）时再减掉两倍的
        # `pad`，长度只剩 4px，而半径是 5px，两端就方了。
        # 所以先减 `pad`，再**夹到 2x半径以上**。
        capsule_min = radius * 2
        if self.orient == "vertical":
            x0 = (width - thickness) / 2
            length = max(capsule_min, int(end - start) - pad * 2)
            points = raster.cached_rounded_rect(
                max(1, int(thickness)), length, radius, colour, colour, 0,
                background=palette.background, supersample=2,
            )
            photo = tk.PhotoImage(master=self, data=points)
            self.create_image(x0 + thickness / 2, (start + end) / 2, image=photo, anchor="center")
        else:
            y0 = (height - thickness) / 2
            length = max(capsule_min, int(end - start) - pad * 2)
            points = raster.cached_rounded_rect(
                length, max(1, int(thickness)), radius, colour, colour, 0,
                background=palette.background, supersample=2,
            )
            photo = tk.PhotoImage(master=self, data=points)
            self.create_image((start + end) / 2, y0 + thickness / 2, image=photo, anchor="center")
        self._thumb_photo = photo  # 必须留引用，否则被回收


class FlatProgress(tk.Canvas):
    """扁平进度条（自绘）。

    ## 为什么要自绘

    用户要求「进度条 / 打开音频 / 生成语音」**在同一行**，且那一行的高度
    由「生成语音」按钮（58px）决定。而 `ttk.Progressbar` 只能画"轨道 + 填充"
    这一条，**百分比和"已生成 N 秒"必须另占行**——三行叠起来自然高度 78px，
    会把整行撑高，按钮跟着变高、行也跟着抖。

    自绘就能把这一整块压成**一条**：Canvas 本身给固定高度，
    填充是圆角条、百分比画在条的右边，全部落在同一条线内。

    ## 外观

    与 `FlatScrollbar` 同一套语言：**纯色、圆角、无边框、无浮雕**。
    轨道用 `palette.track`，填充用 `palette.accent`，百分比用正文色。
    """

    #: 条本身的高度（逻辑像素）。比按钮矮很多才像"一条进度"，不抢视觉。
    BAR_HEIGHT_PX = 8
    #: Canvas 的总高度（逻辑像素）：条 + 上方留白，用来放百分比。
    TOTAL_HEIGHT_PX = 20
    #: 百分比文字与条之间的间距（逻辑像素）。
    LABEL_GAP_PX = 6
    #: 百分比文字的宽度（逻辑像素）：固定宽度，数字变化时条不会跟着抖。
    LABEL_WIDTH_PX = 44

    def __init__(self, master, theme: Theme, **kwargs) -> None:
        super().__init__(
            master,
            highlightthickness=0,
            borderwidth=0,
            takefocus=0,
            height=theme.px(self.TOTAL_HEIGHT_PX),
            **kwargs,
        )
        self.theme = theme
        self._maximum = 1000
        self._value = 0
        self._text = ""
        self._image = None
        self._fill_image = None
        # 轨道/圆头的位图缓存：(键, PhotoImage)。键包含尺寸与配色，
        # 换主题或改窗口宽度时自然失效，不必手工清。
        self._track_key = None
        self._cap_key = None
        self._fallback_key = None
        self.bind("<Configure>", lambda _e: self._paint())

    # ---- 接口与 ttk.Progressbar 保持兼容（configure(value=…) 的用法不变）----

    def configure(self, **kwargs):  # noqa: D102 - 与 ttk 同名同义
        redraw = False
        if "value" in kwargs:
            self._value = kwargs.pop("value")
            redraw = True
        if "maximum" in kwargs:
            self._maximum = kwargs.pop("maximum")
            redraw = True
        if kwargs:
            super().configure(**kwargs)
        if redraw:
            self._paint()

    config = configure

    def cget(self, key):  # noqa: D102
        if key == "value":
            return self._value
        if key == "maximum":
            return self._maximum
        return super().cget(key)

    def set_value(self, value: float, text: str = "") -> None:
        """设置进度和它右边那行字（百分比）。

        进度值与文字都没变时**不重绘**：生成时每来一个词边界都会调到这里，
        而音频字节数在两次音频分片之间是不变的——那不改变任何像素。
        """
        if value == self._value and text == self._text:
            return
        self._value = value
        self._text = text
        self._paint()

    # ---- 绘制 --------------------------------------------------------------

    def _image_for(
        self,
        prefix: str,
        key: tuple,
        width: int,
        height: int,
        radius: float,
        fill: str,
        background: str,
    ):
        """按 ``key`` 缓存一张圆角位图（PNG 解码后的 PhotoImage）。

        缓存放在控件上而不是模块里：解码结果绑定 ``master``，跟着控件走；
        键里带尺寸与颜色，换主题/改宽度时旧图自然不再命中。
        """
        if getattr(self, prefix + "_key", None) == key:
            return getattr(self, prefix + "_image", None)
        try:
            png = raster.cached_rounded_rect(
                width, height, radius, fill,
                background=background, supersample=2,
            )
            image = tk.PhotoImage(master=self, data=png)
        except Exception:  # noqa: BLE001 - 位图失败就退回多边形/旧路径
            image = None
        setattr(self, prefix + "_key", key)
        setattr(self, prefix + "_image", image)
        return image

    def _paint(self) -> None:
        palette = self.theme.palette
        width = max(1, self.winfo_width())
        height = max(1, self.winfo_height())
        self.configure(background=palette.background)
        self.delete("all")

        label_w = self.theme.px(self.LABEL_WIDTH_PX)
        gap = self.theme.px(self.LABEL_GAP_PX)
        bar_w = max(8, width - label_w - gap)
        bar_h = max(4, self.theme.px(self.BAR_HEIGHT_PX))
        radius = bar_h // 2
        top = (height - bar_h) // 2

        ratio = 0.0
        if self._maximum:
            ratio = max(0.0, min(1.0, float(self._value) / float(self._maximum)))

        # 轨道：整条都用圆角矩形（胶囊）。只在宽度/配色变化时重新栅格化。
        track_key = ("track", bar_w, bar_h, radius, palette.track, palette.background)
        track = self._image_for(
            "_track", track_key, bar_w, bar_h, radius,
            palette.track, palette.background,
        )
        if track is not None:
            self._image = track
            self.create_image(0, top, image=track, anchor="nw")

        # 填充：**按实际进度宽度**画（宽度下限 = 一个圆的直径，
        # 这样 0% 刚起步时也是完整的一颗，不会变成一根针）。
        # 不画满再遮挡——遮挡会在切换主题/重绘时露馅。
        filled = max(bar_h, int(bar_w * ratio)) if ratio > 0 else 0
        filled = min(filled, bar_w)
        if filled > 0:
            self._paint_fill(filled, bar_h, radius, top, palette)

        if self._text:
            self.create_text(
                width - label_w, height // 2,
                text=self._text, anchor="w",
                fill=palette.text,
                font=self.theme.font(FONT_PROGRESS_PT, bold=True),
            )

    def _paint_fill(self, filled: int, bar_h: int, radius: int, top: int, palette) -> None:
        """填充部分：**两个缓存的圆头 + 一段直角矩形**。

        ## 为什么不整颗胶囊一次栅格化

        生成时每收到一个音频分片，填充宽度就变一次。整颗胶囊按当前宽度
        栅格化，等于每变一次都重算一整张位图——实测 636px 画布上
        **单次 30~60 ms**（P90 54.5 ms），一次生成里要重算几十次。

        拆成"圆头 + 矩形"之后：

        * 圆头只取决于条高与配色，**一次生成里只栅格化一次**（缓存）；
        * 宽度变化只是 ``create_rectangle`` 的一次调用（<0.1 ms）；
        * 矩形上下两条边是水平直线、与像素网格对齐，不需要抗锯齿；
          需要抗锯齿的只有两端圆弧，而它们来自缓存的位图。

        画法与旧路径几何一致：左颗圆的左半圆 = 左端，右颗圆的右半圆 =
        右端，矩形补中间直段。**先贴两颗圆、再贴矩形**——否则朝内的
        半个圆会把轨道色盖回填充上（那会在两端各留一个凹口）。
        """
        accent = palette.accent
        track = palette.track
        if filled <= 2 * bar_h:
            # 刚起步（0%~约 5%）时两段直边还不存在：两颗圆头会互相重叠，
            # 先贴后贴的顺序会在顶端留下一个轨道色的凹口。这一段按旧路径
            # 整颗栅格化——宽度最多 2 个条高，栅格化很便宜，而且只在
            # 生成的**开头**出现一次。
            fallback_key = ("fill", filled, bar_h, radius, accent, track)
            fallback = self._image_for(
                "_fallback", fallback_key, filled, bar_h, radius, accent, track
            )
            if fallback is not None:
                self._fill_image = fallback
                self.create_image(0, top, image=fallback, anchor="nw")
            return
        cap_key = ("cap", bar_h, radius, accent, track)
        cap = self._image_for("_cap", cap_key, bar_h, bar_h, radius, accent, track)
        if cap is None:
            # 兜底：退回"按宽度整颗栅格化"的老路径，宁可慢也要画对。
            fallback_key = ("fill", filled, bar_h, radius, accent, track)
            fallback = self._image_for(
                "_fallback", fallback_key, filled, bar_h, radius, accent, track
            )
            if fallback is not None:
                self._fill_image = fallback
                self.create_image(0, top, image=fallback, anchor="nw")
            return

        self.create_image(0, top, image=cap, anchor="nw")
        self.create_image(filled - bar_h, top, image=cap, anchor="nw")
        # ⚠️ 右下边界写 `top + bar_h` 而不是 `top + bar_h - 1`：
        # Tk 的 `create_rectangle` 在没有 outline 时**填充区域不含右/下边界**，
        # 写 `- 1` 会让直段只有 bar_h-1 像素高，比两端的圆头细 1 像素
        # （用户截图报回来："两端圆点比矩形粗"）。实测回读：圆头 14 行、
        # 直段 13 行；改成 `top + bar_h` 后两者都是 14 行。
        self.create_rectangle(
            radius, top, filled - radius, top + bar_h,
            fill=accent, outline="",
        )
        self._fill_image = cap
