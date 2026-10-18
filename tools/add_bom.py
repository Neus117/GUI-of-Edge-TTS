"""给 ``.ps1`` 补 UTF-8 BOM（或检查它们是否带 BOM）。

**为什么需要这个**：本机只有 Windows PowerShell 5.1，它读**没有 BOM** 的
UTF-8 脚本时按 GBK 解码，中文变乱码、``}`` 被吃掉，脚本报出一堆假语法错误。
归档里有一次一个 PS 写的检查器因此把 78 处正常代码报成死代码
（见 `projects/File-tracker.md` 第九节）。

用法::

    python tools/add_bom.py            # 补 BOM
    python tools/add_bom.py --check    # 只检查，缺一个就退出码 2
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import List

BOM = b"\xef\xbb\xbf"
REPO_ROOT = Path(__file__).resolve().parent.parent
SKIP_DIRS = {".git", "build", "dist", "__pycache__", "etts-dev", "edge-tts-env"}


def script_files() -> List[Path]:
    found = []
    for path in REPO_ROOT.rglob("*.ps1"):
        if any(part in SKIP_DIRS for part in path.parts):
            continue
        found.append(path)
    return sorted(found)


def main(argv: List[str]) -> int:
    check_only = "--check" in argv
    files = script_files()
    if not files:
        print("没有找到 .ps1 文件")
        return 0

    missing = []
    for path in files:
        raw = path.read_bytes()
        if raw.startswith(BOM):
            continue
        missing.append(path)
        if check_only:
            print(f"[FAIL] 缺少 BOM：{path.relative_to(REPO_ROOT)}")
            continue
        path.write_bytes(BOM + raw)
        print(f"[OK  ] 已补 BOM：{path.relative_to(REPO_ROOT)}")

    if check_only:
        if missing:
            print(f"\n{len(missing)} 个 .ps1 缺少 UTF-8 BOM。运行 python tools/add_bom.py 修好。")
            return 2
        print(f"全部 {len(files)} 个 .ps1 都带 BOM")
        return 0

    print(f"检查了 {len(files)} 个 .ps1，补了 {len(missing)} 个")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
