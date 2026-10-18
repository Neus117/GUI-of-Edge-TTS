"""中英两份 README 的同步检查。

**翻译版不是"另一份 README"，是同一份的另一种语言。** 节数、顺序、表格的
列数与行数都要对齐——否则改了一版忘了另一版，两份就会开始说不同的话。

判据是**结构**而不是文字：

* 两边的标题层级与顺序逐一对应；
* 每个小节里表格的**列数**一致，行数允许出现差异（英文更啰嗦是正常的，
  但差得太多就说明有一边漏了内容）；
* 两边的相对链接（不含锚点的那些）指向的路径集合必须存在；
* 两份都必须**从本地相对路径**引用截图，不能写 `raw.githubusercontent.com`——
  那样一旦图片改名，README 也不会在本地检查里暴露出来。

用法::

    python tools/check_readmes.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent
PAIR = {"中文": REPO / "README.md", "English": REPO / "README.en.md"}

# 允许的行数差（英文说明通常更长，表格行数完全一致反而不正常）
ROW_TOLERANCE = 3


def headings(text: str) -> List[Tuple[int, str]]:
    found = []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        match = re.match(r"^(#{1,6})\s+(.*)$", line)
        if match:
            found.append((len(match.group(1)), match.group(2).strip()))
    return found


def tables(text: str) -> List[List[int]]:
    """每个表格的 (列数, 数据行数)。表格以空行分段。"""
    found: List[List[int]] = []
    current: List[str] = []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            current = []
            continue
        if in_fence:
            continue
        if line.lstrip().startswith("|"):
            current.append(line)
            continue
        if current:
            found.append(_table_shape(current))
            current = []
    if current:
        found.append(_table_shape(current))
    return found


def _table_shape(rows: List[str]) -> List[int]:
    columns = max(len([c for c in row.strip().strip("|").split("|")]) for row in rows)
    data_rows = max(0, len(rows) - 2)  # 去掉表头与分隔行
    return [columns, data_rows]


def links(text: str) -> List[str]:
    found = []
    in_fence = False
    for line in text.splitlines():
        if line.strip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        found += re.findall(r"!?\[[^\]]*\]\(([^)]+)\)", line)
    return found


def main() -> int:
    problems: List[str] = []
    docs: Dict[str, str] = {}
    for label, path in PAIR.items():
        if not path.exists():
            problems.append(f"{label}: 找不到 {path.name}")
            continue
        docs[label] = path.read_text(encoding="utf-8")

    if len(docs) != 2:
        for problem in problems:
            print(f"[FAIL] {problem}")
        return 1

    labels = list(docs)
    left_heads = headings(docs[labels[0]])
    right_heads = headings(docs[labels[1]])

    if len(left_heads) != len(right_heads):
        problems.append(
            f"标题数量不同：{labels[0]} {len(left_heads)} 个，{labels[1]} {len(right_heads)} 个"
        )
    for index, (left, right) in enumerate(zip(left_heads, right_heads), start=1):
        if left[0] != right[0]:
            problems.append(
                f"第 {index} 个标题层级不同：{labels[0]} H{left[0]}「{left[1]}」"
                f" vs {labels[1]} H{right[0]}「{right[1]}」"
            )
    if left_heads and right_heads:
        print(f"标题：{len(left_heads)} 个，两边层级与顺序一致"
              if len(left_heads) == len(right_heads) else "标题：数量不一致（见下）")

    left_tables = tables(docs[labels[0]])
    right_tables = tables(docs[labels[1]])
    if len(left_tables) != len(right_tables):
        problems.append(
            f"表格数量不同：{labels[0]} {len(left_tables)} 个，{labels[1]} {len(right_tables)} 个"
        )
    for index, (left, right) in enumerate(zip(left_tables, right_tables), start=1):
        if left[0] != right[0]:
            problems.append(f"第 {index} 个表格列数不同：{left[0]} vs {right[0]}")
        if abs(left[1] - right[1]) > ROW_TOLERANCE:
            problems.append(
                f"第 {index} 个表格行数差得太多：{left[1]} vs {right[1]}（容差 {ROW_TOLERANCE}）"
            )
    print(f"表格：{len(left_tables)} 个，列数一致" if left_tables == right_tables or not problems else "表格：见下")

    for label, text in docs.items():
        for target in links(text):
            if target.startswith(("http://", "https://", "mailto:", "#")):
                if "raw.githubusercontent.com" in target:
                    problems.append(
                        f"{label}: 截图用了 raw.githubusercontent.com（{target}）——"
                        "请改成仓库内相对路径，否则本地检查发现不了图片缺失"
                    )
                continue
            resolved = (REPO / target.split("#")[0]).resolve()
            if not resolved.exists():
                problems.append(f"{label}: 链接指向的文件不存在 {target}")

    if problems:
        print(f"\n发现 {len(problems)} 个不同步的地方：")
        for problem in problems:
            print("  " + problem)
        return 1
    print("\n两份 README 结构一致，链接都指向存在的文件")
    return 0


if __name__ == "__main__":
    sys.exit(main())
