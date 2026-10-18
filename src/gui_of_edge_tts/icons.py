"""标题栏那几个图标：**全部用图元描述，逐像素栅格化**。

## 为什么不用字体字形

第一版写的是字符（`"⚙"`、`"◐"`、`"☀"`）。实测：

* `"⚙"` 在 `Segoe UI Variable Text` 里**没有字形**，Windows 拿默认的"缺字形
  方框"兜底——它的 advance 宽度是 32px（和汉字一样宽），而 `?` 只有 10px。
  也就是说设置按钮一直在显示一个**空心方框**。
* `"☀"` / `"☾"` 有字形，但渲染成什么由系统字体决定：黑白轮廓、彩色 emoji、
  或者宽度和基线都跟旁边文字不一样。**这些都不受我们控制。**

所以图标改成"描述形状 → 栅格化 → 作为图像贴上"。形状是确定的，
尺寸、线宽、颜色全都由自己定，也不受字体影响。

## 图元格式

``(kind, ...参数..., colour)``，颜色永远是最后一个元素：

* ``("rect", x0, y0, x1, y1, stroke, colour, fill, radius)``
* ``("ellipse", x0, y0, x1, y1, stroke, colour, fill)``
  —— ``stroke=0`` 表示**实心**（此时 ``fill`` 不参与）
* ``("line", x0, y0, x1, y1, stroke, colour)``
* ``("arc", cx, cy, rx, ry, start, extent, stroke, colour)``
* ``("polygon", (x, y, x, y, ...), colour)``

``stroke`` 是描边宽度（0 表示实心），``colour`` 是描边色，``fill`` 是填充色
（``None`` 表示只描边不填充）。

## 这一版按 `Icons-Drawing.md` 重画（2026-10-17）

四条直接来自那份文档、而且这里都踩过的规则：

1. **小尺寸下实心比空心更像**。24px 里空心圆的环宽只剩 1~2 像素，看起来
   是"一个脏的圆圈"；太阳因此改成**实心圆盘 + 八个小圆点**。
2. **比例决定像不像**。显示器从 2:1 收窄到 **1.72:1 ≈ 16:9**；动的是宽度，
   不是高度——高度一动整个图标就变小了。
3. **视觉重心 ≠ 几何中心**。月牙的实体偏左，几何居中时看着就是偏左；
   整条轮廓向右平移 ``MOON_SHIFT_RATIO``。
4. **画中画要拿到底色**。齿轮的中心孔必须用**按钮当前底色**画，
   所以所有 painter 的签名都带 ``background``；底色随主题/悬停/选中态变。

## 旋钮

凡是"看着调"的比例都提成**有名的常量**（见下面 ``SUN_*`` / ``MOON_*`` /
``GEAR_*``）——这些值几乎一定要再改几轮，改常量是一秒的事，改坐标是十分钟。
"""

from __future__ import annotations

import math
from typing import Callable, List, Optional

#: 图元的线宽按图标尺寸的比例给，这样放大缩小都协调。
STROKE_RATIO = 1.0 / 9.0

#: 图标位图的边长 = ``size × 这个系数``。
#:
#: **不是 1.0**：图元坐标最远到 **±0.52·size**（太阳的光点 = 0.45 + 0.07；
#: 月牙的纵向也是 0.45）。按 ``size + 2`` 开画布时，实际余量只有 1 像素，
#: 在 27px 下刚好够、在 **160px 预览图**里就会把光点裁成平口——同一份代码
#: 在不同尺寸下表现不同，是最难查的一类"看起来像"。
#: 放大到 1.2 倍只是给位图四周留透明余量，**图标本身尺寸不变**。
ICON_BOX_SCALE = 1.2

#: 太阳：圆盘半径 / 光点半径 / 光点中心距（都是 ``size`` 的倍数）。
#: 用户 2026-10-17 在 File Tracker 那轮把光点从"粗线段"缩成"小点"，
#: 这三个比例就是那次定稿的值。
SUN_DISC_RADIUS_RATIO = 0.26
SUN_DOT_RADIUS_RATIO = 0.07
SUN_ORBIT_RATIO = 0.45

#: 月牙：整条轮廓向右平移多少（视觉重心补偿）。
#: 0 → "重心在左侧"；0.045 / 0.09 → "还不够居中"；**0.12** 才通过。
MOON_SHIFT_RATIO = 0.12

#: 齿轮：齿数、齿根半径、齿顶半径、齿顶/齿根半角（弧度）、中心孔半径。
#: 8 齿在 27px 下仍能数清；再少像风扇，再多糊成一圈。
GEAR_TEETH = 8
GEAR_ROOT_RADIUS_RATIO = 0.31
GEAR_TIP_RADIUS_RATIO = 0.47
GEAR_TIP_HALF_ANGLE = 0.14
GEAR_ROOT_HALF_ANGLE = 0.22
GEAR_HOLE_RADIUS_RATIO = 0.13

#: painter 的统一签名：``(圆心x, 圆心y, 尺寸, 颜色, 底色) -> 图元列表``。
Painter = Callable[[float, float, float, str, Optional[str]], List[tuple]]


def icon_monitor(
    cx: float, cy: float, size: float, colour: str, background: Optional[str] = None
) -> List[tuple]:
    """跟随系统：空心屏幕外框 + 底座横线。

    ``background`` 收下但不用（统一签名，方便 ``FlatButton`` 直接调）。
    """
    half = size / 2.0
    stroke = max(1.0, size * STROKE_RATIO)
    # 收窄显示屏：宽 0.86 × size、高 0.5 × size ⇒ 1.72:1 ≈ 16:9。
    # **只动宽度**：动高度会让整个图标变小，而用户要的是"别横向挤占"。
    half_w = half * 0.86
    top = cy - half * 0.74
    bottom = cy + half * 0.26
    return [
        ("rect", cx - half_w, top, cx + half_w, bottom, stroke, colour, None, stroke),
        # 底座：跟着外框一起收窄，保持居中
        ("line", cx - half_w * 0.5, bottom + stroke * 1.9,
         cx + half_w * 0.5, bottom + stroke * 1.9, stroke, colour),
    ]


def icon_sun(
    cx: float, cy: float, size: float, colour: str, background: Optional[str] = None
) -> List[tuple]:
    """浅色：**实心圆盘 + 八个小圆点**。

    演化：空心圆 + 八条细线 → 实心圆 + 八条粗线 → **实心圆盘 + 八个小点**。
    用户原话："光线现在又有点太粗了，你干脆把它们全部各自原地缩小退化成小点"。
    """
    radius = size * SUN_DISC_RADIUS_RATIO
    parts: List[tuple] = [
        ("ellipse", cx - radius, cy - radius, cx + radius, cy + radius, 0, colour, None)
    ]
    dot_radius = size * SUN_DOT_RADIUS_RATIO
    orbit = size * SUN_ORBIT_RATIO
    for index in range(8):
        angle = math.radians(index * 45)
        dx = cx + orbit * math.cos(angle)
        dy = cy + orbit * math.sin(angle)
        parts.append(
            ("ellipse", dx - dot_radius, dy - dot_radius,
             dx + dot_radius, dy + dot_radius, 0, colour, None)
        )
    return parts


def icon_moon(
    cx: float, cy: float, size: float, colour: str, background: Optional[str] = None
) -> List[tuple]:
    """深色：**实心月牙 = 整圆减去一个偏移的圆**。

    做法是"整圆减一个偏心圆"，按两圆交点算出一条闭合折线（40 点），
    栅格化时用射线法判内外，得到的就是一个月牙。

    为什么不用两段 ``arc`` 拼：两次描边的圆环各自只有 1 像素宽，交叠处会
    形成"楔形缺口"，看起来是两个细弧而不是一个月亮。

    ## 为什么整条轮廓向右平移

    月牙的实体落在左侧，几何居中时**看着偏左**。用户连说两次"还不够居中"，
    最后一次原话是"在月亮图标前面加一个空格"——但自绘几何里空格不参与，
    真塞进 label 还会把按钮撑宽。所以改成平移 ``MOON_SHIFT_RATIO``。
    """
    radius = size * 0.45
    offset = size * 0.30          # 内圆向右偏，缺口在右侧
    inner_radius = radius * 1.02
    samples = 40

    # 两圆交点：a = (r1² - r2² + d²) / (2d)
    a = (radius * radius - inner_radius * inner_radius + offset * offset) / (2.0 * offset)
    half_chord = math.sqrt(max(0.0, radius * radius - a * a))
    theta = math.atan2(half_chord, a)             # 交点相对外圆心的极角
    phi = math.atan2(half_chord, a - offset)      # 交点相对内圆心的极角

    shift = size * MOON_SHIFT_RATIO
    points: List[float] = []
    # 外圆：从上方交点走"大的那一侧"到下方交点
    for index in range(samples + 1):
        angle = theta + (2 * math.pi - 2 * theta) * index / samples
        points.extend((cx + shift + radius * math.cos(angle),
                       cy + radius * math.sin(angle)))
    # 内圆：从下方交点沿内弧回到上方交点（把缺口切掉）
    for index in range(samples + 1):
        angle = (2 * math.pi - phi) - (2 * math.pi - 2 * phi) * index / samples
        points.extend((cx + shift + offset + inner_radius * math.cos(angle),
                       cy + inner_radius * math.sin(angle)))
    return [("polygon", tuple(points), colour)]


def icon_gear(
    cx: float, cy: float, size: float, colour: str, background: Optional[str] = None
) -> List[tuple]:
    """设置：**实心齿轮 + 中心孔**。

    ## 为什么是实心 + 一个孔

    旧版是"空心圆环 + 八颗齿 + 里面再套一个小圆环"——在 27px 下，
    两圈细环各只剩 1~2 像素，看起来像雪花/星号，而且中心孔和外环之间
    又夹了一圈线。齿轮能认出来靠的是**一个干净的实心轮廓 + 一个孔**，
    所以这一版整块齿形是一个 ``polygon``，孔用按钮底色盖出来。

    ## 孔为什么用 ``background``

    实心圆上画同色的孔等于没画。要看起来"镂空"，必须拿**按钮当前的底色**
    去画它——底色随主题、hover、选中态变化，只能由调用方传进来
    （``FlatButton._paint`` 传的是按钮填充色，也是图标位图的底色）。
    拿不到底色时退回 ``colour``（孔会消失，但图标仍然是个完整的齿轮）。
    """
    root_radius = size * GEAR_ROOT_RADIUS_RATIO
    tip_radius = size * GEAR_TIP_RADIUS_RATIO
    points: List[float] = []
    for index in range(GEAR_TEETH):
        center = 2.0 * math.pi * index / GEAR_TEETH
        # 一颗齿：齿根 → 齿顶 → 齿顶 → 齿根（梯形，外宽内窄）
        for offset, radius in (
            (-GEAR_ROOT_HALF_ANGLE, root_radius),
            (-GEAR_TIP_HALF_ANGLE, tip_radius),
            (GEAR_TIP_HALF_ANGLE, tip_radius),
            (GEAR_ROOT_HALF_ANGLE, root_radius),
        ):
            angle = center + offset
            points.extend((cx + radius * math.cos(angle), cy + radius * math.sin(angle)))

    hole_radius = size * GEAR_HOLE_RADIUS_RATIO
    hole_colour = background if background is not None else colour
    return [
        ("polygon", tuple(points), colour),
        # 中心孔：实心圆盖成底色（raster 的覆盖率合成会得到抗锯齿边缘）
        ("ellipse", cx - hole_radius, cy - hole_radius,
         cx + hole_radius, cy + hole_radius, 0, hole_colour, None),
    ]


#: 三个主题图标：**显示器 = 跟随系统、太阳 = 浅色、月亮 = 深色**（用户定稿）。
THEME_ICONS: dict = {"system": icon_monitor, "light": icon_sun, "dark": icon_moon}

#: 设置按钮的图标（同一个"画"的函数，和主题图标同一套机制）。
SETTINGS_ICON = icon_gear
