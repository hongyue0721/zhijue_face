"""Rebuild the repository integrity manifest exactly as doctor validates it.

口径与 `scripts/doctor.py::check_lock_integrity` 一致：tracked index + 未被 ignore 的
工作区文件，排除 `CHECKSUMS.sha256` 自身。
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANIFEST = ROOT / "CHECKSUMS.sha256"


def tracked_paths() -> list[str]:
    out = subprocess.run(
        ["git", "-c", "core.quotePath=false", "ls-files", "-c", "-o", "--exclude-standard"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return sorted(p for p in out.splitlines() if p and p != MANIFEST.name)


def main() -> None:
    lines: list[str] = []
    for rel in tracked_paths():
        target = ROOT / rel
        if not target.is_file():
            raise SystemExit(f"manifest source missing: {rel}")
        digest = hashlib.sha256(target.read_bytes()).hexdigest()
        lines.append(f"{digest}  {rel}")
    MANIFEST.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"CHECKSUMS.sha256 rebuilt: {len(lines)} entries")


if __name__ == "__main__":
    main()
