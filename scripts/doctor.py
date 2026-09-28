#!/usr/bin/env python3
"""M0-04 doctor：只读就绪检查，按四档 profile 划分业务事实。

profile 语义（互不锁死）：
  bundle    源码发行物自检：清单完整性 + 密钥扫描 + 配置存在性；不假设
            解包目录已安装 Python 依赖或 node/pnpm 工具链。
  offline   干净源码/依赖完整性 + 密钥扫描 + 锁校验。缺私密 env、缺
            node/pnpm 只 WARN：离线开发回归不依赖它们，不算业务失败。
  toolchain 在 offline 之上要求 node/pnpm 实测可用且与实测锁一致，
            否则 FAIL；仍不要求私密 env。
  live      在 toolchain 之上要求 .env.local 存在、权限 ≤0600、
            被 Git 忽略且必需键名齐备，缺失即 FAIL（live not_ready）。

绝不联网、绝不打印任何密钥值或文件正文，只输出变量名、状态与可复核计数。
toolchain/ 目录只是开发者本机声明，不作为所有机器的必要条件；
实际工具版本一律重测，不信任声明文件。

运行方式（必须使用项目锁定 venv）：
    services/api/.venv/bin/python scripts/doctor.py [--json] [--profile bundle|offline|toolchain|live]

退出码：0 = 无 FAIL（允许 WARN）；1 = 存在 FAIL；2 = doctor 自身无法完成检查。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
from importlib.metadata import PackageNotFoundError, distribution, version
from pathlib import Path

PASS, WARN, FAIL = "PASS", "WARN", "FAIL"

# 私密权限要求：owner-only。
SECRET_FILE_MAX_MODE = 0o600
PRIVATE_DIR_MAX_MODE = 0o700

# 四档检查 profile；默认 offline 供 CI 与干净工作区使用。
# bundle 只验源码发行物自身的完整性（清单/密钥/配置存在性），不假设解包
# 目录已安装依赖或工具链——那是 `make setup` 之后的 offline 档职责。
PROFILES = ("bundle", "offline", "toolchain", "live")
DEFAULT_PROFILE = "offline"

# 实测版本与 PATH 工具都不匹配时的强校验档位；offline 只 WARN。
STRICT_TOOLCHAIN_PROFILES = ("toolchain", "live")

# .env.local 必须出现的键名（只查名字，绝不读取/输出值）。
REQUIRED_ENV_KEYS = (
    "EMBEDDING_PROVIDER",
    "EMBEDDING_MODEL",
    "EMBEDDING_API_BASE",
    "EMBEDDING_API_KEY",
)

# Git 跟踪文件密钥扫描。命中只报告 文件+规则名+行号，不输出内容。
# _SEP = 可选的引号/空白分隔符（' " 空格），在原始串字面量里直接写引号会截断字符串。
_SEP = r"""["' ]*"""
SECRET_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("openai-style-sk", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("aws-access-key", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("jwt-like", re.compile(r"\beyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}")),
    (
        "assigned-secret",
        # 下划线连接名（APP_PASSWORD、EMBEDDING_API_KEY）没有词边界，故允许词内前后缀。
        re.compile(
            r"(?i)\w*(?:api[_-]?key|secret|access[_-]?token|auth[_-]?token|"
            r"password|passwd)\w*" + _SEP + r"[=:]" + _SEP + r"[A-Za-z0-9+/_=-]{24,}"
        ),
    ),
)
# 纯 hex（sha256 等完整性清单）与 base64 长行的字段名不是密钥，避免误报。
HEX_ONLY = re.compile(r"^[0-9a-fA-F]{32,}$")
ALLOWED_NAME_HINTS = ("sha256", "checksum", "hash")

TRACKED_SCAN_MAX_BYTES = 2_000_000


class Report:
    """Collect check results without ever storing secret values."""

    def __init__(self) -> None:
        self.items: list[dict[str, str]] = []

    def add(self, check: str, status: str, detail: str) -> None:
        self.items.append({"check": check, "status": status, "detail": detail})

    def counts(self) -> dict[str, int]:
        out = {PASS: 0, WARN: 0, FAIL: 0}
        for item in self.items:
            out[item["status"]] += 1
        return out

    @property
    def failed(self) -> bool:
        return any(i["status"] == FAIL for i in self.items)


def workspace_root() -> Path:
    return Path(__file__).resolve().parent.parent


def load_version_lock(root: Path) -> dict:
    path = root / "config" / "versions.lock.json"
    if not path.is_file():
        raise FileNotFoundError("config/versions.lock.json 缺失")
    return json.loads(path.read_text(encoding="utf-8"))


def check_platform(report: Report, root: Path) -> None:  # root 预留：与其余检查签名一致
    system, machine = platform.system(), platform.machine()
    if system != "Linux":
        report.add("os", FAIL, f"目标为 Linux 单机 Demo，当前 {system}")
    elif machine not in {"x86_64", "aarch64"}:
        report.add("os", WARN, f"未实测架构 {machine}；可运行但需登记兼容性证据")
    else:
        report.add("os", PASS, f"Linux {machine}")


def check_python(report: Report, lock: dict) -> None:
    current = sys.version_info
    allowed = lock["python"]["requires"]
    ok = current >= (3, 11) and current < (3, 14)
    detail = f"运行 Python {platform.python_version()}（要求 {allowed}）"
    if not ok:
        report.add("python", FAIL, detail)
    elif f"{current.major}.{current.minor}" != lock["python"]["measured"][:4]:
        report.add("python", WARN, detail + "，与实测锁 minor 不同，未经验证")
    else:
        report.add("python", PASS, detail)


def check_package_versions(report: Report, lock: dict) -> None:
    for name, expected in (
        ("pymilvus", lock["pymilvus"]),
        ("milvus-lite", lock["milvus_lite"]),
    ):
        try:
            actual = version(name)
        except PackageNotFoundError:
            report.add(
                f"pkg:{name}", FAIL, "未安装，请在 services/api 锁定 venv 内运行"
            )
            continue
        status = PASS if actual == expected else WARN
        report.add(
            f"pkg:{name}",
            status,
            f"安装 {actual}，实测锁 {expected}"
            + ("" if status == PASS else "（版本漂移）"),
        )


def check_openjiuwen_source(report: Report, lock: dict) -> None:
    want = lock["openjiuwen"]
    try:
        actual_version = version("openjiuwen")
        dist = distribution("openjiuwen")
    except PackageNotFoundError:
        report.add("openjiuwen", FAIL, "未安装")
        return
    if actual_version != want["version"]:
        report.add("openjiuwen", FAIL, f"版本 {actual_version} != 锁 {want['version']}")
        return
    direct_url_text = dist.read_text("direct_url.json")
    if direct_url_text is None:
        report.add(
            "openjiuwen:source",
            WARN,
            "无 direct_url（可能来自系统路径）；无法证明兼容 commit",
        )
        return
    direct_url = json.loads(direct_url_text)
    commit = (direct_url.get("vcs_info") or {}).get("commit_id", "")
    url = direct_url.get("url", "")
    if url == want["repository"] and commit == want["commit"]:
        report.add("openjiuwen:source", PASS, f"commit {commit[:12]} == 实测锁")
    else:
        report.add(
            "openjiuwen:source",
            FAIL,
            f"来源漂移：url={url.split('/')[-1]} commit={commit[:12]}，"
            f"期望 {want['repository'].split('/')[-1]} {want['commit'][:12]}",
        )


def check_config_files(report: Report, root: Path) -> None:
    for rel in ("config/demo.yaml", "config/environment.env.example", "api.md"):
        path = root / rel
        if path.is_file() and path.stat().st_size > 0:
            report.add(f"file:{rel}", PASS, "存在且非空")
        else:
            report.add(f"file:{rel}", FAIL, "缺失或为空")
    compat = None
    try:
        import yaml  # 锁定 venv 内已有 PyYAML

        demo = yaml.safe_load(
            (root / "config" / "demo.yaml").read_text(encoding="utf-8")
        )
        compat = (demo.get("retrieval") or {}).get("openjiuwen_compat_commit")
    except ModuleNotFoundError:
        report.add("config:demo.yaml", WARN, "yaml 不可用，跳过兼容 commit 交叉核对")
    if compat is not None:
        lock_commit = load_version_lock(root)["openjiuwen"]["commit"]
        status = PASS if compat == lock_commit else FAIL
        report.add(
            "config:compat-commit",
            status,
            "demo.yaml 与 versions.lock.json 的兼容 commit 一致"
            if status == PASS
            else "demo.yaml 与 versions.lock.json 兼容 commit 不一致",
        )


def read_env_names(path: Path) -> set[str]:
    """只返回键名；任何值都不离开本函数的局部变量。"""
    names: set[str] = set()
    for line in path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"^([A-Z][A-Z0-9_]*)=", line.strip())
        if match:
            names.add(match.group(1))
    return names


def check_private_env(
    report: Report, root: Path, profile: str = DEFAULT_PROFILE
) -> None:
    env_file = root / ".env.local"
    if not env_file.is_file():
        status = FAIL if profile == "live" else WARN
        report.add(
            "secret:env.local",
            status,
            ".env.local 不存在"
            + (
                "：live readiness = not_ready"
                if profile == "live"
                else "：offline/toolchain 检查不依赖私密 env；live 档将判 not_ready"
            ),
        )
        return
    mode = stat.S_IMODE(env_file.stat().st_mode)
    if mode & ~SECRET_FILE_MAX_MODE:
        report.add("secret:env.mode", FAIL, f".env.local 权限 {oct(mode)}，要求 ≤0600")
    else:
        report.add("secret:env.mode", PASS, f".env.local 权限 {oct(mode)}")
    ignored = subprocess.run(
        ["git", "check-ignore", "-q", ".env.local"],
        cwd=root,
        capture_output=True,
        check=False,  # 返回码非 0 = 未被忽略，本身是业务事实
    )
    if ignored.returncode != 0:
        report.add("secret:env.ignored", FAIL, ".env.local 未被 Git 忽略，可能入库")
    else:
        report.add("secret:env.ignored", PASS, ".env.local 已 Git 忽略")
    names = read_env_names(env_file)
    missing = [key for key in REQUIRED_ENV_KEYS if key not in names]
    if missing:
        status = FAIL if profile == "live" else WARN
        report.add(
            "secret:env.keys",
            status,
            "缺少键名："
            + ", ".join(missing)
            + ("（live not_ready）" if status == FAIL else "（live 前需补齐）"),
        )
    else:
        report.add("secret:env.keys", PASS, f"必需 {len(REQUIRED_ENV_KEYS)} 个键名齐备")


def check_runtime_dirs(report: Report, root: Path) -> None:
    runtime = root / "runtime"
    if not runtime.is_dir():
        report.add("runtime:dir", WARN, "runtime/ 不存在，首次使用时创建")
        return
    if not (runtime.stat().st_mode & stat.S_IWUSR):
        report.add("runtime:write", FAIL, "runtime/ 不可写")
    else:
        report.add("runtime:write", PASS, "runtime/ 可写")
    for private in sorted(
        p for p in runtime.iterdir() if p.is_dir() and p.name.startswith("private")
    ):
        mode = stat.S_IMODE(private.stat().st_mode)
        status = PASS if not (mode & ~PRIVATE_DIR_MAX_MODE) else FAIL
        report.add(
            f"runtime:private:{private.name}",
            status,
            f"权限 {oct(mode)}" + ("" if status == PASS else "，要求 ≤0700"),
        )


def tracked_files(root: Path) -> list[str]:
    """仓库可能尚无 commit：-c 索引 + -o 未被 ignore 的工作区文件，与 CHECKSUMS 口径一致。"""
    result = subprocess.run(
        ["git", "ls-files", "-z", "-c", "-o", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        check=True,
    )
    return [p for p in result.stdout.decode("utf-8").split("\0") if p]


def scan_file_for_secrets(path: Path) -> list[str]:
    """返回 '规则@行号' 列表；调用方保证绝不输出内容。"""
    try:
        text = path.read_text(encoding="utf-8")
    except (UnicodeDecodeError, OSError):
        return []  # 二进制或不可读：跟踪清单里不应出现，另项检查
    hits: list[str] = []
    for line_no, line in enumerate(text.splitlines(), start=1):
        lowered = line.lower()
        if any(hint in lowered for hint in ALLOWED_NAME_HINTS):
            continue
        for name, pattern in SECRET_PATTERNS:
            match = pattern.search(line)
            if match and not HEX_ONLY.match(match.group(0).strip("=").strip("'\"")):
                hits.append(f"{name}@{line_no}")
    return hits


def check_no_committed_secrets(report: Report, root: Path) -> None:
    files = tracked_files(root)
    leaks: list[str] = []
    oversized: list[str] = []
    for rel in files:
        path = root / rel
        if not path.is_file():
            continue
        if path.stat().st_size > TRACKED_SCAN_MAX_BYTES:
            oversized.append(rel)
            continue
        leaks.extend(f"{rel}:{hit}" for hit in scan_file_for_secrets(path))
    if oversized:
        report.add(
            "scan:size",
            WARN,
            f"{len(oversized)} 个跟踪文件超过 {TRACKED_SCAN_MAX_BYTES}B 未逐行扫描："
            + ", ".join(oversized[:3]),
        )
    if leaks:
        report.add(
            "scan:secrets",
            FAIL,
            f"{len(leaks)} 处疑似密钥在 Git 跟踪文件中：" + ", ".join(leaks[:5]),
        )
    else:
        report.add("scan:secrets", PASS, f"{len(files)} 个 Git 跟踪文件密钥扫描 0 命中")


def check_toolchain_versions(
    report: Report, root: Path, lock: dict, profile: str = DEFAULT_PROFILE
) -> None:
    """工具链按“实测”判定：开发者 toolchain/ 目录不是所有机器的必要条件，
    但版本漂移与档位要求的缺失工具必须如实报告，不能无条件放行。"""
    strict = profile in STRICT_TOOLCHAIN_PROFILES
    versions_file = root / "toolchain" / "VERSIONS.txt"
    if versions_file.is_file():
        # 声明清单只是开发机事实记录：与锁不一致记 WARN，不作为 FAIL 依据。
        recorded = dict(
            line.split(" ", 1)
            for line in (
                l.strip()
                for l in versions_file.read_text(encoding="utf-8").splitlines()
            )
            if line and not line.startswith("#") and " " in line
        )
        for tool in ("node", "pnpm"):
            want, have = lock[tool], recorded.get(tool, "未记录")
            if want.lstrip("v") != str(have).lstrip("v"):
                report.add(
                    f"toolchain:declared:{tool}",
                    WARN,
                    f"toolchain/VERSIONS.txt={have}，实测锁={want}（仅声明，判定以下方实测为准）",
                )
    for tool in ("node", "pnpm"):
        exe = shutil.which(tool)
        pinned = root / "toolchain" / "node24" / "bin" / tool
        if pinned.is_file() and os.access(pinned, os.X_OK):
            exe = str(pinned)
        if not exe:
            report.add(
                f"toolchain:{tool}",
                FAIL if strict else WARN,
                f"未找到 {tool}（PATH 与 toolchain/ 均无）"
                + ("" if strict else "；offline 完整性检查不要求前端工具链"),
            )
            continue
        actual = subprocess.run(
            [exe, "--version"],
            capture_output=True,
            text=True,
            check=False,  # 启动失败按空版本报告，不中断 doctor
        ).stdout.strip()
        want = lock[tool]
        if not actual:
            report.add(
                f"toolchain:{tool}",
                FAIL if strict else WARN,
                f"{tool} 无法执行 --version",
            )
        elif actual.lstrip("v") == str(want).lstrip("v"):
            report.add(f"toolchain:{tool}", PASS, f"实测 {actual} == 锁 {want}")
        else:
            report.add(
                f"toolchain:{tool}",
                FAIL if strict else WARN,
                f"实测 {actual}，实测锁 {want}（版本漂移，未经验证）",
            )


def check_lock_integrity(report: Report, root: Path) -> None:
    checksums = root / "CHECKSUMS.sha256"
    if not checksums.is_file():
        report.add("lock:checksums", WARN, "CHECKSUMS.sha256 缺失")
        return
    mismatched = 0
    total = 0
    for line in checksums.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        expected, rel = line.split("  ", 1)
        target = root / rel
        total += 1
        if (
            not target.is_file()
            or hashlib.sha256(target.read_bytes()).hexdigest() != expected
        ):
            mismatched += 1
    if mismatched:
        report.add(
            "lock:checksums",
            WARN,
            f"{mismatched}/{total} 个完整性条目不一致（doctor 只读，不修复清单）",
        )
    else:
        report.add("lock:checksums", PASS, f"完整性清单 {total}/{total} 一致")


def run_checks(root: Path, profile: str = DEFAULT_PROFILE) -> Report:
    report = Report()
    lock = load_version_lock(root)
    check_platform(report, root)
    if profile != "bundle":
        check_python(report, lock)
        check_package_versions(report, lock)
        check_openjiuwen_source(report, lock)
    check_config_files(report, root)
    check_private_env(report, root, profile)
    check_runtime_dirs(report, root)
    check_no_committed_secrets(report, root)
    if profile != "bundle":
        check_toolchain_versions(report, root, lock, profile)
    check_lock_integrity(report, root)
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="输出机器可读结果")
    parser.add_argument(
        "--profile",
        choices=PROFILES,
        default=DEFAULT_PROFILE,
        help="offline=源码/依赖完整性；toolchain=+前端工具链实测；live=+私密 env 就绪",
    )
    args = parser.parse_args(argv)
    root = workspace_root()
    try:
        report = run_checks(root, args.profile)
    except subprocess.CalledProcessError as exc:
        print(
            f"doctor 无法完成：git 子命令失败（exit {exc.returncode}）", file=sys.stderr
        )
        return 2
    except FileNotFoundError as exc:
        print(f"doctor 无法完成：{exc}", file=sys.stderr)
        return 2
    if args.json:
        print(
            json.dumps(
                {"counts": report.counts(), "items": report.items}, ensure_ascii=False
            )
        )
    else:
        for item in report.items:
            print(f"[{item['status']}] {item['check']}: {item['detail']}")
        counts = report.counts()
        print(
            f"--- doctor: {counts[PASS]} pass / {counts[WARN]} warn / {counts[FAIL]} fail"
        )
    return 1 if report.failed else 0


if __name__ == "__main__":
    sys.exit(main())
