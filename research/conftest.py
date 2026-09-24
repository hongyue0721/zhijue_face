"""研究测试的唯一路径入口：把研究包与业务包一起挂上 sys.path。

研究代码允许 import 业务模块（复用同一 transport / validator / 知识网关），
但业务模块永不 import 研究模块，保证依赖方向单向。
"""

from __future__ import annotations

import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parent
REPO_ROOT = RESEARCH_ROOT.parent

for path in (RESEARCH_ROOT / "src", REPO_ROOT / "services" / "api" / "src"):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))
