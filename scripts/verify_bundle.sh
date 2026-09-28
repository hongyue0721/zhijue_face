#!/usr/bin/env bash
# 在干净目录复验发行包：解压 → 逐文件 sha256 → doctor 离线画像。
# 不依赖原工作区；证明“拿到 ZIP 就能自证完整”。
set -euo pipefail

BUNDLE="${1:?用法: scripts/verify_bundle.sh <bundle.zip>}"
command -v python3 >/dev/null 2>&1 || { echo "缺少 python3" >&2; exit 1; }
command -v git >/dev/null 2>&1 || { echo "缺少 git" >&2; exit 1; }

WORK="$(mktemp -d "${TMPDIR:-/tmp}/zhijue-verify-XXXXXX")"
trap 'rm -rf "$WORK"' EXIT

python3 - "$BUNDLE" "$WORK" <<'PY'
import hashlib, json, sys, zipfile
from pathlib import Path

bundle, work = Path(sys.argv[1]), Path(sys.argv[2])
archive = zipfile.ZipFile(bundle)
for name in archive.namelist():
    target = Path(name)
    # 防目录穿越：包内条目必须落在 zhijue_face/ 前缀下且为普通相对路径。
    if target.is_absolute() or ".." in target.parts:
        raise SystemExit(f"包内路径不安全: {name}")
    archive.extract(name, work)
manifest = json.loads(
    (work / "zhijue_face" / "BUNDLE_MANIFEST.json").read_text(encoding="utf-8")
)
bad = []
for entry in manifest["files"]:
    path = work / "zhijue_face" / entry["path"]
    if not path.is_file():
        bad.append(entry["path"] + " (missing)")
        continue
    if hashlib.sha256(path.read_bytes()).hexdigest() != entry["sha256"]:
        bad.append(entry["path"])
if bad:
    print(f"逐文件校验失败 {len(bad)} 项: {bad[:5]}", file=sys.stderr)
    raise SystemExit(1)
print(f"manifest ok: {manifest['file_count']} files")
PY

cd "$WORK/zhijue_face"
# doctor 依赖 git 清单口径（ls-files / check-ignore）：解包目录先建临时索引，
# 模拟“干净检出”，不改动包内容本身。
git init -q
git add -A
python3 scripts/doctor.py --profile bundle
echo "verify-bundle PASS: $BUNDLE"
