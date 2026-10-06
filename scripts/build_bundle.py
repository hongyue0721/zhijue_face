#!/usr/bin/env python3
"""生成参赛源码发行包：只装“干净检出即存在”的文件，不夹带运行数据。

清单复用 doctor.tracked_files：包含未忽略的新源码，排除工作区已删除的索引路径。
本地演示产物（runtime/、dist/、.venv、node_modules）本来就被
gitignore 排除。包内附 BUNDLE_MANIFEST.json：逐文件 sha256 + 包指纹，
verify-bundle 在干净目录里据此复验。
"""

from __future__ import annotations

import hashlib
import json
import sys
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import doctor

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "dist" / "bundles"


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    files = doctor.tracked_files(ROOT)
    missing = [rel for rel in files if not (ROOT / rel).is_file()]
    if missing:
        print(f"清单中的文件缺失，拒绝出包: {missing[:5]}", file=sys.stderr)
        return 1
    generated_at = datetime.now(UTC).date().isoformat()
    manifest = {
        "generated_at": generated_at,
        "file_count": len(files),
        "files": [{"path": rel, "sha256": sha256_of(ROOT / rel)} for rel in files],
    }
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    bundle = OUT_DIR / f"zhijue-aic-source-{generated_at}.zip"
    with zipfile.ZipFile(bundle, "w", zipfile.ZIP_DEFLATED) as archive:
        for rel in files:
            archive.write(ROOT / rel, f"zhijue_face/{rel}")
        archive.writestr(
            "zhijue_face/BUNDLE_MANIFEST.json",
            json.dumps(manifest, ensure_ascii=False, indent=2),
        )
    bundle_sha = sha256_of(bundle)
    print(f"bundle={bundle}")
    print(f"sha256={bundle_sha}")
    print(f"files={len(files)}")
    (OUT_DIR / f"{bundle.name}.sha256").write_text(
        f"{bundle_sha}  {bundle.name}\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
