"""M0-04 guards for scripts/doctor.py: readiness checks, secret-scan integrity,
and the promise that doctor never echoes secret values."""

import importlib.util
import json
import shutil
import stat
import subprocess
from pathlib import Path

import pytest

API_ROOT = Path(__file__).resolve().parent.parent
WORKSPACE = API_ROOT.parent.parent
DOCTOR_PATH = WORKSPACE / "scripts" / "doctor.py"


@pytest.fixture(scope="module")
def doctor():
    spec = importlib.util.spec_from_file_location("doctor", DOCTOR_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def statuses(report_items, check):
    return [item for item in report_items if item["check"].startswith(check)]


# --- 真实工作区：干净 checkout 的 offline 档不得依赖开发者私密资产 ----------


def test_doctor_real_workspace_offline_passes_without_developer_extras(doctor, capsys):
    """干净 checkout（无 .env.local、无 toolchain/）也必须通过离线完整性检查。"""
    exit_code = doctor.main(["--json"])
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    assert exit_code == 0, f"offline 档出现 FAIL：{payload['items']}"
    assert payload["counts"]["FAIL"] == 0


# --- 假工作区 + 假密钥：live 档脱敏与 not_ready 语义 --------------------------

# 假密钥故意不匹配 doctor 自身扫描规则（sk-前缀/24 长连续值），
# 它是测试夹具而非资产；泄露断言只依赖“值不出现在输出”。
FAKE_KEY = "fake-embed-key.dot-0123456789abcdefGHIJ"


def _fake_workspace(tmp_path) -> Path:
    """构造可独立运行 doctor 的最小假工作区；密钥为确定假值，绝不发真实请求。"""
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    (tmp_path / ".gitignore").write_text(".env.local\nruntime/\n", encoding="utf-8")
    config = tmp_path / "config"
    config.mkdir()
    shutil.copy(WORKSPACE / "config" / "versions.lock.json", config)
    shutil.copy(WORKSPACE / "config" / "demo.yaml", config)
    shutil.copy(WORKSPACE / "config" / "environment.env.example", config)
    (tmp_path / "api.md").write_text("# fake api doc\n", encoding="utf-8")
    env = tmp_path / ".env.local"
    env.write_text(
        "EMBEDDING_PROVIDER=fake-provider\n"
        "EMBEDDING_MODEL=fake-embedding-v0\n"
        "EMBEDDING_API_BASE=https://example.invalid/v1\n"
        f"EMBEDDING_API_KEY={FAKE_KEY}\n",
        encoding="utf-8",
    )
    env.chmod(0o600)
    return tmp_path


def test_live_profile_with_fake_env_leaks_no_secret_value(
    doctor, tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(doctor, "workspace_root", lambda: _fake_workspace(tmp_path))
    doctor.main(["--json", "--profile", "live"])
    captured = capsys.readouterr().out
    payload = json.loads(captured)
    env_items = [i for i in payload["items"] if i["check"].startswith("secret:env")]
    assert [i["status"] for i in env_items] == ["PASS", "PASS", "PASS"]
    # 完整假密钥与任何长片段都不得出现在输出（stdout/JSON 明细）里。
    assert FAKE_KEY not in captured
    assert FAKE_KEY[:12] not in captured


def test_offline_profile_passes_without_private_env_or_pinned_toolchain(
    doctor, tmp_path, monkeypatch, capsys
):
    root = _fake_workspace(tmp_path)
    (root / ".env.local").unlink()
    monkeypatch.setattr(doctor, "workspace_root", lambda: root)
    assert doctor.main(["--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["counts"]["FAIL"] == 0


def test_bundle_profile_skips_installed_environment_checks(
    doctor, tmp_path, monkeypatch, capsys
):
    """发行包复验不假设解包目录装过依赖：环境类检查必须整体缺席。"""
    root = _fake_workspace(tmp_path)
    monkeypatch.setattr(doctor, "workspace_root", lambda: root)
    assert doctor.main(["--json", "--profile", "bundle"]) == 0
    payload = json.loads(capsys.readouterr().out)
    names = {item["check"] for item in payload["items"]}
    assert "lock:checksums" in names
    assert not [name for name in names if name.startswith(("pkg:", "openjiuwen"))]
    assert "python" not in names
    assert not [name for name in names if name.startswith("toolchain:")]


def test_live_profile_is_not_ready_without_private_env(
    doctor, tmp_path, monkeypatch, capsys
):
    root = _fake_workspace(tmp_path)
    (root / ".env.local").unlink()
    monkeypatch.setattr(doctor, "workspace_root", lambda: root)
    assert doctor.main(["--json", "--profile", "live"]) == 1
    payload = json.loads(capsys.readouterr().out)
    missing = [i for i in payload["items"] if i["check"] == "secret:env.local"]
    assert [i["status"] for i in missing] == ["FAIL"]


def test_doctor_exit_2_when_version_lock_missing(doctor, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(doctor, "workspace_root", lambda: tmp_path)
    assert doctor.main([]) == 2
    assert "versions.lock.json" in capsys.readouterr().err


# --- 密钥扫描：能抓住真密钥，也不误报完整性清单 -----------------------------


def test_scan_detects_planted_secret_without_echoing_it(doctor, tmp_path):
    victim = tmp_path / "leaky.py"
    fake = "sk-" + "z" * 24  # 显式假的占位密钥
    victim.write_text(f'API_KEY = "{fake}"\nprint(1)\n', encoding="utf-8")
    hits = doctor.scan_file_for_secrets(victim)
    assert any(hit.startswith("openai-style-sk@") for hit in hits)
    assert all(fake not in hit for hit in hits), "命中描述不得包含密钥本体"


def test_scan_does_not_flag_checksum_hex_lines(doctor, tmp_path):
    manifest = tmp_path / "CHECKSUMS.sample"
    digest = "a" * 64
    manifest.write_text(f"{digest}  docs/README.md\n", encoding="utf-8")
    assert doctor.scan_file_for_secrets(manifest) == []


def test_scan_flags_assigned_secret_name_not_value(doctor, tmp_path):
    config = tmp_path / "config.env"
    value = "Qz7" + "x" * 40
    config.write_text(f"APP_PASSWORD={value}\n", encoding="utf-8")
    hits = doctor.scan_file_for_secrets(config)
    assert hits == ["assigned-secret@1"]
    assert value not in ";".join(hits)


# --- 私密文件与来源守卫 ------------------------------------------------------


def test_world_readable_env_file_is_fail(doctor, tmp_path):
    secret = tmp_path / ".env.local"
    secret.write_text("EMBEDDING_API_KEY=placeholder\n", encoding="utf-8")
    secret.chmod(0o644)
    report = doctor.Report()
    doctor.check_private_env(report, tmp_path)
    mode_items = statuses(report.items, "secret:env.mode")
    assert [i["status"] for i in mode_items] == ["FAIL"]


def test_missing_env_file_is_warn_not_fail(doctor, tmp_path):
    report = doctor.Report()
    doctor.check_private_env(report, tmp_path)
    assert statuses(report.items, "secret:env")[0]["status"] == "WARN"


def test_read_env_names_returns_names_only(doctor, tmp_path):
    env = tmp_path / ".env"
    env.write_text("EMBEDDING_API_KEY=super-secret-value\nFOO=bar\n", encoding="utf-8")
    assert doctor.read_env_names(env) == {"EMBEDDING_API_KEY", "FOO"}


class FakeDistribution:
    def __init__(self, payload):
        self._payload = payload

    def read_text(self, name):
        assert name == "direct_url.json"
        return json.dumps(self._payload)


def test_openjiuwen_source_drift_is_fail(doctor, monkeypatch):
    monkeypatch.setattr(doctor, "version", lambda name: "0.1.18")
    monkeypatch.setattr(
        doctor,
        "distribution",
        lambda name: FakeDistribution(
            {
                "url": "https://example.com/other-fork.git",
                "vcs_info": {"commit_id": "0" * 40},
            }
        ),
    )
    lock = json.loads((WORKSPACE / "config" / "versions.lock.json").read_text())
    report = doctor.Report()
    doctor.check_openjiuwen_source(report, lock)
    assert statuses(report.items, "openjiuwen:source")[0]["status"] == "FAIL"


def test_lock_integrity_flags_mismatched_entry(doctor, tmp_path):
    target = tmp_path / "docs" / "a.md"
    target.parent.mkdir()
    target.write_text("v2\n", encoding="utf-8")
    (tmp_path / "CHECKSUMS.sha256").write_text(
        f"{'0' * 64}  docs/a.md\n", encoding="utf-8"
    )
    report = doctor.Report()
    doctor.check_lock_integrity(report, tmp_path)
    item = statuses(report.items, "lock:checksums")[0]
    assert item["status"] == "WARN"
    assert "1/1" in item["detail"]


# --- 输出卫生：明细只含相对路径与计数 ---------------------------------------


def test_real_run_details_have_no_absolute_paths(doctor, capsys):
    assert doctor.main(["--json"]) == 0
    captured = json.loads(capsys.readouterr().out)
    text = json.dumps(captured, ensure_ascii=False)
    assert str(WORKSPACE) not in text
    for item in captured["items"]:
        assert not Path(item["detail"]).is_absolute()


def test_runtime_private_dir_mode_checked(doctor, tmp_path):
    private = tmp_path / "runtime" / "private"
    private.mkdir(parents=True)
    private.chmod(0o755)
    report = doctor.Report()
    doctor.check_runtime_dirs(report, tmp_path)
    items = statuses(report.items, "runtime:private")
    assert items and items[0]["status"] == "FAIL"
    assert oct(stat.S_IMODE(private.stat().st_mode)) in items[0]["detail"]
