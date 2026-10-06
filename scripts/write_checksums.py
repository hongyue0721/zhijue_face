#!/usr/bin/env python3
"""生成当前源码的 checksum；不修改 Git 索引或恢复已删除文件。"""

from pathlib import Path

import build_bundle
import doctor


def write_checksums(root: Path) -> None:
    entries = [
        f"{build_bundle.sha256_of(root / path)}  {path}\n"
        for path in doctor.tracked_files(root)
        if path != "CHECKSUMS.sha256"
    ]
    (root / "CHECKSUMS.sha256").write_text("".join(entries), encoding="utf-8")
    print(f"checksums={len(entries)}")


if __name__ == "__main__":
    write_checksums(Path(__file__).resolve().parent.parent)
