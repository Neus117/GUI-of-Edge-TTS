"""端到端冒烟（命令行入口）：**走用户真实走的那条路**，看用户会看到的结果。

这是归档里那条最贵的教训对应的检查
（`01-反复犯的错.md` 错误一：测试走顺手的那条路，不测用户走的那条路）：

* 单元测试证明"规则对"，**不能**证明"程序会那样用它"；
* 它把文字填进**真实的 Text 控件**、选一个**真实的语音**、
  调**真实的生成入口**（只把保存对话框换成已知路径），
  然后等真实的界面事件循环把"完成"消息搬回状态栏；
* 判据是**磁盘上真的出现了 mp3 和 srt**，以及状态栏里真的写着那两个路径
  ——不是"进程还活着"。

**逻辑住在包里**（``gui_of_edge_tts._smoke``），所以打包成 exe 之后
还能用 ``--smoke`` 再跑一遍同一套判据——冻结态与源码态的环境不一样，
只有真的跑一次才知道它行不行。这个脚本只是命令行外壳。

它**会联网**（这正是重点）。用法::

    python tools/e2e_smoke.py            # 临时目录，成功即清理
    python tools/e2e_smoke.py --out DIR  # 留下产物，便于人工看

退出码 0 = 通过；1 = 失败；2 = 环境不满足（没装 edge-tts）。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "src"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default="", help="产物目录；给了就保留产物")
    parser.add_argument("--timeout", type=float, default=90.0)
    args = parser.parse_args()

    try:
        import edge_tts

        print(f"edge-tts: {edge_tts.__version__}")
    except ImportError:
        print("SKIP: 这个解释器里没有 edge-tts")
        return 2

    from gui_of_edge_tts import _smoke

    if args.out:
        output_dir = Path(args.out)
        keep = True
    else:
        import tempfile

        output_dir = Path(tempfile.mkdtemp(prefix="etts-e2e-"))
        keep = False
    output_dir.mkdir(parents=True, exist_ok=True)
    print(f"输出目录：{output_dir}")

    result = _smoke.run_smoke(output_dir, timeout=args.timeout)
    print()
    print(result.report())
    if result.ok and not keep:
        for name in ("smoke.mp3", "smoke.srt"):
            try:
                (output_dir / name).unlink()
            except OSError:
                pass
        # 产物删完，空目录也要一并收掉：不然每跑一次门禁就在 %TEMP% 里
        # 留一个 `etts-e2e-*`，和文件头那句"成功即清理"不符。
        try:
            output_dir.rmdir()
        except OSError:
            pass
        print("产物已清理（成功时不留临时文件）")
    else:
        print(f"产物留在：{output_dir}")
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
