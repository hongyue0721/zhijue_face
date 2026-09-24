"""重算 `config/prompts/**` 的 hash 并写回 `config/experiment.yaml`。

Prompt 版本一经登记，正文改动必须新建版本号；本脚本只用于**首次登记**或
显式的新版本收口，避免手抄 hash 抄错。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

RESEARCH_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(RESEARCH_ROOT / "src"))

import yaml

from zhijue_research.prompts import compute_prompt_hashes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config", type=Path, default=RESEARCH_ROOT / "config/experiment.yaml"
    )
    parser.add_argument(
        "--prompts", type=Path, default=RESEARCH_ROOT / "config/prompts"
    )
    parser.add_argument("--check", action="store_true", help="只比对，不写回")
    args = parser.parse_args()

    document = yaml.safe_load(args.config.read_text(encoding="utf-8"))
    computed = compute_prompt_hashes(args.prompts)
    registered = document.get("prompt_hashes") or {}
    if args.check:
        if registered != computed:
            print("prompt_hashes 与正文不一致：")
            print("  registered:", registered)
            print("  computed  :", computed)
            return 1
        print(f"prompt_hashes 一致（{sum(len(v) for v in computed.values())} 个版本）")
        return 0

    document["prompt_hashes"] = computed
    args.config.write_text(
        yaml.safe_dump(document, allow_unicode=True, sort_keys=False, width=100),
        encoding="utf-8",
    )
    print(f"已登记 {sum(len(v) for v in computed.values())} 个 prompt 版本 hash")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
