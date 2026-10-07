"""Explicit TEST_ONLY approvals for temporary test databases, never runtime defaults."""

import json
from pathlib import Path

from zhijue.domain.competency_profiles import parse_competency_profile
from zhijue.domain.knowledge_packs import parse_competencies

REPO_ROOT = Path(__file__).resolve().parents[3]
EMBEDDED_PROFILE = parse_competency_profile(
    parse_competencies(
        {
            "competencies.json": (
                REPO_ROOT / "knowledge_packs/embedded_software_junior/competencies.json"
            ).read_bytes()
        }
    )
)
TEST_JD = (REPO_ROOT / "data/jd/preset_embedded_junior.txt").read_text(encoding="utf-8")


def approve_test_pack(service, release_id=None):
    """Opt-in setup for an already isolated fixture database."""
    assert service._runtime_dir.resolve() != (REPO_ROOT / "runtime").resolve()
    release_id = release_id or service.list_view()["default_pack_release_id"]
    detail = service.detail_view(release_id)
    return service.record_review(
        release_id=release_id,
        expected_digest=detail["content_digest"],
        decision="approved",
        reviewer_id="TEST_ONLY_owner",
        reviewer_role="owner",
        note="TEST_ONLY explicit two-level fixture approval; not a real owner decision.",
        level1_reviewed=True,
        level2_reviewed=True,
        rules_reviewed=True,
    )


def synthetic_service_pack_files(*, version="1.0.0", example=True):
    """An unregistered occupation with six draft seeds and literal data rules."""
    root = REPO_ROOT / "knowledge_packs/embedded_software_junior"
    files = {
        p.relative_to(root).as_posix(): p.read_bytes()
        for p in root.rglob("*")
        if p.is_file()
    }
    manifest = json.loads(files["manifest.json"])
    manifest.update(
        pack_id="test-service-role",
        version=version,
        name="合成服务岗位",
        competency_profile_id="test-service-profile",
    )
    manifest.pop("example_jd_file", None)
    capabilities = [
        {"competency_id": f"service.skill.{i}", "label": f"服务能力 {i}"}
        for i in range(6)
    ]
    rules = [
        {"competency_id": c["competency_id"], "keywords": [f"skill{i}"]}
        for i, c in enumerate(capabilities)
    ]
    profile = {
        "competency_profile_id": "test-service-profile",
        "profile_version": "1.0.0",
        "capabilities": capabilities,
        "jd_keyword_rules": rules,
        "direct_evidence_rules": rules,
        "related_context_rules": [
            {
                "competency_id": capabilities[0]["competency_id"],
                "keywords": ["contextonly"],
            }
        ],
        "seed_family_rules": [],
    }
    for i, path in enumerate(manifest["seeds"]):
        seed = json.loads(files[path])
        seed["id"] = f"seed_test_service_{i}"
        seed["competency_id"] = capabilities[i]["competency_id"]
        seed["review_status"] = "draft"
        seed["review_levels"] = {
            level: {
                "status": "pending",
                "reviewer_role": "owner",
                "checked": [],
                "at": None,
            }
            for level in ("level1", "level2")
        }
        seed["stem"] = f"请解释合成服务能力 skill{i} 的实现与验证边界。"
        files[path] = json.dumps(seed, ensure_ascii=False).encode()
    if example:
        manifest["example_jd_file"] = "examples/jd.txt"
        files["examples/jd.txt"] = (
            "SYNTHETIC_DEMO_JD\n必要项："
            + "；".join(f"解释 skill{i}" for i in range(6))
        ).encode()
    files["manifest.json"] = json.dumps(manifest, ensure_ascii=False).encode()
    files["competencies.json"] = json.dumps(profile, ensure_ascii=False).encode()
    return files
