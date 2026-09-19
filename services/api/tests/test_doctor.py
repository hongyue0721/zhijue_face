"""M0-04 guards for scripts/doctor.py: readiness checks, secret-scan integrity,
and the promise that doctor never echoes secret values."""

import importlib.util
import json
import stat
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


# --- 真实工作区：无 FAIL 且绝不外泄密钥 -------------------------------------


def test_doctor_real_workspace_passes_and_leaks_no_secret(doctor, capsys):
    key_value = None
    env_file = WORKSPACE / ".env.local"
    for line in env_file.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("EMBEDDING_API_KEY="):
            key_value = line.split("=", 1)[1].strip().strip('"').strip("'")
    assert key_value, "测试前提：本地私密配置存在"

    exit_code = doctor.main(["--json"])
    captured = capsys.readouterr().out
    assert exit_code == 0, "锁定环境里 doctor 不得报 FAIL"
    payload = json.loads(captured)
    assert payload["counts"]["FAIL"] == 0
    # 密钥值及其任何长片段都不得出现在输出里。
    assert key_value not in captured
    assert key_value[:12] not in captured


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
