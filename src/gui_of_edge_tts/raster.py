"""**不依赖任何第三方库**的栅格化器：把形状画成带抗锯齿的 PNG 位图。

## 为什么需要它

用户实测反馈："每个按钮的圆角还是存在明显的锯齿。"

这不是写错了，是 **Tk 的 Canvas 根本不画抗锯齿**——`create_polygon` 出来就是
硬边阶梯，没有开关可调。所以"把圆角画圆"在 Tk 里做不到。

三条路的代价（都实测过）：

| 做法 | 结果 |
|---|---|
| 把 Pillow 打进 exe 做超采样 | 可行，但 **exe 从 17.58 MB 涨到 24.59 MB**（+7 MB） |
| Tk 的 `-stipple` 位图近似 | `BitmapImage(data=...)` 内联数据在本机 **报 `format error`** |
| **自己算覆盖率 + 自己写 PNG** | **零新增依赖、零体积增长**（`zlib` 是标准库，spec 已打包 `zlib.dll`） |

选第三条：

1. **覆盖率抗锯齿**：边界像素取 4x4 子采样，数落在形状内的比例 → alpha。
2. **自己编码 PNG**：`IHDR` + `IDAT`（`zlib` 压缩）+ `IEND`。PNG 支持 alpha，
   Tk 8.6 内建解码器，`PhotoImage(data=bytes)` 直接吃得下（实测通过）。
3. 位图当**底层**放，文字仍交给 Tk 画——Tk 的文字有字体提示（hinting），
   比我们自己栅格化清楚。

## 形状用"图元列表"描述

图标（显示器/太阳/月亮/齿轮）是**用图元拼出来的**，不是字体字形
（`"⚙"` 在本机没有字形，会渲染成空心方框）。图元列表把"描述形状"与
"变成像素"分开：图标只负责说清画什么，栅格化只负责画好。

## 性能（都是实测值）

* `rounded_rect_coverage`（按钮、开关）：120x45 是 **8 ms**，52x52 是 **5 ms**；
* 结果**按参数缓存**（`cached_rounded_rect`），命中后 + Tk 解码是 **0.26 ms**；
* 缓存满 512 条就整体清空——按钮的尺寸/配色组合是有限的，不会失控。
"""

from __future__ import annotations

import math
import struct
import zlib
from functools import lru_cache
from typing import Dict, List, Optional, Sequence, Tuple

#: 每个像素方向上的子采样数。4 表示 16 个子采样——角落能得到 16 级灰度，
#: 肉眼已看不出阶梯。再高收益递减，代价是平方增长。
#: 图标图元的子采样数。图标本身较小，4×4 已够；按钮圆角单独用更高档。
SUBSAMPLES = 4
#: 圆角矩形（按钮/开关/滚动条）的子采样数。
#: 按钮再按 2 倍分辨率渲染后 2×2 盒式降采样，等效 256 个子采样；
#: 这样不仅有颜色过渡，边缘的空间过渡也有约 2 个目标像素，175% 下
#: 不会出现"一个像素一跳"的阶梯。
ROUNDED_SUBSAMPLES = 8

RGBA = Tuple[int, int, int, int]
#: 图元：``(kind, ...参数..., colour)``，颜色一律是最后一个元素。
Primitive = tuple


def parse_colour(value: str) -> RGBA:
    """把 ``#RRGGBB`` / ``#RGB`` 解析成 RGBA。"""
    text = value.strip().lstrip("#")
    if len(text) == 3:
        text = "".join(ch * 2 for ch in text)
    if len(text) != 6:
        raise ValueError(f"看不懂的颜色：{value!r}")
    return (int(text[0:2], 16), int(text[2:4], 16), int(text[4:6], 16), 255)


def write_png(width: int, height: int, rows: Sequence[bytes]) -> bytes:
    """把逐行 RGBA 数据编码成 PNG 字节（只用标准库 ``zlib``）。"""
    raw = bytearray()
    for row in rows:
        raw.append(0)  # 过滤器：0 = None
        raw.extend(row)

    def chunk(tag: bytes, payload: bytes) -> bytes:
        return (
            struct.pack(">I", len(payload))
            + tag
            + payload
            + struct.pack(">I", zlib.crc32(tag + payload) & 0xFFFFFFFF)
        )

    return b"".join(
        (
            b"\x89PNG\r\n\x1a\n",
            chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)),
            chunk(b"IDAT", zlib.compress(bytes(raw), 9)),
            chunk(b"IEND", b""),
        )
    )


# --------------------------------------------------------------------------- #
# 圆角矩形：最常用，单独做结构优化
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=8)
def rounded_rect_coverage(
    width: int, height: int, radius: float, inset: float = 0.0
) -> List[List[int]]:
    """圆角矩形的覆盖率网格（0..255），**内联标量算术**。

    为什么不用通用的"闭包版有符号距离"：实测每次调用闭包再开平方，120x45 的
    按钮要 24 ms、13 个按钮首屏 689 ms——启动会明显卡一下。这里把距离公式摊平成
    局部变量与乘法，靠三层判定把绝大多数像素 O(1) 解决（实测降到 8 ms）。

    判定分三层（``BAND`` 是半个像素的对角线）：

    * ``d > BAND``：整块在形状内 → 255
    * ``d < -BAND``：整块在形状外 → 0
    * 其余：做 ``ROUNDED_SUBSAMPLES²`` 子采样，得到 1..254 的中间档——**这就是抗锯齿**

    结果按几何参数做小容量 LRU 缓存：悬停只换颜色时不用重新算覆盖率，
    否则每颗按钮第一次悬停都要重算 2× 高分辨率整图。
    """
    band = 0.7072
    step = 1.0 / ROUNDED_SUBSAMPLES
    total = ROUNDED_SUBSAMPLES * ROUNDED_SUBSAMPLES

    x0, y0 = inset, inset
    x1, y1 = width - inset, height - inset
    cx = (x0 + x1) / 2.0
    cy = (y0 + y1) / 2.0
    half_w = max(0.0, (x1 - x0) / 2.0 - radius)
    half_h = max(0.0, (y1 - y0) / 2.0 - radius)
    radius_sq = radius * radius
    skip_sq = (radius + 1.0) * (radius + 1.0)

    def coverage(px: int, py: int) -> int:
        x = px + 0.5
        y = py + 0.5
        dx = abs(x - cx) - half_w
        dy = abs(y - cy) - half_h
        if dx <= 0.0 and dy <= 0.0:
            return 255
        if dx <= 0.0:
            outside_sq = dy * dy
        elif dy <= 0.0:
            outside_sq = dx * dx
        else:
            outside_sq = dx * dx + dy * dy
        if outside_sq >= skip_sq:
            return 0
        distance = radius - outside_sq**0.5
        if distance > band:
            return 255
        if distance < -band:
            return 0
        hits = 0
        for sy in range(ROUNDED_SUBSAMPLES):
            yy = py + (sy + 0.5) * step
            dy2 = abs(yy - cy) - half_h
            for sx in range(ROUNDED_SUBSAMPLES):
                xx = px + (sx + 0.5) * step
                dx2 = abs(xx - cx) - half_w
                if dx2 <= 0.0 and dy2 <= 0.0:
                    hits += 1
                    continue
                if dx2 <= 0.0:
                    sq = dy2 * dy2
                elif dy2 <= 0.0:
                    sq = dx2 * dx2
                else:
                    sq = dx2 * dx2 + dy2 * dy2
                if sq <= radius_sq:
                    hits += 1
        return (hits * 255) // total

    return [[coverage(px, py) for px in range(width)] for py in range(height)]


def _rounded_rect_rows(
    width: int,
    height: int,
    radius: float,
    fill: str,
    outline: str,
    outline_width: float,
    background: Optional[str],
) -> List[bytes]:
    """按像素生成圆角矩形的 RGBA 行。"""
    fill_rgba = parse_colour(fill)
    stroke_rgba = parse_colour(outline) if outline else fill_rgba
    bg_rgba = parse_colour(background) if background else None
    inset = max(0.0, outline_width)

    inner = rounded_rect_coverage(width, height, max(0.0, radius - inset), inset + inset)
    outer = (
        rounded_rect_coverage(width, height, max(0.0, radius), inset) if inset > 0 else None
    )

    rows: List[bytes] = []
    for py in range(height):
        row = bytearray()
        inner_row = inner[py]
        outer_row = outer[py] if outer is not None else None
        for px in range(width):
            inner_alpha = inner_row[px]
            if bg_rgba is not None:
                # 预混合：背景 → 描边（外层覆盖率）→ 填充（内层覆盖率）。
                # 输出 alpha 恒为 255，不依赖 Tk 对半透明 PNG 的合成。
                r, g, b = bg_rgba[:3]
                if outer_row is not None:
                    a = outer_row[px] / 255.0
                    r = round(r + (stroke_rgba[0] - r) * a)
                    g = round(g + (stroke_rgba[1] - g) * a)
                    b = round(b + (stroke_rgba[2] - b) * a)
                a = inner_alpha / 255.0
                r = round(r + (fill_rgba[0] - r) * a)
                g = round(g + (fill_rgba[1] - g) * a)
                b = round(b + (fill_rgba[2] - b) * a)
                row.extend((r, g, b, 255))
                continue

            # 无底色（标题栏/独立 PNG）：保留原来的透明 alpha 合成。
            if outer_row is None:
                colour, alpha = fill_rgba, inner_alpha
            else:
                outer_alpha = outer_row[px]
                if inner_alpha >= outer_alpha and inner_alpha > 0:
                    colour, alpha = fill_rgba, inner_alpha
                else:
                    colour, alpha = stroke_rgba, max(outer_alpha, inner_alpha)
            row.extend((colour[0], colour[1], colour[2], alpha))
        rows.append(bytes(row))
    return rows


def _downsample_rows(
    rows: List[bytes], width: int, height: int, scale: int, opaque: bool
) -> List[bytes]:
    """把 ``scale`` 倍分辨率的 RGBA 行按盒式滤波降回目标尺寸。"""
    result: List[bytes] = []
    count = scale * scale
    for py in range(height):
        row = bytearray()
        for px in range(width):
            sr = sg = sb = sa = 0
            for sy in range(scale):
                source = rows[py * scale + sy]
                offset = px * scale * 4
                for _sx in range(scale):
                    r, g, b, a = (
                        source[offset],
                        source[offset + 1],
                        source[offset + 2],
                        source[offset + 3],
                    )
                    if opaque:
                        sr += r
                        sg += g
                        sb += b
                    elif a:
                        sr += r * a
                        sg += g * a
                        sb += b * a
                        sa += a
                    offset += 4
            if opaque:
                row.extend((sr // count, sg // count, sb // count, 255))
            elif sa:
                row.extend((sr // sa, sg // sa, sb // sa, sa // count))
            else:
                row.extend((0, 0, 0, 0))
        result.append(bytes(row))
    return result


def rounded_rect_png(
    width: int,
    height: int,
    radius: float,
    fill: str,
    outline: str = "",
    outline_width: float = 0.0,
    background: Optional[str] = None,
    supersample: int = 1,
) -> bytes:
    """生成一个**抗锯齿**的圆角矩形 PNG。

    先铺描边色（半径相同），再叠一个**内缩 outline_width** 的填充色——
    描边于是自然只在外缘露出一条，和自绘按钮的层次一致。

    ``background`` 非空时输出**不透明** PNG：先把描边、填充按覆盖率
    混合到该底色上。按钮的圆角要嵌在面板底色里，若保留透明 alpha，
    Tk 的 Canvas 合成会把"描边→填充"的内边缘也当成透明边，角上出现
    硬切换/浅色缝；预混合后两层边都是真正的连续色阶。

    ``supersample`` >1 时先按该倍数分辨率渲染，再做盒式降采样；边缘
    会从 1 像素过渡变成约 2 像素，175% 下不再有"一个像素一跳"的阶梯。
    """
    scale = max(1, int(supersample))
    if scale > 1:
        high_rows = _rounded_rect_rows(
            width * scale,
            height * scale,
            radius * scale,
            fill,
            outline,
            outline_width * scale,
            background,
        )
        rows = _downsample_rows(
            high_rows, width, height, scale, opaque=background is not None
        )
    else:
        rows = _rounded_rect_rows(
            width, height, radius, fill, outline, outline_width, background
        )
    return write_png(width, height, rows)


# --------------------------------------------------------------------------- #
# 通用图元：描边用"叠一层内缩实心"实现，于是图元只需要"填充"一种语义
# --------------------------------------------------------------------------- #


def _distance_to_segment(px, py, x0, y0, x1, y1) -> float:
    dx, dy = x1 - x0, y1 - y0
    length_sq = dx * dx + dy * dy
    if length_sq <= 1e-9:
        return math.hypot(px - x0, py - y0)
    t = ((px - x0) * dx + (py - y0) * dy) / length_sq
    t = max(0.0, min(1.0, t))
    return math.hypot(px - (x0 + t * dx), py - (y0 + t * dy))


#: "擦除"用的透明色：用它在已有像素上做 alpha 合成，等于**挖空**。
#: 空心形状（显示器的边框、太阳的圆环、齿轮的中心孔）靠它实现——
#: 只有"填充"一种操作时，画不出中间是空的形状。
#: "擦除"用的哨兵色。
#: ⚠️ 不要用空字节做哨兵——那是一个**真空字节**，
#: 写进 .py 文件之后 Python 连解析都做不到（``source code string cannot
#: contain null bytes``）。第一版就是这么写的，直接把文件弄坏了。
CLEAR = "clear"


def _expand(primitive: Primitive) -> List[Tuple[str, tuple, str]]:
    """把一个图元展开成若干"填充/擦除"操作。

    三种情形：

    * ``fill`` 是颜色、``width > 0``：描边色实心 + **内缩**的填充色实心
      —— 描边自然只在外缘露出一条；
    * ``fill`` 是颜色、``width <= 0``：一个实心；
    * ``fill is None``：**空心** —— 描边色实心 + 内缩半个线宽的**透明擦除**。
      ⚠️ 第一版把这一支当成"实心"，于是显示器的边框、太阳的圆心、齿轮的
      中心孔全被填满了（用户从预览图上看出来了）。
    """
    kind = primitive[0]
    # ⚠️ 颜色**单独放一个字段**，不要塞进 params 的尾巴：
    # `rect` 的最后一个参数是圆角半径、`polygon` 最后是点列，都不是颜色。
    # 第一版写死 `params[-1]` 取颜色，于是在 rect 上取到了半径（一个 float），
    # 报 `can't multiply sequence by non-int of type 'float'`。
    if kind == "rect":
        _, x0, y0, x1, y1, width, colour, fill, radius = primitive
        if width <= 0:
            return [("rect", (x0, y0, x1, y1, radius), colour)]
        if fill is None:
            half = width / 2.0
            return [
                ("rect", (x0, y0, x1, y1, radius), colour),
                ("rect", (x0 + half, y0 + half, x1 - half, y1 - half, max(0.0, radius - half)), CLEAR),
            ]
        return [
            ("rect", (x0, y0, x1, y1, radius), colour),
            ("rect", (x0 + width, y0 + width, x1 - width, y1 - width, max(0.0, radius - width)), fill),
        ]
    if kind == "ellipse":
        _, x0, y0, x1, y1, width, colour, fill = primitive
        if width <= 0:
            return [("ellipse", (x0, y0, x1, y1), colour)]
        if fill is None:
            half = width / 2.0
            return [
                ("ellipse", (x0, y0, x1, y1), colour),
                ("ellipse", (x0 + half, y0 + half, x1 - half, y1 - half), CLEAR),
            ]
        return [
            ("ellipse", (x0, y0, x1, y1), colour),
            ("ellipse", (x0 + width, y0 + width, x1 - width, y1 - width), fill),
        ]
    if kind == "line":
        _, x0, y0, x1, y1, width, colour = primitive
        return [("line", (x0, y0, x1, y1, max(1.0, width)), colour)]
    if kind == "polygon":
        _, points, colour = primitive
        return [("polygon", (tuple(points),), colour)]
    if kind == "arc":
        _, cx, cy, rx, ry, start_deg, extent_deg, width, colour = primitive
        return [("arc", (cx, cy, rx, ry, start_deg, extent_deg, max(1.0, width)), colour)]
    raise ValueError(f"不认识的图元：{kind!r}")


def _bounding_box(kind: str, params: tuple) -> Tuple[float, float, float, float]:
    if kind == "rect":
        x0, y0, x1, y1 = params[0], params[1], params[2], params[3]
        return x0, y0, x1, y1
    if kind == "ellipse":
        return params[0], params[1], params[2], params[3]
    if kind == "line":
        x0, y0, x1, y1, width = params[0], params[1], params[2], params[3], params[4]
        return x0 - width, y0 - width, x1 + width, y1 + width
    if kind == "polygon":
        points = params[0]
        xs, ys = points[0::2], points[1::2]
        return min(xs), min(ys), max(xs), max(ys)
    if kind == "arc":
        cx, cy, rx, ry, _start, _extent, width = params[:7]
        return cx - rx - width, cy - ry - width, cx + rx + width, cy + ry + width
    raise ValueError(f"不认识的图元：{kind!r}")


def _inside(kind: str, params: tuple, x: float, y: float) -> bool:
    if kind == "rect":
        x0, y0, x1, y1, radius = params
        if radius <= 0:
            return x0 <= x <= x1 and y0 <= y <= y1
        cx = (x0 + x1) / 2.0
        cy = (y0 + y1) / 2.0
        half_w = max(0.0, (x1 - x0) / 2.0 - radius)
        half_h = max(0.0, (y1 - y0) / 2.0 - radius)
        dx = abs(x - cx) - half_w
        dy = abs(y - cy) - half_h
        if dx <= 0.0 and dy <= 0.0:
            return True
        ox, oy = max(dx, 0.0), max(dy, 0.0)
        return ox * ox + oy * oy <= radius * radius
    if kind == "ellipse":
        x0, y0, x1, y1 = params
        rx, ry = (x1 - x0) / 2.0, (y1 - y0) / 2.0
        if rx <= 0 or ry <= 0:
            return False
        nx = (x - (x0 + x1) / 2.0) / rx
        ny = (y - (y0 + y1) / 2.0) / ry
        return nx * nx + ny * ny <= 1.0
    if kind == "line":
        x0, y0, x1, y1, width = params
        return _distance_to_segment(x, y, x0, y0, x1, y1) <= width / 2.0
    if kind == "polygon":
        (points,) = params
        return _point_in_polygon(x, y, points)
    if kind == "arc":
        cx, cy, rx, ry, start_deg, extent_deg, width = params
        if rx <= 0 or ry <= 0:
            return False
        nx = (x - cx) / rx
        ny = (y - cy) / ry
        ratio = width / ((rx + ry) / 2.0)
        dist = math.hypot(nx, ny)
        if not (1.0 - ratio <= dist <= 1.0):
            return False
        start, span = start_deg, extent_deg
        if span < 0:
            start += span
            span = -span
        angle = math.degrees(math.atan2(y - cy, x - cx)) % 360.0
        return ((angle - start) % 360.0) <= span
    raise ValueError(f"不认识的图元：{kind!r}")


def _point_in_polygon(x: float, y: float, points: Sequence[float]) -> bool:
    """射线法（奇偶规则）。"""
    inside = False
    count = len(points) // 2
    for index in range(count):
        x0, y0 = points[2 * index], points[2 * index + 1]
        x1, y1 = points[2 * ((index + 1) % count)], points[2 * ((index + 1) % count) + 1]
        if (y0 > y) != (y1 > y):
            cross = x0 + (y - y0) * (x1 - x0) / (y1 - y0)
            if cross > x:
                inside = not inside
    return inside


def rasterise(
    primitives: Sequence[Primitive],
    width: int,
    height: int,
    background: str | None = None,
) -> bytes:
    """把图元列表栅格化成 PNG（带抗锯齿）。

    ``background`` 为 ``None`` 时背景**透明**；给了颜色就先铺一层底色。
    像素按"图元出现顺序"依次合成，所以后面的图元画在上面。
    """
    ops: List[Tuple[str, tuple, str]] = []
    boxes: List[Tuple[float, float, float, float]] = []
    for primitive in primitives:
        for kind, params, colour in _expand(primitive):
            ops.append((kind, params, colour))
            boxes.append(_bounding_box(kind, params))

    base = parse_colour(background) if background else (0, 0, 0, 0)
    step = 1.0 / SUBSAMPLES
    total = SUBSAMPLES * SUBSAMPLES

    rows: List[bytes] = []
    for py in range(height):
        row = bytearray()
        for px in range(width):
            r, g, b, a = base
            for (kind, params, colour), (bx0, by0, bx1, by1) in zip(ops, boxes):
                # 包围盒剔除：图元离这个像素很远时直接跳过（图标有几十个图元，
                # 不剔除的话每个像素都要遍历全部图元）
                if (
                    px + 1 < bx0 - 1
                    or px > bx1 + 1
                    or py + 1 < by0 - 1
                    or py > by1 + 1
                ):
                    continue
                hits = 0
                for sy in range(SUBSAMPLES):
                    yy = py + (sy + 0.5) * step
                    for sx in range(SUBSAMPLES):
                        if _inside(kind, params, px + (sx + 0.5) * step, yy):
                            hits += 1
                if hits == 0:
                    continue
                alpha = (hits * 255) // total
                if colour == CLEAR:
                    # 擦除：把覆盖率当作"扣掉多少 alpha"，颜色保持不变
                    a = int(round(a * (1.0 - alpha / 255.0)))
                    if a <= 0:
                        r = g = b = 0
                    continue
                src_a = alpha / 255.0
                dst_a = a / 255.0
                out_a = src_a + dst_a * (1 - src_a)
                if out_a <= 0:
                    continue
                rgba = parse_colour(colour)
                r = int(round((rgba[0] * src_a + r * dst_a * (1 - src_a)) / out_a))
                g = int(round((rgba[1] * src_a + g * dst_a * (1 - src_a)) / out_a))
                b = int(round((rgba[2] * src_a + b * dst_a * (1 - src_a)) / out_a))
                a = int(round(out_a * 255))
            row.extend((r, g, b, a))
        rows.append(bytes(row))
    return write_png(width, height, rows)


#: 缓存：同一套参数只栅格化一次。
_CACHE: Dict[Tuple, bytes] = {}
_CACHE_LIMIT = 512


def _key_of(value):
    if isinstance(value, (list, tuple)):
        return tuple(_key_of(item) for item in value)
    return value


def cached_rounded_rect(
    width: int,
    height: int,
    radius: float,
    fill: str,
    outline: str = "",
    outline_width: float = 0.0,
    background: Optional[str] = None,
    supersample: int = 1,
) -> bytes:
    """带缓存的圆角矩形 PNG。"""
    key = (
        "rr", width, height, round(radius, 2), fill, outline,
        round(outline_width, 2), background, int(supersample),
    )
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    data = rounded_rect_png(
        width, height, radius, fill, outline, outline_width, background,
        supersample,
    )
    if len(_CACHE) >= _CACHE_LIMIT:
        _CACHE.clear()
    _CACHE[key] = data
    return data


def cached_circle(size: int, fill: str) -> bytes:
    """带缓存的**实心圆** PNG（抗锯齿），用于开关的圆形滑块。

    圆的抗锯齿比矩形更要紧：直径只有二十几像素时，``create_oval`` 的硬边
    会让圆看起来是个多边形。这里用覆盖率算法，边缘得到十几档半透明过渡。
    """
    key = ("circle", size, fill)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    alpha = rounded_rect_coverage(size, size, size / 2.0)
    rgba = parse_colour(fill)
    rows = []
    for py in range(size):
        row = bytearray()
        for px in range(size):
            row.extend((rgba[0], rgba[1], rgba[2], alpha[py][px]))
        rows.append(bytes(row))
    data = write_png(size, size, rows)
    if len(_CACHE) >= _CACHE_LIMIT:
        _CACHE.clear()
    _CACHE[key] = data
    return data


def cached_rasterise(
    primitives: Sequence[Primitive],
    width: int,
    height: int,
    background: str | None = None,
) -> bytes:
    """带缓存的通用栅格化。"""
    key = ("gen", _key_of(primitives), width, height, background)
    hit = _CACHE.get(key)
    if hit is not None:
        return hit
    data = rasterise(primitives, width, height, background)
    if len(_CACHE) >= _CACHE_LIMIT:
        _CACHE.clear()
    _CACHE[key] = data
    return data
