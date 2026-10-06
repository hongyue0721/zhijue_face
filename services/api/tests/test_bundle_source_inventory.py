"""发行物必须反映当前源码，不恢复索引中的已删除文件或夹带运行数据。"""

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
from pathlib import Path
from zipfile import ZipFile

WORKSPACE = Path(__file__).resolve().parent.parent.parent.parent


def script_module(name):
    spec = importlib.util.spec_from_file_location(
        name, WORKSPACE / "scripts" / f"{name}.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_current_source_artifacts_respect_deletions_untracked_and_ignored_files(
    tmp_path,
    monkeypatch,
):
    (tmp_path / ".gitignore").write_text("runtime/\ndist/\n", encoding="utf-8")
    (tmp_path / "keep.txt").write_text("source retained", encoding="utf-8")
    deleted = tmp_path / "deleted.txt"
    deleted.write_text("obsolete source", encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(
        ["git", "add", ".gitignore", "keep.txt", "deleted.txt"],
        cwd=tmp_path,
        check=True,
    )
    deleted.unlink()
    (tmp_path / "题目登记.txt").write_text("new source", encoding="utf-8")
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime" / "private.txt").write_text(
        "private fixture data", encoding="utf-8"
    )
    (tmp_path / "CHECKSUMS.sha256").write_text("previous manifest", encoding="utf-8")
    monkeypatch.syspath_prepend(str(WORKSPACE / "scripts"))
    checksums = script_module("write_checksums")
    checksums.write_checksums(tmp_path)
    lines = (tmp_path / "CHECKSUMS.sha256").read_text(encoding="utf-8").splitlines()
    hashed = dict(line.split("  ", 1)[::-1] for line in lines)
    expected = {".gitignore", "keep.txt", "题目登记.txt"}
    assert set(hashed) == expected
    for path, digest in hashed.items():
        assert digest == hashlib.sha256((tmp_path / path).read_bytes()).hexdigest()
    bundle = script_module("build_bundle")
    monkeypatch.setattr(bundle, "ROOT", tmp_path)
    monkeypatch.setattr(bundle, "OUT_DIR", tmp_path / "dist")
    assert bundle.main() == 0
    archive_path = next((tmp_path / "dist").glob("*.zip"))
    with ZipFile(archive_path) as archive:
        manifest = json.loads(archive.read("zhijue_face/BUNDLE_MANIFEST.json"))
        assert {entry["path"] for entry in manifest["files"]} == expected | {
            "CHECKSUMS.sha256"
        }
        for entry in manifest["files"]:
            content = archive.read("zhijue_face/" + entry["path"])
            assert hashlib.sha256(content).hexdigest() == entry["sha256"]
        assert not any(
            name.startswith("zhijue_face/runtime/") for name in archive.namelist()
        )
    assert not deleted.exists()


def test_spec_check_in_extracted_bundle_preserves_source_integrity(
    tmp_path,
    monkeypatch,
):
    monkeypatch.syspath_prepend(str(WORKSPACE / "scripts"))
    doctor = script_module("doctor")
    source = tmp_path / "source"
    source.mkdir()
    for relative in doctor.tracked_files(WORKSPACE):
        if relative == "BUNDLE_MANIFEST.json":
            continue
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(WORKSPACE / relative, target)
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    script_module("write_checksums").write_checksums(source)
    bundle = script_module("build_bundle")
    monkeypatch.setattr(bundle, "ROOT", source)
    monkeypatch.setattr(bundle, "OUT_DIR", tmp_path / "dist")
    assert bundle.main() == 0
    extracted = tmp_path / "extracted"
    with ZipFile(next((tmp_path / "dist").glob("*.zip"))) as archive:
        archive.extractall(extracted)
    packaged_source = extracted / "zhijue_face"
    subprocess.run(
        [sys.executable, "tools/validate_spec.py"],
        cwd=packaged_source,
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["sha256sum", "-c", "CHECKSUMS.sha256"],
        cwd=packaged_source,
        capture_output=True,
        check=True,
    )
