"""测试的公共装配：把 ``src`` 放进 ``sys.path``。

**不用 pytest 专属特性**，所以 ``python -m unittest discover -s tests`` 和
``pytest`` 都能跑——不强制贡献者装额外的包。
"""

from __future__ import annotations

import os
import sys

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "src")
if SRC not in sys.path:
    sys.path.insert(0, SRC)

REPO_ROOT = os.path.dirname(SRC)
IMAGES = os.path.join(REPO_ROOT, "images")
# 测试默认中文：语言检测会看系统，CI 机器/贡献者系统未必是中文。
# 语言本身的切换由 test_lang.py 显式验证。
os.environ.setdefault("ETTS_LANG", "zh")

__all__ = ["SRC", "REPO_ROOT", "IMAGES"]
