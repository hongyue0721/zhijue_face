"""确定性 evaluator 的判定产物：一条可解释的漂移记录。

`Finding` 只描述"从输入文本与证据推出的结论"：
- `snippet` 是让读者一眼定位的原文片段；
- `detail` 必须写清判定口径（比较了什么、豁免了什么），禁止只给结论；
- `source_ids` 只填能确证的证据来源；拿不到就留空元组，不猜。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from zhijue_research.taxonomy import DriftLabel


@dataclass(frozen=True, slots=True)
class Finding:
    """一次漂移判定：label + 检测器 + 原文片段 + 依据 + 可回查来源。"""

    label: DriftLabel
    detector_id: str
    snippet: str
    detail: str
    source_ids: tuple[str, ...]
    deterministic: bool

    def as_dict(self) -> dict[str, Any]:
        """JSON 友好形态：label 输出为 str 值，source_ids 输出为 list。"""

        return {
            "label": self.label.value,
            "detector_id": self.detector_id,
            "snippet": self.snippet,
            "detail": self.detail,
            "source_ids": list(self.source_ids),
            "deterministic": self.deterministic,
        }
