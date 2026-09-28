"""结构化岗位知识包服务：注册、导入、解析与面试冻结（主文件 Phase 3/4.5/5.1）。

职责边界：

- 这是对既有资源（SeedBank/能力配置/来源登记）的**加载与信任边界**，
  不是第二套 Knowledge 引擎；候选人 Knowledge 仍走 openJiuwen 原路径。
- 包内任何 `approved` 只是作者声明。服务端有效审核 = 绑定当前
  `content_digest` 的包外审核记录 ∩ Seed 内容 hash 范围 ∩ 声明状态门槛。
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
    get_registered_profile,
    match_registered_profile,
)
from zhijue.domain.errors import DomainError, ResourceNotFoundError
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
    parse_competencies,
    parse_manifest,
    parse_sources,
    release_id_for,
    safe_extract_zip,
    seed_content_hash,
    strict_json_loads,
)

# 内置六条 Seed 的历史批准记录（M2-01 负责人结论）。ensure_builtin 只登记
# “可审计映射”：同一批字节内容、同一记录 ID，不新增批准范围。
BUILTIN_REVIEW_RECORD_ID = "review_m2_01_level2_owner_20260919"
BUILTIN_PACK_STORAGE_ROOT = "knowledge_packs/embedded_software_junior"
# 历史批准白名单：内置迁移只继承这六条 ID（docs/reviews/review_m2_01_*）。
# 内置目录新增 Seed 不会自动获批——那需要负责人经 CLI 走新一轮审核。
BUILTIN_APPROVED_SEED_IDS = frozenset(
    {
        "seed_embedded_freertos_queue_mechanism",
        "seed_embedded_interrupt_priority",
        "seed_embedded_mutex_vs_semaphore",
        "seed_embedded_rtos_task_period",
        "seed_embedded_spi_i2c_selection",
        "seed_embedded_uart_dma_debug",
    }
)


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
    seed_bank: SeedBank
    sources: tuple[dict[str, Any], ...]
    review: dict[str, Any] | None
    binding: InterviewPackBinding


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
        profile = match_registered_profile(parse_competencies(files))
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
                f"声明镜像与注册表 {profile.profile_id} 一致",
            ),
        ]
        seed_index = self._validate_seeds(files, manifest, sources, checks)
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
        checks.append(
            ValidationCheck(
                "seeds_schema",
                ValidationStatus.PASSED,
                f"{len(index)} 条 Seed 通过契约校验；引用均可解析到来源登记",
            )
        )
        return index

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
        """把仓库内置资产登记为 release，并映射负责人历史批准范围。

        只继承 M2-01 已批准六条的范围（逐条内容 hash）；任何新增/改写
        内容不会因此获得批准。同摘要幂等复用；异摘要冲突属于资产变更，
        必须走新的审核而不是静默重批。
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
                    and entry["seed_id"] in BUILTIN_APPROVED_SEED_IDS
                ]
                if len(scope) != len(BUILTIN_APPROVED_SEED_IDS):
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
                    if entry["declared_review_status"] != "approved":
                        raise _error(
                            "PACK_REVIEW_SCOPE_INVALID",
                            f"Seed {entry['seed_id']} 包内声明未达 approved；"
                            "批准范围只覆盖两级审核通过的原文。",
                            422,
                        )
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
                reviewed_at=utc_now_rfc3339(),
            )
            session.add(review)
            row.approved_seed_count = self._recompute_approved_count(session, row)
            return self.effective_review(session, row) or {}

    def _recompute_approved_count(
        self, session: Session, row: KnowledgePackRelease
    ) -> int:
        review = self.effective_review(session, row)
        if review is None or review["decision"] != "approved":
            return 0
        scope = {
            entry["seed_content_sha256"] for entry in review["approved_seed_scope"]
        }
        threshold = REVIEW_RANK[self._live_allowed_review_status]
        return sum(
            1
            for entry in row.manifest_snapshot.get("seed_index", [])
            if entry["content_sha256"] in scope
            and REVIEW_RANK.get(entry["declared_review_status"], -1) >= threshold
        )

    # ---------------------------------------------------------------- 解析边界

    def resolve(self, release_id: str) -> ResolvedKnowledgePack:
        """加载边界：重算摘要、应用服务端审核范围，返回只读资源包。"""
        with Session(self._engine, expire_on_commit=False) as session:
            row = session.get(KnowledgePackRelease, release_id)
            if row is None:
                raise ResourceNotFoundError("岗位包 release 不存在。")
            review = self.effective_review(session, row)
        files = self._load_canonical_files(row)
        profile = get_registered_profile(row.competency_profile_id)
        manifest = parse_manifest(files)
        match_registered_profile(parse_competencies(files))
        sources = parse_sources(files)
        # seed_id → 内容 hash 的唯一权威映射来自与摘要一起校验过的文件本体。
        hash_by_seed_id: dict[str, str] = {}
        payloads: dict[str, Any] = {}
        for seed_path in manifest.seeds:
            payload = strict_json_loads(
                files[seed_path].decode("utf-8"), path=seed_path
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
        scope_hashes: set[str] = set()
        if review is not None and review["decision"] == "approved":
            scope_hashes = {
                entry["seed_content_sha256"] for entry in review["approved_seed_scope"]
            }
        threshold = REVIEW_RANK[self._live_allowed_review_status]
        eligible = [
            seed
            for seed in full_bank.seeds
            if hash_by_seed_id.get(seed.id) in scope_hashes
            and REVIEW_RANK.get(seed.review_status, -1) >= threshold
        ]
        bank = SeedBank(
            eligible,
            schema_version=full_bank.schema_version,
            live_allowed_review_status=self._live_allowed_review_status,
        )
        binding = InterviewPackBinding(
            release_id=row.id,
            pack_id=row.pack_id,
            version=row.version,
            content_digest=row.content_digest,
            competency_profile_id=row.competency_profile_id,
            seed_bank_version=bank.version_fingerprint(),
        )
        return ResolvedKnowledgePack(
            release_id=row.id,
            pack_id=row.pack_id,
            version=row.version,
            name=row.name,
            content_digest=row.content_digest,
            profile=profile,
            seed_bank=bank,
            sources=sources,
            review=review,
            binding=binding,
        )

    def freeze_for_new_plan(
        self, requested_release_id: str | None
    ) -> InterviewPackBinding:
        """计划请求受理时的冻结解析（主文件 5.1）：只接受 selectable 的 release。"""
        release_id = requested_release_id
        if release_id is None:
            with Session(self._engine) as session:
                row = session.scalar(
                    select(KnowledgePackRelease)
                    .where(KnowledgePackRelease.pack_id == self._default_pack_id)
                    .order_by(KnowledgePackRelease.created_at.desc())
                )
                if row is None:
                    raise _error(
                        "SERVICE_NOT_READY",
                        "没有可解析的内置岗位包；面试计划能力未就绪，"
                        "岗位包管理仍可用。",
                        503,
                    )
                release_id = row.id
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
        return (not reasons), reasons

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
                self._item_dict(row, self.effective_review(session, row))
                for row in rows
            ]
            default = session.scalar(
                select(KnowledgePackRelease)
                .where(KnowledgePackRelease.pack_id == self._default_pack_id)
                .order_by(KnowledgePackRelease.created_at.desc())
            )
        return {
            "items": items,
            "default_pack_release_id": default.id if default is not None else None,
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
            base = self._item_dict(row, review)
        detail = dict(base)
        integrity_error: str | None = None
        files: dict[str, bytes] = {}
        try:
            files = self._load_canonical_files(row)
        except DomainError as exc:
            integrity_error = exc.code
        if files:
            try:
                sources = parse_sources(files)
                detail["sources"] = [_safe_source(record) for record in sources]
            except PackValidationError as exc:
                detail["sources"] = []
                integrity_error = integrity_error or exc.code
        else:
            detail["sources"] = []
        detail["validation_checks"] = list(row.validation_checks)
        if integrity_error:
            detail["validation_checks"] = detail["validation_checks"] + [
                {
                    "check": "storage_integrity",
                    "status": "failed",
                    "detail": f"内容完整性异常：{integrity_error}",
                }
            ]
        detail["limitations_note"] = (
            "格式通过、负责人审核与可用于新面试是三个独立状态；"
            "来源登记字段完整不代表内容已实查认证。"
        )
        return detail

    def _item_dict(
        self, row: KnowledgePackRelease, review: dict[str, Any] | None
    ) -> dict[str, Any]:
        """裁剪展示视图：绝不包含 rubric/reference_points/参考答案/Seed 正文。"""
        review_status = ReviewStatus.UNREVIEWED
        blocked: list[dict[str, str]] = []
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
        selectable = row.validation_status == ValidationStatus.PASSED and not blocked
        scope_hashes: set[str] = set()
        if review is not None and review["decision"] == "approved":
            scope_hashes = {
                entry["seed_content_sha256"] for entry in review["approved_seed_scope"]
            }
        capabilities: list[dict[str, Any]] = []
        try:
            profile = get_registered_profile(row.competency_profile_id)
        except ValueError:
            selectable = False
            blocked.append(
                {
                    "code": "COMPETENCY_PROFILE_UNSUPPORTED",
                    "message": "能力配置未在服务端注册。",
                }
            )
            profile = None
        if profile is not None:
            threshold = REVIEW_RANK[self._live_allowed_review_status]
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
                    and REVIEW_RANK.get(entry["declared_review_status"], -1)
                    >= threshold
                    for entry in seed_index
                )
                capabilities.append(
                    {
                        "competency_id": capability.competency_id,
                        "label": capability.label,
                        "technical_seed_available": covered,
                    }
                )
        approved = row.approved_seed_count if scope_hashes else 0
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
            "scope_summary": row.supported_scope,
            "unsupported_scope": row.unsupported_scope,
            "validation_status": row.validation_status,
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
                "note": (
                    "历史会话没有可证实的岗位包绑定；保留原报告与冻结题目，"
                    "继续新面试需重新创建计划并显式选择岗位包。"
                ),
            }
        name = version = pack_id = None
        with Session(self._engine) as session:
            row = session.get(KnowledgePackRelease, pack_release_id)
            if row is not None and row.content_digest == pack_content_digest:
                name, version, pack_id = row.name, row.version, row.pack_id
        return {
            "binding": "frozen" if pack_id is not None else "frozen_unavailable",
            "pack_release_id": pack_release_id,
            "pack_id": pack_id,
            "name": name,
            "version": version,
            "content_digest": pack_content_digest,
            "competency_profile_id": competency_profile_id,
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
