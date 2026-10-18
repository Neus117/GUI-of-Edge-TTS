"""开发机上的全部门禁，一次跑完。

八道检查，每道都对应**一类可查证的缺陷**，不是"跑个测试图个安心"：

| 检查 | 查的是什么缺陷 |
|---|---|
| ``add_bom.py --check`` | ``.ps1`` 少了 UTF-8 BOM ⇒ Windows PowerShell 5.1 按 GBK 解码，中文变假语法错误 |
| ``selftest`` | 参数解析 / 字幕合成 / 主题 / 设置读写这些**纯逻辑**的回归 |
| ``unittest`` | 上面那些的细化用例（含"对旧实现会失败"的阳性用例） |
| ``ui_layout_probe`` | 控件被挤出客户区、卡片与底色同色、间距离开网格 |
| ``check_forbidden.py`` | 写死的绝对路径、写死的颜色、未使用的私有方法 |
| ``e2e_smoke.py`` | **走用户真实走的那条路**（联网）；只有它能证明"程序真的会那样用" |

用法::

    python tools/check_all.py            # 全部（含联网的 e2e）
    python tools/check_all.py --offline  # 跳过联网那一项
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import List, Sequence, Tuple

REPO = Path(__file__).resolve().parent.parent
TOOLS = REPO / "tools"


def run(label: str, command: Sequence[str], cwd: Path = REPO) -> Tuple[str, int, str]:
    print(f"\n=== {label} ===")
    print("$ " + " ".join(str(part) for part in command))
    result = subprocess.run(list(command), cwd=str(cwd), capture_output=True, text=True, check=False)
    output = (result.stdout or "") + (result.stderr or "")
    tail = "\n".join(output.strip().splitlines()[-40:])
    if tail:
        print(tail)
    print(f"-> 退出码 {result.returncode}")
    return label, result.returncode, output


def main(argv: List[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offline", action="store_true", help="跳过需要联网的 e2e 冒烟")
    args = parser.parse_args(argv)

    python = sys.executable
    steps: List[Tuple[str, List[str]]] = [
        ("UTF-8 BOM 检查", [python, "-X", "utf8", str(TOOLS / "add_bom.py"), "--check"]),
        ("应用自检", [python, "-X", "utf8", str(REPO / "src" / "GUI-of-Edge-TTS.py"), "--selftest"]),
        ("单元测试", [python, "-X", "utf8", "-m", "unittest", "discover", "-s", "tests", "-t", "tests"]),
        ("禁用写法检查", [python, "-X", "utf8", str(TOOLS / "check_forbidden.py")]),
        ("禁用写法检查的自身对照", [python, "-X", "utf8", str(TOOLS / "check_forbidden.py"), "--self-test"]),
        ("版位自检的自身对照", [python, "-X", "utf8", str(TOOLS / "probe_layout_negative.py")]),
        ("占位提示与真实粘贴", [python, "-X", "utf8", str(TOOLS / "probe_paste_placeholder.py")]),
        ("全界面主题审计", [python, "-X", "utf8", str(TOOLS / "audit_theme_surfaces.py")]),
        ("中英 README 同步", [python, "-X", "utf8", str(TOOLS / "check_readmes.py")]),
    ]
    for theme in ("light", "dark"):
        steps.append(
            (
                f"界面几何与配色（{theme}）",
                [python, "-X", "utf8", str(TOOLS / "ui_layout_probe.py"), "--theme", theme, "--quiet"],
            )
        )
    if not args.offline:
        steps.append(("端到端冒烟（联网）", [python, "-X", "utf8", str(TOOLS / "e2e_smoke.py")]))

    failed = []
    for label, command in steps:
        _, code, _ = run(label, command)
        if code != 0:
            failed.append(label)

    print("\n" + "=" * 60)
    if failed:
        print(f"门禁未通过：{len(failed)} / {len(steps)} 项失败")
        for label in failed:
            print(f"  - {label}")
        return 1
    print(f"全部门禁通过（{len(steps)} 项）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
