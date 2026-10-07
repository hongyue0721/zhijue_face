#!/usr/bin/env python3
"""把仓库内的岗位知识包目录打成可直接上传的 ZIP（根目录即 manifest.json）。

文件集合沿用服务端 parse_manifest 的同一套规则（缺声明文件或多出未声明文件都拒绝）；
条目按路径排序、时间戳固定，同一内容重复构建得到同一字节。产物在 gitignore 的
dist/knowledge-packs/ 下，文档引用本命令而不是链接构建产物。
打包成功只说明文件齐全，是否可导入由服务端完整校验决定，是否可出题由负责人审核决定。

用法：python scripts/build_knowledge_pack.py knowledge_packs/python_backend_junior
"""

from __future__ import annotations

import argparse
import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "services" / "api" / "src"))

from zhijue.domain.knowledge_packs import (
    PackValidationError,
    parse_manifest,
)

OUT_DIR = ROOT / "dist" / "knowledge-packs"
FIXED_ZIP_TIME = (1980, 1, 1, 0, 0, 0)


def pack_files(pack_dir: Path) -> dict[str, bytes]:
    """目录内全部文件；parse_manifest 会拒绝缺失声明文件和未声明的多余文件。"""
    return {
        path.relative_to(pack_dir).as_posix(): path.read_bytes()
        for path in sorted(pack_dir.rglob("*"))
        if path.is_file()
    }


def build(pack_dir: Path, out_dir: Path = OUT_DIR) -> Path:
    files = pack_files(pack_dir)
    manifest = parse_manifest(files)
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{manifest.pack_id}-{manifest.version}.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path, content in files.items():
            info = zipfile.ZipInfo(path, date_time=FIXED_ZIP_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, content)
    digest = hashlib.sha256(target.read_bytes()).hexdigest()
    target.with_name(target.name + ".sha256").write_text(
        f"{digest}  {target.name}\n", encoding="utf-8"
    )
    print(f"zip={target}")
    print(f"sha256={digest}")
    print(f"files={len(files)}")
    return target


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("pack_dir", type=Path, help="仓库内岗位知识包目录")
    args = parser.parse_args(argv)
    try:
        build(args.pack_dir.resolve())
    except (OSError, PackValidationError) as exc:
        print(f"打包失败：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
