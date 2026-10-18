"""构建辅助：读写版本号、生成带提交哈希的 ``_build.py``。

**为什么单独成脚本**：`.ps1` 里嵌 Python 代码要处理两层转义
（PowerShell 的 ``\"`` 与 Python 的引号），实测第一版直接在字符集上炸了。
把这个逻辑放进 Python 文件，`.ps1` 只负责调度——**少一层转义就少一个坑**
（归档 `01` 错误八：中文引号进 PowerShell 命令，当天五次）。
"""

from __future__ import annotations

import argparse
import io
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
VERSION_PY = REPO / "src" / "gui_of_edge_tts" / "version.py"
VERSION_TXT = REPO / "version.txt"
BUILD_PY = REPO / "src" / "gui_of_edge_tts" / "_build.py"
README_ZH = REPO / "README.md"

BUILD_TEMPLATE = '''"""由 build.ps1 生成，**不要手工编辑，也不要提交**。

打包时把提交哈希写进来，产物就能自报"我是哪个提交构建的"——
用户报障时这一行决定你能不能判断他装的是哪一个（归档 02 第 26.2 ②）。
"""

COMMIT = "{commit}"
'''


def read_app_version() -> str:
    text = io.open(VERSION_PY, encoding="utf-8").read()
    match = re.search(r'APP_VERSION\s*=\s*"([^"]+)"', text)
    if not match:
        raise SystemExit(f"在 {VERSION_PY} 里找不到 APP_VERSION")
    return match.group(1)


def check() -> int:
    version = read_app_version()
    problems = []

    rc = io.open(VERSION_TXT, encoding="utf-8-sig").read()
    if f"FileVersion', '{version}'" not in rc:
        problems.append(f"version.txt 里的 FileVersion 不是 {version}")
    if f"ProductVersion', '{version}'" not in rc:
        problems.append(f"version.txt 里的 ProductVersion 不是 {version}")

    if README_ZH.exists():
        readme = io.open(README_ZH, encoding="utf-8").read()
        if f"Edge-TTS {version}+" not in readme:
            problems.append(f"README.md 的「查看版本」示例没写成 {version}")

    print(version)
    for problem in problems:
        print(f"[WARN] {problem}", file=sys.stderr)
    return 1 if problems else 0


def write_build(commit: str) -> int:
    commit = (commit or "unknown").strip()
    BUILD_PY.write_text(BUILD_TEMPLATE.format(commit=commit), encoding="utf-8", newline="\n")
    print(commit)
    return 0


def main(argv: list) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["version", "check", "write-build"])
    parser.add_argument("--commit", default="")
    args = parser.parse_args(argv)
    if args.action == "version":
        print(read_app_version())
        return 0
    if args.action == "check":
        return check()
    return write_build(args.commit)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
