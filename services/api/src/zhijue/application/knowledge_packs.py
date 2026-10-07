"""结构化岗位知识包服务：注册、导入、解析与面试冻结（主文件 Phase 3/4.5/5.1）。

职责边界：

- 这是对既有资源（SeedBank/能力配置/来源登记）的**加载与信任边界**，
  不是第二套 Knowledge 引擎；候选人 Knowledge 仍走 openJiuwen 原路径。
- 包内任何 `approved` 只是作者声明。服务端有效审核必须绑定包内容摘要、
  能力规则原始 canonical 字节摘要和包外 owner 两级确认；draft Seed 可外部批准。
- release 不可变：`(pack_id, version)` 唯一；同摘要幂等复用，
  异摘要冲突拒绝覆盖（B09/E09）。存储文件每次解析都重算摘要，
  损坏显式失败，绝不悄悄回落默认包（D06）。
"""

from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from zhijue.adapters.db.models import (
    KnowledgePackImportReceipt,
    KnowledgePackRelease,
    KnowledgePackReview,
    utc_now_rfc3339,
)
from zhijue.application.seed_bank import (
    REVIEW_RANK,
    SeedBank,
    SeedBankError,
    load_seed_bank,
)
from zhijue.domain.competency_profiles import (
    CompetencyProfile,
    parse_competency_profile,
)
from zhijue.domain.errors import DomainError, JdRejected, ResourceNotFoundError
from zhijue.domain.ids import new_id
from zhijue.domain.knowledge_packs import (
    MANIFEST_FILE,
    PackLimits,
    PackManifest,
    PackValidationError,
    ReviewStatus,
    ValidationCheck,
    ValidationStatus,
    assert_seed_reference_ids_resolve,
    canonicalize_file_bytes,
    compute_content_digest,
    file_sha256,
    parse_competencies,
    parse_manifest,
    parse_sources,
    release_id_for,
    safe_extract_zip,
    seed_content_hash,
    strict_json_loads,
)
from zhijue.domain.requisition import (
    JDSourceType,
    extract_requirements,
    make_snapshot,
)

# 内置六条 Seed 的历史批准记录（M2-01 负责人结论）。ensure_builtin 只登记
# “可审计映射”：同一批字节内容、同一记录 ID，不新增批准范围。
BUILTIN_REVIEW_RECORD_ID = "review_m2_01_level2_owner_20260919"
BUILTIN_PACK_STORAGE_ROOT = "knowledge_packs/embedded_software_junior"
# Fixed canonical-byte baseline from the six unchanged 0.2.1 assets approved in
# docs/reviews/review_m2_01_level2_owner_20260919.md. Never derive this allowlist
# from the files being registered: doing so would approve their replacements.
BUILTIN_APPROVED_SEEDS = {
    "seed_embedded_freertos_queue_mechanism": (
        "0.2.1",
        "bf8418d609b34518a3c62d39c78e11598c1fad374ec8833eccd4cae689bdb1e0",
    ),
    "seed_embedded_interrupt_priority": (
        "0.2.1",
        "153f0b4525fdfb0d3d078b2252dcca182abd4890d5efa5ae32ee1a878d7d8fdc",
    ),
    "seed_embedded_mutex_vs_semaphore": (
        "0.2.1",
        "944acbf4cb293b93bfc048f65d5bb3d8526c52fc107efc643c8eed66266c4260",
    ),
    "seed_embedded_rtos_task_period": (
        "0.2.1",
        "2c333fc37a49af4f1aa35e3d2190b588307cea8a15997abb9a57b81da57992ca",
    ),
    "seed_embedded_spi_i2c_selection": (
        "0.2.1",
        "33c2d1a915435fa53c66cdba98642397193c7049ccd06848a82a4124f9994e18",
    ),
    "seed_embedded_uart_dma_debug": (
        "0.2.1",
        "f800aab47840c5328d8e1fa2068ccfe89e95e99f4ac0711d7e34c51c5754c919",
    ),
}


class PackDomainError(DomainError):
    """带机器码的包错误；routes 直接透传 code/message，不再二次翻译。"""


@dataclass(frozen=True)
class InterviewPackBinding:
    """受理计划请求时冻结进 Interview 的不可变绑定。"""

    release_id: str
    pack_id: str
    version: str
    content_digest: str
    competency_profile_id: str
    seed_bank_version: str
    review_snapshot: dict[str, Any] | None = None


@dataclass(frozen=True)
class ImportOutcome:
    release: KnowledgePackRelease
    reused: bool


@dataclass(frozen=True)
class ResolvedKnowledgePack:
    """既有资源的加载边界（主文件 §5）：只读 SeedBank + 能力配置 + 来源。"""

    release_id: str
    pack_id: str
    version: str
    name: str
    content_digest: str
    profile: CompetencyProfile
    profile_digest: str
    rules_reviewed: bool
    example_jd: str | None
    seed_bank: SeedBank
    sources: tuple[dict[str, Any], ...]
    review: dict[str, Any] | None
    binding: InterviewPackBinding


def example_jd_source_name(pack_id: str) -> str:
    return "SYNTHETIC_DEMO_JD_" + pack_id


def _error(code: str, message: str, status_code: int) -> PackDomainError:
    return PackDomainError(message, code=code, status_code=status_code)


class KnowledgePackService:
    def __init__(
        self,
        engine,
        *,
        runtime_dir: Path,
        repo_root: Path,
        limits: PackLimits | None = None,
        default_pack_id: str,
        live_allowed_review_status: str = "approved",
    ) -> None:
        self._engine = engine
        self._runtime_dir = Path(runtime_dir)
        self._repo_root = Path(repo_root)
        self._limits = limits or PackLimits()
        self._default_pack_id = default_pack_id
        self._default_release_id: str | None = None
        if live_allowed_review_status not in REVIEW_RANK:
            raise ValueError("未知的 live 审核门槛")
        self._live_allowed_review_status = live_allowed_review_status

    # ------------------------------------------------------------------ 存储

    @property
    def limits(self) -> PackLimits:
        return self._limits

    def _releases_root(self) -> Path:
        return self._runtime_dir / "knowledge_packs" / "releases"

    def _uploads_root(self) -> Path:
        return self._runtime_dir / "knowledge_packs" / "uploads"

    def _storage_path(self, row: KnowledgePackRelease) -> Path:
        if row.storage_kind == "builtin":
            return self._repo_root / row.storage_root
        return self._releases_root() / row.storage_root

    def _load_canonical_files(self, row: KnowledgePackRelease) -> dict[str, bytes]:
        """从存储读回并按同一规则归一化；任何与登记摘要的偏差显式失败。"""
        root = self._storage_path(row)
        if not root.is_dir():
            raise _error(
                "PACK_CONTENT_MISSING",
                "岗位包存储目录不存在；该 release 不可用。",
                503,
            )
        files: dict[str, bytes] = {}
        for entry in row.file_index:
            path = root / entry["path"]
            try:
                raw = path.read_bytes()
            except OSError as exc:
                raise _error(
                    "PACK_CONTENT_MISSING",
                    f"岗位包文件不可读：{entry['path']}",
                    503,
                ) from exc
            files[entry["path"]] = canonicalize_file_bytes(raw, path=entry["path"])
        digest, index = compute_content_digest(
            pack_id=row.pack_id, version=row.version, files=files
        )
        stored = {item["path"]: item["sha256"] for item in row.file_index}
        recomputed = {item["path"]: item["sha256"] for item in index}
        if digest != row.content_digest or stored != recomputed:
            raise _error(
                "PACK_CONTENT_CORRUPTED",
                "岗位包内容与登记摘要不一致；拒绝用其他包顶替。",
                503,
            )
        return files

    # ---------------------------------------------------------------- 注册

    def register_files(
        self,
        files: dict[str, bytes],
        *,
        upload_sha256: str = "",
        storage_kind: str = "runtime",
        storage_root: str | None = None,
        operation_id: str | None = None,
    ) -> ImportOutcome:
        """校验 → 摘要 → 原子登记；同 (pack_id, version, digest) 幂等复用。"""
        manifest = parse_manifest(files)
        profile = parse_competency_profile(parse_competencies(files))
        if profile.profile_id != manifest.competency_profile_id:
            raise _error("PACK_PROFILE_INVALID", "manifest 与能力配置 ID 不一致。", 422)
        sources = parse_sources(files)
        checks: list[ValidationCheck] = [
            ValidationCheck(
                "structure", ValidationStatus.PASSED, "目录与文件集合符合声明"
            ),
            ValidationCheck(
                "manifest", ValidationStatus.PASSED, f"{MANIFEST_FILE} 契约通过"
            ),
            ValidationCheck(
                "competencies",
                ValidationStatus.PASSED,
                f"有限能力规则 {profile.profile_id}/{profile.profile_version} 通过严格解析",
            ),
        ]
        seed_index = self._validate_seeds(files, manifest, sources, checks, profile)
        self._validate_example_jd(files, manifest, profile, checks)
        digest, index = compute_content_digest(
            pack_id=manifest.pack_id, version=manifest.version, files=files
        )
        release_id = release_id_for(digest)
        checks.append(
            ValidationCheck(
                "content_digest",
                ValidationStatus.PASSED,
                f"服务端重算 {digest[:23]}…",
            )
        )
        checks.append(
            ValidationCheck(
                "review",
                ValidationStatus.NOT_RUN,
                "服务端有效审核=unreviewed（新内容默认；仅包外负责人记录可改变）",
            )
        )
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            existing = session.scalar(
                select(KnowledgePackRelease).where(
                    KnowledgePackRelease.pack_id == manifest.pack_id,
                    KnowledgePackRelease.version == manifest.version,
                )
            )
            if existing is not None:
                if existing.content_digest == digest:
                    if storage_kind == "runtime" and storage_root:
                        self._discard_staging(storage_root)
                    return ImportOutcome(existing, reused=True)
                raise _error(
                    "PACK_VERSION_CONFLICT",
                    f"{manifest.pack_id} v{manifest.version} 已注册且内容不同；"
                    "禁止覆盖旧 release，请提升 version 后重新打包。",
                    409,
                )
            if storage_kind == "runtime":
                if storage_root is None:
                    raise _error("INVALID_REQUEST", "runtime 导入缺少暂存目录", 500)
                staging = self._runtime_dir / "staging" / storage_root
                final_dir = self._releases_root() / release_id
                final_dir.parent.mkdir(parents=True, exist_ok=True)
                if final_dir.exists():
                    self._discard_staging(storage_root)
                else:
                    os.replace(staging, final_dir)
                stored_root = release_id
            else:
                stored_root = storage_root or BUILTIN_PACK_STORAGE_ROOT
            row = KnowledgePackRelease(
                id=release_id,
                pack_id=manifest.pack_id,
                version=manifest.version,
                name=manifest.name,
                description=manifest.description,
                format_version="1.0",
                competency_profile_id=manifest.competency_profile_id,
                content_digest=digest,
                upload_sha256=upload_sha256,
                storage_kind=storage_kind,
                storage_root=stored_root,
                manifest_snapshot={
                    **manifest.as_dict(),
                    "seed_index": seed_index,
                },
                file_index=index,
                validation_status=ValidationStatus.PASSED,
                validation_checks=[check.as_dict() for check in checks],
                seed_count=len(manifest.seeds),
                approved_seed_count=0,
                source_count=len(sources),
                supported_scope=manifest.supported_scope,
                unsupported_scope=manifest.unsupported_scope,
                source_kind=manifest.source_kind,
                import_operation_id=operation_id,
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError as exc:
                # 并发同内容注册：唯一约束保证权威行只有一个（E09）。
                winner = session.scalar(
                    select(KnowledgePackRelease).where(
                        KnowledgePackRelease.pack_id == manifest.pack_id,
                        KnowledgePackRelease.version == manifest.version,
                    )
                )
                if winner is not None and winner.content_digest == digest:
                    return ImportOutcome(winner, reused=True)
                raise _error(
                    "PACK_VERSION_CONFLICT",
                    "同 (pack_id, version) 并发注册了不同内容。",
                    409,
                ) from exc
        return ImportOutcome(row, reused=False)

    def _validate_seeds(
        self,
        files: dict[str, bytes],
        manifest: PackManifest,
        sources: tuple[dict[str, Any], ...],
        checks: list[ValidationCheck],
        profile: CompetencyProfile,
    ) -> list[dict[str, Any]]:
        payloads: dict[str, Any] = {}
        for seed_path in manifest.seeds:
            payloads[seed_path] = strict_json_loads(
                files[seed_path].decode("utf-8"), path=seed_path
            )
        try:
            assert_seed_reference_ids_resolve(payloads, sources)
        except PackValidationError as exc:
            raise _error(exc.code, exc.message, 422) from exc
        # Seed 契约复用唯一既有入口校验（seed.schema.json + ADR-013 约束）。
        staging = Path(
            tempfile.mkdtemp(prefix="zhijue-seedcheck-", dir=str(self._runtime_dir))
        )
        try:
            seeds_dir = staging / "seeds"
            seeds_dir.mkdir()
            for seed_path in manifest.seeds:
                name = seed_path.removeprefix("seeds/")
                (seeds_dir / name).write_bytes(files[seed_path])
            try:
                load_seed_bank(seeds_dir)
            except SeedBankError as exc:
                raise _error("PACK_SEED_SCHEMA_INVALID", str(exc), 422) from exc
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        index = [
            {
                "seed_id": payload["id"],
                "seed_version": payload["version"],
                "competency_id": payload["competency_id"],
                "file": seed_path,
                "content_sha256": seed_content_hash(files[seed_path]),
                "declared_review_status": payload["review_status"],
            }
            for seed_path, payload in sorted(payloads.items())
        ]
        ids = [entry["seed_id"] for entry in index]
        if len(set(ids)) != len(ids):
            raise _error("PACK_DUPLICATE_SEED_ID", "包内 Seed ID 重复", 422)
        if any(entry["competency_id"] not in profile.competency_ids for entry in index):
            raise _error("PACK_SEED_COMPETENCY_INVALID", "Seed 引用未声明的能力。", 422)
        checks.append(
            ValidationCheck(
                "seeds_schema",
                ValidationStatus.PASSED,
                f"{len(index)} 条 Seed 通过契约校验；引用均可解析到来源登记",
            )
        )
        return index

    @staticmethod
    def _validate_example_jd(
        files: dict[str, bytes],
        manifest: PackManifest,
        profile: CompetencyProfile,
        checks: list[ValidationCheck],
    ) -> None:
        """声明的示例 JD 会在未填 JD 时直接用于出题，导入时就按出题同一路径试抽取。

        抽不出任何要求的示例等于声明了一份不可用的输入，应在导入时拒绝，
        而不是等到生成计划才失败。
        """
        if manifest.example_jd_file is None:
            return
        try:
            snapshot = make_snapshot(
                snapshot_id="example_jd_check",
                profile_id="example_jd_check",
                raw_text=files[manifest.example_jd_file].decode("utf-8"),
                source_type=JDSourceType.SYNTHETIC_DEMO_JD,
                source_name=example_jd_source_name(manifest.pack_id),
            )
        except JdRejected as exc:
            raise _error("PACK_EXAMPLE_JD_INVALID", exc.message, 422) from exc
        requirements = extract_requirements(snapshot, profile=profile)
        if not requirements:
            raise _error(
                "PACK_EXAMPLE_JD_INVALID",
                "示例 JD 按本包能力规则识别不到任何岗位要求；"
                "需要「必要项：」「加分项：」等显式分区，且条目命中 JD 关键词。",
                422,
            )
        checks.append(
            ValidationCheck(
                "example_jd",
                ValidationStatus.PASSED,
                f"示例 JD 按本包规则识别出 {len(requirements)} 条岗位要求",
            )
        )

    def import_pack_bytes(
        self, zip_bytes: bytes, *, operation_id: str | None = None
    ) -> ImportOutcome:
        """完整导入路径：安全解压 → 校验 → 暂存 → 原子登记。"""
        upload_sha256 = hashlib.sha256(zip_bytes).hexdigest()
        try:
            files = safe_extract_zip(zip_bytes, self._limits)
        except PackValidationError as exc:
            raise _error(exc.code, exc.message, 422) from exc
        staging_id = new_id("staging").removeprefix("staging_")
        # register_files 按 runtime/staging/<storage_root> 找暂存目录，
        # 再原子搬到 releases/<release_id>；这里不能多套一层 package/。
        staging = self._runtime_dir / "staging" / staging_id
        staging.mkdir(parents=True, exist_ok=True)
        try:
            for path, data in files.items():
                target = staging / path
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            return self.register_files(
                files,
                upload_sha256=upload_sha256,
                storage_kind="runtime",
                storage_root=staging_id,
                operation_id=operation_id,
            )
        finally:
            shutil.rmtree(
                self._runtime_dir / "staging" / staging_id, ignore_errors=True
            )

    def _discard_staging(self, storage_root: str) -> None:
        shutil.rmtree(self._runtime_dir / "staging" / storage_root, ignore_errors=True)

    # ---------------------------------------------------------------- 内置迁移

    def ensure_builtin_release(self) -> KnowledgePackRelease:
        """Register built-in assets and retain only historical Seed approval facts.

        M2-01 approved six exact Seed byte hashes, not competency mapping rules.
        This migration leaves all new rule-review columns NULL and never permits
        a new plan until an owner explicitly reviews both levels and rules.
        """
        root = self._repo_root / BUILTIN_PACK_STORAGE_ROOT
        if not root.is_dir():
            raise _error(
                "PACK_BUILTIN_ASSETS_MISSING",
                f"内置岗位包资产缺失：{BUILTIN_PACK_STORAGE_ROOT}",
                503,
            )
        files: dict[str, bytes] = {}
        for path in sorted(root.rglob("*")):
            if path.is_file():
                rel = str(path.relative_to(root)).replace(os.sep, "/")
                files[rel] = canonicalize_file_bytes(path.read_bytes(), path=rel)
        outcome = self.register_files(
            files,
            storage_kind="builtin",
            storage_root=BUILTIN_PACK_STORAGE_ROOT,
        )
        # outcome.release 属于 register_files 已关闭的 session；直接改它的
        # 字段不会落库。批准计数必须在下面的事务里写回托管实例。
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            row = session.get(KnowledgePackRelease, outcome.release.id)
            existing_review = session.scalar(
                select(KnowledgePackReview)
                .where(
                    KnowledgePackReview.release_id == row.id,
                    KnowledgePackReview.content_digest == row.content_digest,
                    KnowledgePackReview.reviewer_id == BUILTIN_REVIEW_RECORD_ID,
                )
                .order_by(KnowledgePackReview.reviewed_at.desc())
            )
            if existing_review is None:
                scope = [
                    {
                        "seed_id": entry["seed_id"],
                        "seed_version": entry["seed_version"],
                        "seed_content_sha256": entry["content_sha256"],
                    }
                    for entry in row.manifest_snapshot.get("seed_index", [])
                    if entry["declared_review_status"] == "approved"
                    and BUILTIN_APPROVED_SEEDS.get(entry["seed_id"])
                    == (entry["seed_version"], entry["content_sha256"])
                ]
                if len(scope) != len(BUILTIN_APPROVED_SEEDS):
                    raise _error(
                        "PACK_BUILTIN_MIGRATION_INVALID",
                        "内置迁移必须且只能继承 M2-01 六条原内容；"
                        "新增/缺失 Seed 不会自动获批。",
                        503,
                    )
                session.add(
                    KnowledgePackReview(
                        id=new_id("kpv"),
                        release_id=row.id,
                        content_digest=row.content_digest,
                        decision="approved",
                        reviewer_id=BUILTIN_REVIEW_RECORD_ID,
                        reviewer_role="owner",
                        note=(
                            "迁移映射：M2-01 负责人批准的六条原内容"
                            "（ID/版本/正文不变）；批准范围不扩张到新增题、"
                            "rubric 改写、新领域或事实边界变更。"
                        ),
                        approved_seed_scope=scope,
                        reviewed_at=utc_now_rfc3339(),
                    )
                )
                row.approved_seed_count = self._recompute_approved_count(session, row)
        if row.pack_id != self._default_pack_id:
            raise _error(
                "PACK_DEFAULT_NOT_REGISTERED",
                "配置的默认包与本次核验的内置资产不一致；请明确选择已审核 release。",
                503,
            )
        # 默认身份来自启动时核验的资产，不按上传时间推导；同摘要的上传复用也成立。
        self._default_release_id = row.id
        return row

    # ---------------------------------------------------------------- 审核信任

    def effective_review(
        self, session: Session, row: KnowledgePackRelease
    ) -> dict[str, Any] | None:
        """有效审核 = 摘要匹配的最近记录。摘要不符的记录不生效（C03/B10）。"""
        review = session.scalar(
            select(KnowledgePackReview)
            .where(
                KnowledgePackReview.release_id == row.id,
                KnowledgePackReview.content_digest == row.content_digest,
            )
            .order_by(KnowledgePackReview.reviewed_at.desc())
        )
        if review is None:
            return None
        return {
            "review_id": review.id,
            "decision": review.decision,
            "reviewer_id": review.reviewer_id,
            "reviewer_role": review.reviewer_role,
            "note": review.note,
            "reviewed_at": review.reviewed_at,
            "content_digest": review.content_digest,
            "approved_seed_scope": list(review.approved_seed_scope),
            "competency_profile_id": review.competency_profile_id,
            "profile_version": review.profile_version,
            "profile_digest": review.profile_digest,
            "level1_reviewed": review.level1_reviewed,
            "level2_reviewed": review.level2_reviewed,
            "rules_reviewed": review.rules_reviewed,
        }

    def record_review(
        self,
        *,
        release_id: str,
        expected_digest: str,
        decision: str,
        reviewer_id: str,
        reviewer_role: str,
        note: str,
        approved_seed_ids: list[str] | None = None,
        level1_reviewed: bool = False,
        level2_reviewed: bool = False,
        rules_reviewed: bool = False,
    ) -> dict[str, Any]:
        """负责人登记审核结论（CLI 与测试信任注入共用此入口）。

        expected_digest 与当前重算摘要不一致 → 拒绝；批准范围逐条绑定
        Seed 内容 hash。执行 Agent 不得自行调用它批准新内容。
        """
        if decision not in {"approved", "rejected"}:
            raise _error("INVALID_REQUEST", "decision 仅允许 approved/rejected", 400)
        if not reviewer_id.strip() or not note.strip():
            raise _error(
                "INVALID_REQUEST",
                "负责人标识与审核备注必须非空（谁在何时批了什么）",
                400,
            )
        if reviewer_role != "owner":
            raise _error(
                "PACK_REVIEW_OWNER_REQUIRED", "审核登记必须由 owner 完成。", 403
            )
        if decision == "approved" and not (
            level1_reviewed is True
            and level2_reviewed is True
            and rules_reviewed is True
        ):
            raise _error(
                "PACK_REVIEW_CONFIRMATION_REQUIRED",
                "批准必须显式确认 Level 1、Level 2 及能力规则内容均已核对。",
                422,
            )
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            row = session.get(KnowledgePackRelease, release_id)
            if row is None:
                raise ResourceNotFoundError("岗位包 release 不存在。")
            files = self._load_canonical_files(row)  # 损坏即失败
            digest, _ = compute_content_digest(
                pack_id=row.pack_id, version=row.version, files=files
            )
            if digest != expected_digest:
                raise _error(
                    "PACK_REVIEW_DIGEST_MISMATCH",
                    "期望摘要与当前 release 实际内容不符；拒绝登记审核。",
                    409,
                )
            profile = parse_competency_profile(parse_competencies(files))
            profile_digest = "sha256:" + file_sha256(files["competencies.json"])
            seed_index = row.manifest_snapshot.get("seed_index", [])
            scope: list[dict[str, Any]] = []
            if decision == "approved":
                known_ids = {entry["seed_id"] for entry in seed_index}
                wanted = (
                    set(approved_seed_ids) if approved_seed_ids is not None else None
                )
                if wanted is not None and not wanted <= known_ids:
                    raise _error(
                        "PACK_REVIEW_SCOPE_UNKNOWN_SEED",
                        "批准了包内不存在的 Seed",
                        422,
                    )
                for entry in seed_index:
                    if wanted is not None and entry["seed_id"] not in wanted:
                        continue
                    scope.append(
                        {
                            "seed_id": entry["seed_id"],
                            "seed_version": entry["seed_version"],
                            "seed_content_sha256": entry["content_sha256"],
                        }
                    )
            review = KnowledgePackReview(
                id=new_id("kpv"),
                release_id=row.id,
                content_digest=digest,
                decision=decision,
                reviewer_id=reviewer_id,
                reviewer_role=reviewer_role,
                note=note,
                approved_seed_scope=scope,
                competency_profile_id=profile.profile_id,
                profile_version=profile.profile_version,
                profile_digest=profile_digest,
                level1_reviewed=level1_reviewed,
                level2_reviewed=level2_reviewed,
                rules_reviewed=rules_reviewed,
                reviewed_at=utc_now_rfc3339(),
            )
            session.add(review)
            row.approved_seed_count = self._recompute_approved_count(session, row)
            return self.effective_review(session, row) or {}

    def _recompute_approved_count(
        self, session: Session, row: KnowledgePackRelease
    ) -> int:
        review = self.effective_review(session, row)
        files = self._load_canonical_files(row)
        profile = parse_competency_profile(parse_competencies(files))
        if not self._rules_reviewed(
            review, profile, "sha256:" + file_sha256(files["competencies.json"])
        ):
            return 0
        scope = {
            (entry["seed_id"], entry["seed_version"], entry["seed_content_sha256"])
            for entry in review["approved_seed_scope"]
        }
        return sum(
            (entry["seed_id"], entry["seed_version"], entry["content_sha256"]) in scope
            for entry in row.manifest_snapshot.get("seed_index", [])
        )

    @staticmethod
    def _rules_reviewed(
        review: dict[str, Any] | None, profile: CompetencyProfile, profile_digest: str
    ) -> bool:
        return bool(
            review is not None
            and review.get("decision") == "approved"
            and review.get("reviewer_role") == "owner"
            and review.get("level1_reviewed") is True
            and review.get("level2_reviewed") is True
            and review.get("rules_reviewed") is True
            and review.get("competency_profile_id") == profile.profile_id
            and review.get("profile_version") == profile.profile_version
            and review.get("profile_digest") == profile_digest
        )

    # ---------------------------------------------------------------- 解析边界

    def resolve(
        self, release_id: str, *, binding: InterviewPackBinding | None = None
    ) -> ResolvedKnowledgePack:
        """Validate bytes on every load; existing interviews use admission review facts."""
        legacy_snapshot = False
        with Session(self._engine, expire_on_commit=False) as session:
            row = session.get(KnowledgePackRelease, release_id)
            if row is None:
                raise ResourceNotFoundError("岗位包 release 不存在。")
            if binding is None:
                review = self.effective_review(session, row)
                review_status = self._live_allowed_review_status
            else:
                if (
                    binding.release_id != row.id
                    or binding.pack_id != row.pack_id
                    or binding.version != row.version
                    or binding.content_digest != row.content_digest
                    or binding.competency_profile_id != row.competency_profile_id
                ):
                    raise _error(
                        "PACK_BINDING_MISMATCH",
                        "冻结的岗位包身份与 release 不符。",
                        409,
                    )
                snapshot = binding.review_snapshot
                if snapshot is None:
                    raise _error(
                        "PACK_REVIEW_SNAPSHOT_MISSING",
                        "历史面试没有受理时审核快照；保留既有题目与报告，请新建面试。",
                        409,
                    )
                review = snapshot.get("review")
                review_status = snapshot.get("live_allowed_review_status")
                if (
                    snapshot.get("schema_version") not in (1, 2)
                    or not isinstance(review, dict)
                    or review.get("decision") != "approved"
                    or review.get("content_digest") != row.content_digest
                    or review_status not in REVIEW_RANK
                    or not isinstance(review.get("approved_seed_scope"), list)
                ):
                    raise _error(
                        "PACK_REVIEW_SNAPSHOT_INVALID", "冻结审核快照无效。", 409
                    )
                legacy_snapshot = snapshot["schema_version"] == 1
        files = self._load_canonical_files(row)
        profile = parse_competency_profile(parse_competencies(files))
        profile_digest = "sha256:" + file_sha256(files["competencies.json"])
        manifest = parse_manifest(files)
        if profile.profile_id != row.competency_profile_id:
            raise _error("PACK_PROFILE_INVALID", "能力配置身份与 release 不符。", 503)
        rules_reviewed = self._rules_reviewed(review, profile, profile_digest)
        if binding is not None and not legacy_snapshot and not rules_reviewed:
            raise _error(
                "PACK_REVIEW_SNAPSHOT_INVALID", "冻结的两级规则审核无效。", 409
            )
        sources = parse_sources(files)
        # seed_id → 内容 hash 的唯一权威映射来自与摘要一起校验过的文件本体。
        hash_by_seed_id: dict[str, str] = {}
        payloads: dict[str, Any] = {}
        for seed_path in manifest.seeds:
            payload = strict_json_loads(
                files[seed_path].decode("utf-8"), path=seed_path
            )
            if payload["competency_id"] not in profile.competency_ids:
                raise _error(
                    "PACK_SEED_COMPETENCY_INVALID", "Seed 引用未声明能力。", 503
                )
            hash_by_seed_id[payload["id"]] = seed_content_hash(files[seed_path])
            payloads[seed_path] = payload
        assert_seed_reference_ids_resolve(payloads, sources)
        staging = Path(
            tempfile.mkdtemp(prefix="zhijue-resolve-", dir=str(self._runtime_dir))
        )
        try:
            seeds_dir = staging / "seeds"
            seeds_dir.mkdir()
            for seed_path in manifest.seeds:
                (seeds_dir / seed_path.removeprefix("seeds/")).write_bytes(
                    files[seed_path]
                )
            try:
                full_bank = load_seed_bank(seeds_dir)
            except SeedBankError as exc:
                raise _error("PACK_SEED_SCHEMA_INVALID", str(exc), 503) from exc
        finally:
            shutil.rmtree(staging, ignore_errors=True)
        scope: set[tuple[str, str, str]] = set()
        if (
            review is not None
            and review["decision"] == "approved"
            and (rules_reviewed or legacy_snapshot)
        ):
            scope = {
                (
                    entry["seed_id"],
                    entry["seed_version"],
                    entry["seed_content_sha256"],
                )
                for entry in review["approved_seed_scope"]
            }
        threshold = REVIEW_RANK[review_status]
        eligible = [
            seed
            for seed in full_bank.seeds
            if (seed.id, seed.version, hash_by_seed_id.get(seed.id)) in scope
            and (
                not legacy_snapshot
                or REVIEW_RANK.get(seed.review_status, -1) >= threshold
            )
        ]
        bank = SeedBank(
            eligible,
            schema_version=full_bank.schema_version,
            live_allowed_review_status=review_status,
            externally_approved=not legacy_snapshot,
        )
        if (
            binding is not None
            and binding.seed_bank_version != bank.version_fingerprint()
        ):
            raise _error("PACK_BINDING_MISMATCH", "冻结审核范围与题库指纹不符。", 409)
        binding = InterviewPackBinding(
            release_id=row.id,
            pack_id=row.pack_id,
            version=row.version,
            content_digest=row.content_digest,
            competency_profile_id=row.competency_profile_id,
            seed_bank_version=bank.version_fingerprint(),
            review_snapshot={
                "schema_version": 1 if legacy_snapshot else 2,
                "review": review,
                "live_allowed_review_status": review_status,
            },
        )
        return ResolvedKnowledgePack(
            release_id=row.id,
            pack_id=row.pack_id,
            version=row.version,
            name=row.name,
            content_digest=row.content_digest,
            profile=profile,
            profile_digest=profile_digest,
            rules_reviewed=rules_reviewed,
            example_jd=(
                files[manifest.example_jd_file].decode("utf-8")
                if manifest.example_jd_file is not None
                else None
            ),
            seed_bank=bank,
            sources=sources,
            review=review,
            binding=binding,
        )

    def freeze_for_new_plan(
        self, requested_release_id: str | None
    ) -> InterviewPackBinding:
        """计划请求受理时的冻结解析（主文件 5.1）：只接受 selectable 的 release。"""
        release_id = (
            self._default_release_id
            if requested_release_id is None
            else requested_release_id
        )
        if release_id is None:
            raise _error(
                "SERVICE_NOT_READY",
                "没有可解析的内置岗位包；面试计划能力未就绪，岗位包管理仍可用。",
                503,
            )
        resolved = self.resolve(release_id)
        selectable, reasons = self.selectability(resolved)
        if not selectable:
            raise PackDomainError(
                "所选岗位包当前不可用于新面试："
                + "；".join(reason["message"] for reason in reasons),
                code=reasons[0]["code"],
                status_code=409,
            )
        return resolved.binding

    @staticmethod
    def selectability(
        resolved: ResolvedKnowledgePack,
    ) -> tuple[bool, list[dict[str, str]]]:
        reasons: list[dict[str, str]] = []
        review = resolved.review
        if review is None:
            reasons.append(
                {
                    "code": "PACK_REVIEW_PENDING",
                    "message": "格式已通过；负责人技术审核尚未登记。",
                }
            )
        elif review["decision"] == "rejected":
            reasons.append(
                {
                    "code": "PACK_REVIEW_REJECTED",
                    "message": "负责人审核未通过：" + review["note"],
                }
            )
        if not resolved.rules_reviewed and not reasons:
            reasons.append(
                {
                    "code": "PACK_RULES_REVIEW_PENDING",
                    "message": "能力规则尚未获绑定当前内容的 owner Level 1 / Level 2 审核。",
                }
            )
        return (not reasons), reasons

    def example_jd(self, requested_release_id: str | None) -> tuple[str, str]:
        """Only the selected pack's explicit example may supply an omitted JD."""
        release_id = requested_release_id or self._default_release_id
        if release_id is None:
            raise _error(
                "SERVICE_NOT_READY", "没有默认岗位包，请显式选包并提供 JD。", 503
            )
        resolved = self.resolve(release_id)
        if resolved.example_jd is None or not resolved.example_jd.strip():
            raise _error(
                "JD_REQUIRED", "所选岗位包未声明示例 JD，请提供 jd_text。", 422
            )
        return resolved.example_jd, example_jd_source_name(resolved.pack_id)

    # ---------------------------------------------------------------- 视图

    def list_view(self) -> dict[str, Any]:
        with Session(self._engine, expire_on_commit=False) as session:
            rows = list(
                session.scalars(
                    select(KnowledgePackRelease).order_by(
                        KnowledgePackRelease.created_at
                    )
                )
            )
            items = [
                self._verified_item(row, self.effective_review(session, row))[0]
                for row in rows
            ]
        return {
            "items": items,
            "default_pack_release_id": self._default_release_id,
            "import_limits": {
                "max_upload_bytes": self._limits.max_upload_bytes,
                "max_extracted_total_bytes": self._limits.max_extracted_total_bytes,
                "max_single_file_bytes": self._limits.max_single_file_bytes,
                "max_entries": self._limits.max_entries,
                "max_path_depth": self._limits.max_path_depth,
            },
        }

    def detail_view(self, release_id: str) -> dict[str, Any]:
        with Session(self._engine, expire_on_commit=False) as session:
            row = session.get(KnowledgePackRelease, release_id)
            if row is None:
                raise ResourceNotFoundError("岗位包 release 不存在。")
            review = self.effective_review(session, row)
            detail, files, integrity_error = self._verified_item(row, review)
        if files:
            try:
                sources = parse_sources(files)
                detail["sources"] = [_safe_source(record) for record in sources]
            except PackValidationError as exc:
                detail["sources"] = []
                integrity_error = exc.code
                detail["selectable"] = False
                detail["validation_status"] = str(ValidationStatus.FAILED)
                detail["blocked_reasons"].insert(
                    0,
                    {
                        "code": exc.code,
                        "message": "来源目录校验失败，该 release 不可用。",
                    },
                )
        else:
            detail["sources"] = []
        detail["validation_checks"] = list(row.validation_checks)
        if integrity_error:
            detail["validation_checks"].append(
                {
                    "check": "storage_integrity",
                    "status": "failed",
                    "detail": f"内容完整性异常：{integrity_error}",
                }
            )
        detail["limitations_note"] = (
            "格式通过、负责人审核与可用于新面试是三个独立状态；"
            "来源登记字段完整不代表内容已实查认证。"
        )
        return detail

    def _verified_item(
        self, row: KnowledgePackRelease, review: dict[str, Any] | None
    ) -> tuple[dict[str, Any], dict[str, bytes], str | None]:
        files: dict[str, bytes] = {}
        integrity_error = None
        try:
            files = self._load_canonical_files(row)
        except DomainError as exc:
            integrity_error = exc.code
        return (
            self._item_dict(row, review, integrity_error, files),
            files,
            integrity_error,
        )

    def _item_dict(
        self,
        row: KnowledgePackRelease,
        review: dict[str, Any] | None,
        integrity_error: str | None,
        files: dict[str, bytes],
    ) -> dict[str, Any]:
        """裁剪展示视图：绝不包含 rubric/reference_points/参考答案/Seed 正文。"""
        review_status = ReviewStatus.UNREVIEWED
        blocked: list[dict[str, str]] = []
        profile = None
        profile_digest = None
        if files:
            profile = parse_competency_profile(parse_competencies(files))
            profile_digest = "sha256:" + file_sha256(files["competencies.json"])
        rules_reviewed = profile is not None and self._rules_reviewed(
            review, profile, profile_digest
        )
        if integrity_error is not None:
            blocked.append(
                {
                    "code": integrity_error,
                    "message": f"内容完整性校验失败（{integrity_error}），该 release 不可用。",
                }
            )
        if review is None:
            blocked.append(
                {
                    "code": "PACK_REVIEW_PENDING",
                    "message": "格式已通过；负责人技术审核尚未登记。",
                }
            )
        elif review["decision"] == "rejected":
            review_status = ReviewStatus.REJECTED
            blocked.append(
                {"code": "PACK_REVIEW_REJECTED", "message": "负责人审核未通过。"}
            )
        else:
            review_status = ReviewStatus.APPROVED
        if review_status == ReviewStatus.APPROVED and not rules_reviewed:
            blocked.append(
                {
                    "code": "PACK_RULES_REVIEW_PENDING",
                    "message": "能力规则尚未获当前内容的 owner 两级审核。",
                }
            )
        selectable = row.validation_status == ValidationStatus.PASSED and not blocked
        scope_hashes: set[str] = set()
        if rules_reviewed and not integrity_error:
            scope_hashes = {
                entry["seed_content_sha256"] for entry in review["approved_seed_scope"]
            }
        capabilities: list[dict[str, Any]] = []
        if profile is not None:
            seed_index = row.manifest_snapshot.get("seed_index", [])
            for capability in profile.capabilities:
                covered = any(
                    (
                        entry["competency_id"] == capability.competency_id
                        or any(
                            rule[0] == capability.competency_id
                            and entry["competency_id"].startswith(rule[1])
                            for rule in profile.seed_family_rules
                        )
                    )
                    and entry["content_sha256"] in scope_hashes
                    for entry in seed_index
                )
                capabilities.append(
                    {
                        "competency_id": capability.competency_id,
                        "label": capability.label,
                        "technical_seed_available": covered,
                    }
                )
        approved = sum(
            entry["content_sha256"] in scope_hashes
            for entry in row.manifest_snapshot.get("seed_index", [])
        )
        review_summary = None
        if review is not None:
            review_summary = {
                "decision": review["decision"],
                "reviewer_role": review["reviewer_role"],
                "reviewed_at": review["reviewed_at"],
                "review_basis": review["reviewer_id"],
            }
        return {
            "pack_release_id": row.id,
            "pack_id": row.pack_id,
            "name": row.name,
            "version": row.version,
            "content_digest": row.content_digest,
            "format_version": row.format_version,
            "competency_profile_id": row.competency_profile_id,
            "profile_version": profile.profile_version if profile else None,
            "profile_digest": profile_digest,
            "rules_reviewed": bool(rules_reviewed),
            "scope_summary": row.supported_scope,
            "unsupported_scope": row.unsupported_scope,
            "validation_status": str(ValidationStatus.FAILED)
            if integrity_error
            else row.validation_status,
            "review_status": str(review_status),
            "selectable": selectable,
            "blocked_reasons": blocked,
            "seed_count": row.seed_count,
            "approved_seed_count": approved,
            "source_count": row.source_count,
            "capabilities": capabilities,
            "review_summary": review_summary,
        }

    def summary_for_interview(
        self,
        *,
        pack_release_id: str | None,
        pack_content_digest: str | None,
        competency_profile_id: str | None,
    ) -> dict[str, Any]:
        """Interview/Report 冻结摘要：不从“当前默认包”倒推历史绑定。"""
        if pack_release_id is None or pack_content_digest is None:
            return {
                "binding": "legacy_unresolved",
                "pack_release_id": None,
                "profile_version": None,
                "profile_digest": None,
                "capabilities": [],
                "note": (
                    "历史会话没有可证实的岗位包绑定；保留原报告与冻结题目，"
                    "继续新面试需重新创建计划并显式选择岗位包。"
                ),
            }
        name = version = pack_id = None
        profile_version = profile_digest = None
        capabilities: list[dict[str, str]] = []
        with Session(self._engine) as session:
            row = session.get(KnowledgePackRelease, pack_release_id)
            if row is not None and row.content_digest == pack_content_digest:
                name, version, pack_id = row.name, row.version, row.pack_id
                try:
                    files = self._load_canonical_files(row)
                    profile = parse_competency_profile(parse_competencies(files))
                    profile_version = profile.profile_version
                    profile_digest = "sha256:" + file_sha256(files["competencies.json"])
                    capabilities = [
                        {"competency_id": c.competency_id, "label": c.label}
                        for c in profile.capabilities
                    ]
                except (DomainError, ValueError):
                    # Stored questions/reports remain readable; do not guess labels.
                    pass
        return {
            "binding": "frozen"
            if profile_version is not None
            else "frozen_unavailable",
            "pack_release_id": pack_release_id,
            "pack_id": pack_id,
            "name": name,
            "version": version,
            "content_digest": pack_content_digest,
            "competency_profile_id": competency_profile_id,
            "profile_version": profile_version,
            "profile_digest": profile_digest,
            "capabilities": capabilities,
        }

    # ---------------------------------------------------------------- 导入回执

    def create_upload_receipt(self, zip_bytes: bytes) -> KnowledgePackImportReceipt:
        upload_sha256 = hashlib.sha256(zip_bytes).hexdigest()
        receipt_id = new_id("kpi")
        self._uploads_root().mkdir(parents=True, exist_ok=True)
        relative = f"knowledge_packs/uploads/{receipt_id}.zip"
        (self._runtime_dir / relative).write_bytes(zip_bytes)
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            receipt = KnowledgePackImportReceipt(
                id=receipt_id,
                upload_sha256=upload_sha256,
                storage_path=relative,
            )
            session.add(receipt)
        return receipt

    def discard_upload_receipt(self, receipt_id: str) -> None:
        """受理失败/竞争回滚清理：回执行与字节同删，不留半状态。"""
        with Session(self._engine) as session, session.begin():
            receipt = session.get(KnowledgePackImportReceipt, receipt_id)
            relative = receipt.storage_path if receipt is not None else None
            if receipt is not None:
                session.delete(receipt)
        if relative is not None:
            (self._runtime_dir / relative).unlink(missing_ok=True)

    def read_receipt_upload(self, receipt_id: str) -> bytes:
        """Operation 主体取回上传字节；输入丢失/损坏显式失败，不假成功。"""
        with Session(self._engine) as session:
            receipt = session.get(KnowledgePackImportReceipt, receipt_id)
            if receipt is None:
                raise ResourceNotFoundError("导入回执不存在。")
            relative = receipt.storage_path
            expected_sha = receipt.upload_sha256
        path = self._runtime_dir / relative
        if not path.is_file():
            raise _error(
                "PACK_UPLOAD_INPUT_LOST",
                "后台输入已不可用；请重新选择同一文件，"
                "服务端会按内容摘要复用已有 release，不重复登记。",
                503,
            )
        zip_bytes = path.read_bytes()
        if hashlib.sha256(zip_bytes).hexdigest() != expected_sha:
            raise _error("PACK_UPLOAD_INPUT_CORRUPTED", "上传字节与登记摘要不符。", 503)
        return zip_bytes

    def complete_import_receipt(
        self, receipt_id: str, outcome: ImportOutcome
    ) -> KnowledgePackImportReceipt:
        """成功规则：release 已登记 → 回执指向它并清理原始上传字节。"""
        with Session(self._engine, expire_on_commit=False) as session, session.begin():
            receipt = session.get(KnowledgePackImportReceipt, receipt_id)
            if receipt is None:
                raise ResourceNotFoundError("导入回执不存在。")
            receipt.release_id = outcome.release.id
            receipt.reused_release = outcome.reused
            receipt.updated_at = utc_now_rfc3339()
            path = self._runtime_dir / receipt.storage_path
        path.unlink(missing_ok=True)
        return receipt

    def sweep_orphan_uploads(self) -> int:
        """启动清理：删除没有回执行的孤儿上传（崩溃在登记前的残留）。"""
        uploads = self._uploads_root()
        if not uploads.is_dir():
            return 0
        with Session(self._engine) as session:
            known = {
                receipt.id
                for receipt in session.scalars(select(KnowledgePackImportReceipt))
            }
        removed = 0
        for stale in uploads.glob("*.zip"):
            if stale.stem not in known:
                stale.unlink(missing_ok=True)
                removed += 1
        # 已登记成功的回执字节在 complete 时删除；失败回执的字节保留给
        # 有限、parent-linked 的重试，不无限自动重放。
        return removed


def _safe_source(record: dict[str, Any]) -> dict[str, Any]:
    """来源记录裁剪视图：URL 已过协议白名单；展示专用，不自动抓取。"""
    allowed = (
        "source_id",
        "title",
        "publisher",
        "edition",
        "locator",
        "recorded_at",
        "url",
        "local_identifier",
        "redistribution_boundary",
        "review_record_id",
        "note",
    )
    view = {key: record.get(key) for key in allowed}
    view["record_status_only"] = True
    return view
