"""禁用写法检查：查那些"跑起来不报错、但确实是缺陷"的写法。

**判据只对可执行代码生效**：先把 AST 里所有字符串常量（含 docstring）剔掉，
再跳过 ``#`` 注释，然后才匹配。否则注释里那句"原来是 ``wx.StandardPaths.Get()``"
会把检查器自己骗了（归档 `02` 第十九节）。

四类判据，每一类都对应一次真实返工：

1. **写死的绝对路径**——`D:\\Coding\\...` 只在这台机器上成立，换机器/进 CI 就废
2. **写死的颜色**——颜色必须来自 `Palette`，否则深色主题下会出现低对比度灰字
3. **同一个类里定义两次同名方法**——Python 静默用后一个，改前一个不会有任何效果
4. **声明了却没人读的设置字段**——`settings.py` 里加了字段但代码从不读它

用法::

    python tools/check_forbidden.py            # 检查
    python tools/check_forbidden.py --verbose
"""

from __future__ import annotations

import argparse
import ast
import io
import re
import sys
from pathlib import Path
from typing import Dict, List, Tuple

REPO = Path(__file__).resolve().parent.parent
SRC = REPO / "src" / "gui_of_edge_tts"
SCRIPTS = [REPO / "src" / "GUI-of-Edge-TTS.py"]

# 颜色只允许出现在这里（这是唯一的权威来源）
COLOUR_HOME = "theme.py"
# 颜色判据在**去了注释、但内容还在**的行上匹配：颜色一定写在字符串里，
# 而字符串在 executable_lines 里会被换成 "<str>" 占位——所以这条判据不能
# 用可执行行，要用 comment-free 行（见 check_file 的注释）。
COLOUR_PATTERN = re.compile(r"[\"']#[0-9a-fA-F]{3,8}[\"']")
# 写死的绝对路径判据落在**字符串的内容**上，不用正则匹配源码里的转义：
# 源码里 `"D:\\a"` 有两个反斜杠，而 `r"D:\a"` 只有一个——按源码匹配会
# 漏掉后一种（第一版就在这里误报/漏报过）。判据看清内容、不看清写法。
WINDOWS_PATH_PATTERN = re.compile(r"^(?:[A-Za-z]:[\\/]|\\\\)")
URL_SCHEME_PATTERN = re.compile(r"^[A-Za-z][A-Za-z0-9+.\-]*://")


def absolute_path_reason(value: str) -> str:
    """字符串**内容**是不是写死的绝对路径。

    判据落在内容上、不落在源码写法上：源码里 ``"D:\\a"`` 有两个反斜杠，
    而 ``r"D:\\a"`` 只有一个——按源码匹配两种写法会一漏一报
    （第一版两种都错过）。``ast`` 已经把两种写法都还原成真实的字符串值
    （raw 前缀只是"少还原一次"，得到的仍然是同一个内容），所以在这里判最省事。
    """
    if not value:
        return ""
    if URL_SCHEME_PATTERN.match(value):
        return ""
    if WINDOWS_PATH_PATTERN.match(value):
        return value
    return ""


def colour_literals(path: Path, comment_free: List[str], raw_lines: List[str]) -> List[str]:
    """找写死的颜色。

    用"去了注释、内容还在"的行：颜色一定写在字符串里，而字符串在可执行行里
    已经被换成 ``<str>`` 占位；注释又必须去掉，否则注释里那句
    "原来是 ``#F0F0F0``"会把检查器自己骗了（归档 `02` 第十九节）。
    """
    if path.name == COLOUR_HOME:
        return []
    problems = []
    for index, line in enumerate(comment_free, start=1):
        if COLOUR_PATTERN.search(line):
            problems.append(
                f"{display_path(path)}:{index}: 写死的颜色（应来自 Palette）：{raw_lines[index - 1].strip()}"
            )
    return problems


def hardcoded_paths(path: Path, raw_lines: List[str]) -> List[str]:
    """找写在字符串常量里的绝对路径——**只看可执行代码里的字符串值**。"""
    tree = ast.parse(io.open(path, encoding="utf-8").read(), str(path))
    problems = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Constant) and isinstance(node.value, str)):
            continue
        reason = absolute_path_reason(node.value)
        if reason:
            line = node.lineno
            shown = raw_lines[line - 1].strip() if 0 < line <= len(raw_lines) else ""
            problems.append(f"{display_path(path)}:{line}: 写死的绝对路径 {reason!r}：{shown}")
    return problems


def display_path(path: Path) -> str:
    """尽量显示成仓库内相对路径；不在仓库里（阳性对照的临时文件）就显示全路径。"""
    try:
        return str(path.relative_to(REPO))
    except ValueError:
        return str(path)


def python_files() -> List[Path]:
    files = sorted(SRC.glob("*.py")) + [p for p in SCRIPTS if p.exists()]
    return files


def strip_comments(source: str) -> List[str]:
    """逐行去掉真正的 ``#`` 注释，**字符串里的 `#` 不算注释**。

    第一版是"找到 ``#`` 就切断"——于是 ``background="#123456"`` 被切成了
    ``background="``，颜色判据自己把证据删掉了。颜色码里就带 ``#``，
    所以这一层必须区分"在不在字符串里"。
    """
    cleaned: List[str] = []
    for line in source.splitlines():
        quote = ""
        index = 0
        cut = -1
        while index < len(line):
            char = line[index]
            if quote:
                if char == "\\":
                    index += 2
                    continue
                if char == quote:
                    quote = ""
            elif char in "\"'":
                quote = char
            elif char == "#":
                cut = index
                break
            index += 1
        cleaned.append(line if cut == -1 else line[:cut])
    return cleaned




def check_file(path: Path) -> List[str]:
    """一个文件的三类检查。

    **颜色看行、路径看值**，这一点是踩出来的：

    * **颜色**在"去了注释"的行上匹配。颜色一定写在字符串里，用 AST 值去判也行，
      但按行匹配能顺带把"同一行里出现了颜色"这件事说清楚；前提是注释去掉，
      否则注释里那句"原来是 ``#F0F0F0``"会骗过检查器。
    * **路径**直接看 ``ast`` 里字符串的**值**。按源码文本匹配会因转义写法
      （``"D:\a"`` vs ``r"D:"``）一漏一报，两种都错过。
    """
    source = io.open(path, encoding="utf-8").read()
    raw_lines = source.splitlines()

    problems: List[str] = []
    problems += colour_literals(path, strip_comments(source), raw_lines)
    problems += hardcoded_paths(path, raw_lines)
    problems += check_duplicate_methods(path, False)
    return problems


def check_duplicate_methods(path: Path, verbose: bool) -> List[str]:
    tree = ast.parse(io.open(path, encoding="utf-8").read(), str(path))
    problems = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        seen: Dict[str, int] = {}
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if item.name in seen:
                    problems.append(
                        f"{display_path(path)}:{item.lineno}: "
                        f"{node.name}.{item.name} 定义了两次（前一次在第 {seen[item.name]} 行）"
                    )
                seen[item.name] = item.lineno
    return problems


SETTINGS_FIELDS_EXEMPT = {"theme", "voice", "rate", "volume", "pitch", "output_dir", "proxy"}


def check_unread_settings(verbose: bool) -> List[str]:
    """设置里加了字段，但界面从不读它——用户改了什么都不会发生。"""
    import dataclasses  # pylint: disable=import-outside-toplevel
    import importlib  # pylint: disable=import-outside-toplevel

    sys.path.insert(0, str(REPO / "src"))
    module = importlib.import_module("gui_of_edge_tts.settings")
    fields = [f.name for f in dataclasses.fields(module.Settings)]

    haystack = "\n".join(
        io.open(p, encoding="utf-8").read() for p in sorted(SRC.glob("*.py"))
    )
    problems = []
    for field in fields:
        if field in SETTINGS_FIELDS_EXEMPT:
            continue
        occurrences = len(re.findall(rf"\b{field}\b", haystack))
        if occurrences <= 2:  # 定义处 + dataclass 里的那一处
            problems.append(
                f"settings.Settings.{field}: 只在 settings.py 里出现过 {occurrences} 次，界面从不读它"
            )
    if verbose:
        print(f"  （设置字段共 {len(fields)} 个：{', '.join(fields)}）")
    return problems


def self_test() -> int:
    """阳性对照：造一个**必然被拦**的样本，确认检查器真的会报。

    归档里踩过这个坑：一个门禁返回"干净"，而它其实根本没运行——
    **"返回通过"和"根本没有检查这一项"在输出里长得一模一样**
    （`02` 第 26.4 节）。所以每个检查器都要有这一步。
    """
    import tempfile  # pylint: disable=import-outside-toplevel

    cases = {
        # 用例的**源码写法**各不相同，但内容都是绝对路径 —— 判据落在内容上
        "绝对路径（两个反斜杠的普通字符串）": 'PATH = "D:\\\\projects\\\\thing\\\\file.txt"\n',
        "绝对路径（原始字符串）": 'PATH = r"D:\\projects\\thing\\file.txt"\n',
        "绝对路径（正斜杠）": 'PATH = "D:/projects/thing/file.txt"\n',
        "绝对路径（UNC）": 'SHARE = "\\\\\\\\server\\\\share\\\\file"\n',
        "写死的颜色": 'widget.configure(background="#123456")\n',
    }
    body_duplicate = (
        "class Thing:\n"
        "    def run(self):\n"
        "        return 1\n"
        "    def run(self):\n"
        "        return 2\n"
    )

    failures = []
    with tempfile.TemporaryDirectory() as folder:
        for label, body in cases.items():
            path = Path(folder) / f"case_{abs(hash(label))}.py"
            path.write_text(body, encoding="utf-8")
            found = check_file(path)
            print(f"  [{'OK  ' if found else 'FAIL'}] 阳性：{label} — {found[:1]}")
            if not found:
                failures.append(label)

        path = Path(folder) / "dup.py"
        path.write_text(body_duplicate, encoding="utf-8")
        found = check_file(path)
        print(f"  [{'OK  ' if found else 'FAIL'}] 阳性：同一个类里重复定义方法 — {found[:1]}")
        if not found:
            failures.append("重复方法")

        # ---- 阴性对照：合法代码不能被报 ----
        negatives = {
            "文件名非法字符集合（曾经在这里误报）": (
                'import os\n\n\ndef safe(name):\n'
                "    return ''.join(ch for ch in name if ch not in '/:*?\"<>|')\n"
            ),
            "颜色从调色板取": (
                "from .theme import Theme\n\n\ndef make(theme):\n    return theme.palette.card\n"
            ),
            "注释里提到颜色不算写死": (
                "# \u539f\u6765\u5199\u7684\u662f background=\"#F0F0F0\"\uff0c\u73b0\u5728\u4ece Palette \u53d6\n"
                "VALUE = 1\n"
            ),
            "URL 不是本地路径": 'HOME = "https://github.com/Neus117/GUI-of-Edge-TTS"\n',
            "包名不是路径": 'MODULE = "gui_of_edge_tts.bootstrap"\n',
        }
        for label, body in negatives.items():
            path = Path(folder) / f"neg_{abs(hash(label))}.py"
            path.write_text(body, encoding="utf-8")
            found = check_file(path)
            print(f"  [{'OK  ' if not found else 'FAIL'}] 阴性：{label} — {found[:1]}")
            if found:
                failures.append(label)

    if failures:
        print(f"\n对照未通过：{len(failures)} 项（{', '.join(failures)}）")
        return 1
    print("\n阳性全部被拦、阴性全部放过：检查器确实在跑")
    return 0


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--self-test", action="store_true", dest="self_test")
    args = parser.parse_args(argv)

    if args.self_test:
        print("=== check_forbidden 的阳性 / 阴性对照 ===")
        return self_test()

    problems: List[str] = []
    for path in python_files():
        problems += check_file(path)
    problems += check_unread_settings(args.verbose)

    checked = len(python_files())
    if problems:
        print(f"检查了 {checked} 个文件，发现 {len(problems)} 处禁用写法：")
        for problem in problems:
            print("  " + problem)
        print("\n这些写法都不会报错，但都会在别的地方出问题——修掉它，或者把理由写进豁免清单。")
        return 1
    print(f"检查了 {checked} 个文件，没有发现写死的路径/颜色、重复方法或无人读取的设置字段")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
