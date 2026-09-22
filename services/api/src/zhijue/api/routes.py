"""HTTP 路由（api.md §4）：/profiles、/facts、/confirm、/documents、/operations、/health。

这里只做 HTTP 语义：DTO 校验、契约错误映射、operation 受理与 202 返回。
业务规则在 application 层，HTTP 层不重写一遍。
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import platform
from importlib.metadata import version
from typing import Any

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Form,
    Header,
    Query,
    Request,
    UploadFile,
)

from zhijue.adapters.db.operations import (
    OperationCommand,
    OperationRepository,
    canon_scope,
)
from zhijue.api.errors import ApiError, RequestContext, envelope
from zhijue.api.schemas import (
    AcceptResumeDraftRequest,
    ActivateProfileRequest,
    ConfirmRequest,
    ControlInterviewRequest,
    CreateInterviewRequest,
    CreateProfileRequest,
    CreateResumeDraftRequest,
    FactsRequest,
    GenerateCoachingRequest,
    OperationAccepted,
    ProfileClaim,
    ProfileDocumentView,
    ProfileViewDto,
    RetryOperationRequest,
    StartInterviewRequest,
    SubmitAnswerRequest,
)
from zhijue.application.documents import DocumentService
from zhijue.application.operations_runner import OperationJob
from zhijue.application.profiles import ProfileService
from zhijue.domain.ids import new_id
from zhijue.domain.requisition import JDSourceType

router = APIRouter(prefix="/api/v1")
logger = logging.getLogger("zhijue.routes")

WORKSPACE_ID = "local"


def _ctx(request: Request) -> RequestContext:
    return request.state.context


def _require_idempotency_key(value: str | None) -> str:
    if value is None:
        raise ApiError(
            status_code=400,
            code="INVALID_REQUEST",
            message="创建异步操作必须携带 Idempotency-Key。",
        )
    if not 8 <= len(value) <= 128:
        raise ApiError(
            status_code=400,
            code="INVALID_REQUEST",
            message="Idempotency-Key 长度必须为 8—128。",
        )
    return value


async def _release_after_failure(release: Any, operation_id: str) -> None:
    """Best-effort resource cleanup without replacing the operation's root failure."""
    try:
        await asyncio.to_thread(release, operation_id)
    except Exception as cleanup_error:  # noqa: BLE001 - original error must survive.
        logger.error(
            "operation %s cleanup failed after primary failure: %s",
            operation_id,
            type(cleanup_error).__name__,
        )


def _claims(
    service: ProfileService, profile_id: str, status: str
) -> list[ProfileClaim]:
    return [
        ProfileClaim(
            id=claim.id,
            text=claim.text,
            status=claim.status.value,
            source_block_ids=claim.source_block_ids,
            source_quotes=claim.source_quotes,
            supersedes_id=claim.supersedes_id,
        )
        for claim in service.list_claims(profile_id)
        if claim.status.value == status
    ]


def _profile_view(
    request: Request,
    service: ProfileService,
    document_service: DocumentService,
    profile_id: str,
) -> ProfileViewDto:
    profile = service.get_profile(profile_id)
    return ProfileViewDto(
        id=profile.id,
        revision=profile.revision,
        display_name=profile.display_name,
        synthetic=profile.synthetic,
        status=profile.status,
        documents=[
            ProfileDocumentView(
                id=doc.id,
                kind=doc.kind,
                filename_display=doc.filename_display,
                sha256=doc.sha256,
                page_count=doc.page_count,
                extract_status=doc.extract_status,
                index_status=doc.index_status,
                warnings=list(doc.warnings or []),
            )
            for doc in document_service.list_documents(profile_id)
        ],
        proposed_claims=_claims(service, profile_id, "proposed"),
        confirmed_claims=_claims(service, profile_id, "confirmed"),
        latest_snapshot_id=profile.latest_snapshot_id,
        active_operation_id=profile.active_operation_id,
        snapshot_activation=profile.snapshot_activation,
    )


@router.post("/profiles", status_code=201)
def create_profile(payload: CreateProfileRequest, request: Request) -> dict[str, Any]:
    services = request.app.state.services
    profile = services.profiles.create_profile(
        display_name=payload.display_name, synthetic=payload.synthetic
    )
    return envelope(
        _profile_view(
            request, services.profiles, services.documents, profile.id
        ).model_dump(),
        _ctx(request).request_id,
    )


@router.get("/profiles/{profile_id}")
def get_profile(profile_id: str, request: Request) -> dict[str, Any]:
    services = request.app.state.services
    body = _profile_view(request, services.profiles, services.documents, profile_id)
    return envelope(body.model_dump(), _ctx(request).request_id)


@router.post("/profiles/{profile_id}/facts", status_code=201)
def add_facts(
    profile_id: str, payload: FactsRequest, request: Request
) -> dict[str, Any]:
    services = request.app.state.services
    services.profiles.add_facts(
        profile_id,
        expected_revision=payload.expected_revision,
        items=[item.model_dump() for item in payload.items],
    )
    body = _profile_view(request, services.profiles, services.documents, profile_id)
    return envelope(body.model_dump(), _ctx(request).request_id)


@router.post("/profiles/{profile_id}/confirm", status_code=202)
def confirm(
    profile_id: str,
    payload: ConfirmRequest,
    request: Request,
    background: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """写快照是同步业务写；Knowledge 激活异步执行（api.md §4：202 OperationAccepted）。"""
    key = _require_idempotency_key(idempotency_key)
    services = request.app.state.services
    decisions = [decision.model_dump() for decision in payload.decisions]
    scope = canon_scope(WORKSPACE_ID, "POST", f"/api/v1/profiles/{profile_id}/confirm")
    accepted = services.profiles.accept_confirmation(
        profile_id,
        expected_revision=payload.expected_revision,
        decisions=decisions,
        capacity_available=services.runner.capacity_available,
        command=OperationCommand(
            kind="profile.confirm",
            resource_type="profile",
            resource_id=profile_id,
            scope=scope,
            idempotency_key=key,
            input={
                "profile_id": profile_id,
                "expected_revision": payload.expected_revision,
                "decisions": decisions,
            },
        ),
    )
    _schedule_profile_activation(services, background, accepted)
    return envelope(
        _accepted(accepted.operation).model_dump(), _ctx(request).request_id
    )


@router.post("/profiles/{profile_id}/activate", status_code=202)
def activate_profile(
    profile_id: str,
    payload: ActivateProfileRequest,
    request: Request,
    background: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    key = _require_idempotency_key(idempotency_key)
    services = request.app.state.services
    accepted = services.profiles.accept_activation(
        profile_id,
        expected_revision=payload.expected_revision,
        capacity_available=services.runner.capacity_available,
        command=OperationCommand(
            kind="profile.activate",
            resource_type="profile",
            resource_id=profile_id,
            scope=canon_scope(
                WORKSPACE_ID, "POST", f"/api/v1/profiles/{profile_id}/activate"
            ),
            idempotency_key=key,
            input={"profile_id": profile_id, **payload.model_dump()},
        ),
    )
    _schedule_profile_activation(services, background, accepted)
    return envelope(
        _accepted(accepted.operation).model_dump(), _ctx(request).request_id
    )


@router.delete("/profiles/{profile_id}", status_code=202)
def delete_profile(
    profile_id: str,
    request: Request,
    background: BackgroundTasks,
    expected_revision: int = Query(..., alias="expected_revision", ge=0),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """api.md §4：先 tombstone，再异步清理档案/关联资料/索引/会话。

    删除不可恢复；profile.delete 回执 Operation 是唯一留存痕迹。
    """
    key = _require_idempotency_key(idempotency_key)
    services = request.app.state.services
    accepted = services.profiles.accept_deletion(
        profile_id,
        expected_revision=expected_revision,
        capacity_available=services.runner.capacity_available,
        command=OperationCommand(
            kind="profile.delete",
            resource_type="profile",
            resource_id=profile_id,
            scope=canon_scope(WORKSPACE_ID, "DELETE", f"/api/v1/profiles/{profile_id}"),
            idempotency_key=key,
            input={"profile_id": profile_id, "expected_revision": expected_revision},
        ),
    )
    _schedule_profile_deletion(services, background, accepted)
    return envelope(
        _accepted(accepted.operation).model_dump(), _ctx(request).request_id
    )


def _schedule_profile_activation(
    services: Any, background: BackgroundTasks, accepted: Any
) -> None:
    if not accepted.created:
        return
    operation = accepted.operation

    async def _run() -> dict[str, Any]:
        return await services.profiles.process_activation(operation.id)

    background.add_task(
        services.runner.submit,
        OperationJob(
            operation_id=operation.id,
            kind=operation.kind,
            resource_id=operation.resource_id,
            run=_run,
        ),
    )


def _schedule_profile_deletion(
    services: Any, background: BackgroundTasks, accepted: Any
) -> None:
    if not accepted.created:
        return
    operation = accepted.operation

    async def _run() -> dict[str, Any]:
        return await services.profiles.process_deletion(
            profile_id=operation.resource_id
        )

    background.add_task(
        services.runner.submit,
        OperationJob(
            operation_id=operation.id,
            kind=operation.kind,
            resource_id=operation.resource_id,
            run=_run,
        ),
    )


@router.get("/operations/{operation_id}")
def get_operation(operation_id: str, request: Request) -> dict[str, Any]:
    services = request.app.state.services
    operation = services.operations.get(operation_id)
    if operation is None:
        raise ApiError(
            status_code=404, code="RESOURCE_NOT_FOUND", message="操作不存在。"
        )
    return envelope(
        {
            "id": operation.id,
            "kind": operation.kind,
            "status": operation.status,
            "resource_type": operation.resource_type,
            "resource_id": operation.resource_id,
            "parent_operation_id": operation.parent_operation_id,
            "attempts": operation.attempts,
            "result": operation.result,
            "error": operation.error,
            "last_event_seq": operation.last_event_seq,
            "created_at": operation.created_at,
            "updated_at": operation.updated_at,
        },
        _ctx(request).request_id,
    )


@router.get("/health/live")
def health_live(request: Request) -> dict[str, Any]:
    return envelope({"status": "ok"}, _ctx(request).request_id)


@router.get("/health/ready")
def health_ready(
    request: Request, response_status: int = Query(default=0)
) -> dict[str, Any]:
    """readiness 只检查已初始化依赖，不每请求调用付费模型（api.md §7）。"""
    services = request.app.state.services
    ready = services.ready
    if not ready:
        from fastapi.responses import JSONResponse

        return JSONResponse(  # type: ignore[return-value]
            status_code=503,
            content={
                "error": {
                    "code": "SERVICE_NOT_READY",
                    "message": "依赖未就绪。",
                    "retryable": True,
                    "details": services.readiness_details(),
                },
                "meta": {"request_id": _ctx(request).request_id},
            },
        )
    return envelope(
        {"status": "ok", **services.readiness_details()}, _ctx(request).request_id
    )


@router.get("/runtime/info")
def runtime_info(request: Request) -> dict[str, Any]:
    """api.md §7：运行事实 = 模式、锁定版本、特性开关、依赖健康摘要。

    不含密钥、内部路径或档案数据。feature_flags 是事实而非可配置项：
    OCR/记忆/外网等能力在本 Demo 没有实现代码，取值与 demo.yaml 规范默认一致。
    """
    services = request.app.state.services
    readiness = services.readiness_details()
    return envelope(
        {
            "run_mode": readiness.get("run_mode"),
            "data_mode": readiness.get("data_mode"),
            "versions": {
                "python": platform.python_version(),
                "openjiuwen": version("openjiuwen"),
                "pymilvus": version("pymilvus"),
                "seed_bank_version": readiness.get("seed_bank_version"),
            },
            "feature_flags": {
                "ocr_enabled": False,
                "memory_enabled": False,
                "external_web_enabled": False,
                "observer_mode_default": False,
                "remote_public_access_enabled": False,
            },
            "health_summary": {
                "database": readiness.get("database"),
                "knowledge": readiness.get("knowledge"),
                "model": readiness.get("model"),
            },
        },
        _ctx(request).request_id,
    )


def operation_repository_for(request: Request) -> OperationRepository:
    return request.app.state.services.operations


@router.post("/profiles/{profile_id}/documents", status_code=202)
async def upload_document(
    profile_id: str,
    request: Request,
    background: BackgroundTasks,
    file: UploadFile,
    kind: str = Form(...),
    expected_revision: int = Form(...),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """multipart 上传：先校验并保存，解析/索引异步完成（api.md §4）。"""
    key = _require_idempotency_key(idempotency_key)
    services = request.app.state.services
    data = await file.read()
    body = {
        "profile_id": profile_id,
        "kind": kind,
        "expected_revision": expected_revision,
        # 文件 bytes hash 参与幂等输入（api.md §1：不使用 multipart boundary）。
        "document_sha256": hashlib.sha256(data).hexdigest(),
        "size": len(data),
    }
    scope = canon_scope(
        WORKSPACE_ID, "POST", f"/api/v1/profiles/{profile_id}/documents"
    )
    operation, created = services.operations.accept_queued(
        OperationCommand(
            kind="document.import",
            resource_type="profile",
            resource_id=profile_id,
            scope=scope,
            idempotency_key=key,
            input=body,
        ),
        capacity_available=services.runner.capacity_available,
    )
    if not created:
        return envelope(_accepted(operation).model_dump(), _ctx(request).request_id)

    async def _run() -> dict[str, Any]:
        return await _import_and_activate(
            services,
            profile_id=profile_id,
            data=data,
            filename=file.filename or "上传材料",
            kind=kind,
            expected_revision=expected_revision,
        )

    background.add_task(
        services.runner.submit,
        OperationJob(
            operation_id=operation.id,
            kind=operation.kind,
            resource_id=profile_id,
            run=_run,
        ),
    )
    return envelope(_accepted(operation).model_dump(), _ctx(request).request_id)


def _accepted(operation: Any) -> OperationAccepted:
    return OperationAccepted(
        operation_id=operation.id,
        resource_type=operation.resource_type,
        resource_id=operation.resource_id,
        status=operation.status,
        events_url=f"/api/v1/operations/{operation.id}/events",
    )


async def _import_and_activate(
    services: Any,
    *,
    profile_id: str,
    data: bytes,
    filename: str,
    kind: str,
    expected_revision: int,
) -> dict[str, Any]:
    """Import → P-EXTRACT → atomic Document/Claim/revision commit.

    The user still decides whether every proposed Claim is accepted. Knowledge
    activation remains behind that explicit confirmation boundary.
    """
    imported = await asyncio.to_thread(
        services.documents.import_document,
        profile_id=profile_id,
        expected_revision=expected_revision,
        data=data,
        filename=filename,
        kind=kind,
    )
    document = imported.document
    return {
        "resource_revision": imported.resource_revision,
        "document_id": document.id,
        "extract_status": document.extract_status,
        "index_status": document.index_status,
        "proposed_claim_count": imported.proposed_claim_count,
        "extraction_metadata": imported.extraction_metadata,
    }


@router.get("/documents/{document_id}")
def get_document(document_id: str, request: Request) -> dict[str, Any]:
    services = request.app.state.services
    document = services.documents.get_document(document_id)
    if document is None:
        raise ApiError(
            status_code=404, code="RESOURCE_NOT_FOUND", message="材料不存在。"
        )
    return envelope(
        ProfileDocumentView(
            id=document.id,
            kind=document.kind,
            filename_display=document.filename_display,
            sha256=document.sha256,
            page_count=document.page_count,
            extract_status=document.extract_status,
            index_status=document.index_status,
            warnings=list(document.warnings or []),
        ).model_dump(),
        _ctx(request).request_id,
    )


@router.get("/documents/{document_id}/blocks")
def get_document_blocks(
    document_id: str,
    request: Request,
    cursor: str | None = Query(default=None),
    limit: int = Query(default=20),
) -> dict[str, Any]:
    services = request.app.state.services
    if services.documents.get_document(document_id) is None:
        raise ApiError(
            status_code=404, code="RESOURCE_NOT_FOUND", message="材料不存在。"
        )
    page = services.documents.list_blocks(document_id, cursor=cursor, limit=limit)
    return envelope(
        {
            "items": [
                {
                    "id": block.id,
                    "document_id": block.document_id,
                    "page_number": block.page_number,
                    "block_index": block.block_index,
                    "text": block.text,
                    "text_hash": block.text_hash,
                    "origin": block.origin,
                }
                for block in page.items
            ],
            "next_cursor": page.next_cursor,
        },
        _ctx(request).request_id,
    )


# ---- M2-02：JD 与五题计划（卡面：固定快照 + 生成五题计划，成功 ready）----

PRESET_JD_SOURCE = "SYNTHETIC_DEMO_JD_preset_embedded_junior"
USER_JD_SOURCE = "USER_PROVIDED_JD"


def _preset_jd_path() -> Any:
    from pathlib import Path

    here = Path(__file__).resolve()
    for candidate in here.parents:
        path = candidate / "data/jd/preset_embedded_junior.txt"
        if path.is_file():
            return path
    raise ApiError(
        status_code=503,
        code="SERVICE_NOT_READY",
        message="合成 Demo JD 不可用，请显式提供 jd_text。",
        retryable=True,
    )


@router.post("/interviews", status_code=202)
def create_interview(
    payload: CreateInterviewRequest,
    request: Request,
    background: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """固定资料快照并生成五题计划（api.md §6）。

    规划只声明"验证什么"，不生成题目文本、不绑定未批准种子（M2-02 决策 §4）。
    """
    key = _require_idempotency_key(idempotency_key)
    services = request.app.state.services
    if payload.role_preset != "embedded_junior":
        raise ApiError(
            status_code=422,
            code="SCHEMA_VALIDATION_FAILED",
            message="P0 仅支持 role_preset=embedded_junior。",
        )

    jd_text = payload.jd_text
    if jd_text is None:
        path = _preset_jd_path()
        jd_text = path.read_text(encoding="utf-8")
        source_name = PRESET_JD_SOURCE
        jd_source_type = JDSourceType.SYNTHETIC_DEMO_JD
    else:
        source_name = payload.jd_source_name or USER_JD_SOURCE
        jd_source_type = JDSourceType.USER_PROVIDED
    # 客户端可据此 GET /interviews/{id}（操作进行中为 404，完成后为 ready）。
    interview_id = new_id("interview")
    scope = canon_scope(WORKSPACE_ID, "POST", "/api/v1/interviews")
    accepted = services.interviews.accept_plan(
        profile_id=payload.profile_id,
        expected_revision=payload.profile_revision,
        capacity_available=services.runner.capacity_available,
        command=OperationCommand(
            kind="interview.plan",
            resource_type="interview",
            resource_id=interview_id,
            scope=scope,
            idempotency_key=key,
            input={
                "profile_id": payload.profile_id,
                "expected_revision": payload.profile_revision,
                "jd_sha256": hashlib.sha256(jd_text.encode("utf-8")).hexdigest(),
                "jd_source_name": source_name,
                "jd_source_type": jd_source_type.value,
            },
        ),
    )
    operation = accepted.operation
    if not accepted.created:
        return envelope(_accepted(operation).model_dump(), _ctx(request).request_id)

    async def _run() -> dict[str, Any]:
        return await asyncio.to_thread(
            services.interviews.create_plan,
            interview_id=interview_id,
            profile_id=payload.profile_id,
            expected_revision=payload.profile_revision,
            jd_text=jd_text,
            jd_source_name=source_name,
            jd_source_type=jd_source_type,
            seed_bank_version=services.readiness_details().get(
                "seed_bank_version", "seed_bank_unavailable"
            ),
            run_mode=services.config.run_mode,
        )

    background.add_task(
        services.runner.submit,
        OperationJob(
            operation_id=operation.id,
            kind=operation.kind,
            resource_id=operation.resource_id,
            run=_run,
        ),
    )
    return envelope(_accepted(operation).model_dump(), _ctx(request).request_id)


@router.get("/interviews/{interview_id}")
def get_interview(interview_id: str, request: Request) -> dict[str, Any]:
    services = request.app.state.services
    view = services.interviews.get_view(interview_id)
    if view is None:
        raise ApiError(
            status_code=404, code="RESOURCE_NOT_FOUND", message="面试不存在。"
        )
    return envelope(view, _ctx(request).request_id)


@router.post("/interviews/{interview_id}/start", status_code=202)
def start_interview(
    interview_id: str,
    payload: StartInterviewRequest,
    request: Request,
    background: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    key = _require_idempotency_key(idempotency_key)
    services = request.app.state.services
    accepted = services.interviews.accept_start(
        interview_id,
        expected_revision=payload.expected_revision,
        command=OperationCommand(
            kind="interview.start",
            resource_type="interview",
            resource_id=interview_id,
            scope=canon_scope(
                WORKSPACE_ID,
                "POST",
                f"/api/v1/interviews/{interview_id}/start",
            ),
            idempotency_key=key,
            input=payload.model_dump(),
        ),
        capacity_available=services.runner.capacity_available,
    )
    if accepted.created:

        async def _run() -> dict[str, Any]:
            try:
                return await asyncio.to_thread(
                    services.interviews.start_interview,
                    interview_id=interview_id,
                    operation_id=accepted.operation.id,
                )
            except Exception:
                await _release_after_failure(
                    services.interviews.release_failed_operation,
                    accepted.operation.id,
                )
                raise

        background.add_task(
            services.runner.submit,
            OperationJob(
                operation_id=accepted.operation.id,
                kind=accepted.operation.kind,
                resource_id=interview_id,
                run=_run,
            ),
        )
    return envelope(
        _accepted(accepted.operation).model_dump(),
        _ctx(request).request_id,
    )


@router.post("/interviews/{interview_id}/answers", status_code=202)
def submit_answer(
    interview_id: str,
    payload: SubmitAnswerRequest,
    request: Request,
    background: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    key = _require_idempotency_key(idempotency_key)
    services = request.app.state.services
    accepted = services.interviews.accept_answer(
        interview_id,
        expected_revision=payload.expected_revision,
        question_id=payload.question_id,
        client_turn_id=payload.client_turn_id,
        answer_text=payload.answer_text,
        command=OperationCommand(
            kind="interview.answer",
            resource_type="interview",
            resource_id=interview_id,
            scope=canon_scope(
                WORKSPACE_ID,
                "POST",
                f"/api/v1/interviews/{interview_id}/answers",
            ),
            idempotency_key=key,
            input=payload.model_dump(),
        ),
        capacity_available=services.runner.capacity_available,
    )
    if accepted.created:

        async def _run() -> dict[str, Any]:
            try:
                return await services.interviews.process_answer(
                    operation_id=accepted.operation.id
                )
            except Exception:
                await _release_after_failure(
                    services.interviews.release_failed_operation,
                    accepted.operation.id,
                )
                raise

        background.add_task(
            services.runner.submit,
            OperationJob(
                operation_id=accepted.operation.id,
                kind=accepted.operation.kind,
                resource_id=interview_id,
                run=_run,
            ),
        )
    return envelope(
        _accepted(accepted.operation).model_dump(),
        _ctx(request).request_id,
    )


@router.post("/interviews/{interview_id}/control", status_code=202)
def control_interview(
    interview_id: str,
    payload: ControlInterviewRequest,
    request: Request,
    background: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    key = _require_idempotency_key(idempotency_key)
    services = request.app.state.services
    accepted = services.interviews.accept_control(
        interview_id,
        expected_revision=payload.expected_revision,
        action=payload.action,
        command=OperationCommand(
            kind=f"interview.control.{payload.action}",
            resource_type="interview",
            resource_id=interview_id,
            scope=canon_scope(
                WORKSPACE_ID,
                "POST",
                f"/api/v1/interviews/{interview_id}/control",
            ),
            idempotency_key=key,
            input=payload.model_dump(),
        ),
        capacity_available=services.runner.capacity_available,
    )
    if accepted.created:

        async def _run() -> dict[str, Any]:
            try:
                return await asyncio.to_thread(
                    services.interviews.process_control,
                    operation_id=accepted.operation.id,
                )
            except Exception:
                await _release_after_failure(
                    services.interviews.release_failed_operation,
                    accepted.operation.id,
                )
                raise

        background.add_task(
            services.runner.submit,
            OperationJob(
                operation_id=accepted.operation.id,
                kind=accepted.operation.kind,
                resource_id=interview_id,
                run=_run,
            ),
        )
    return envelope(
        _accepted(accepted.operation).model_dump(),
        _ctx(request).request_id,
    )


@router.get("/interviews/{interview_id}/report")
def get_interview_report(interview_id: str, request: Request) -> dict[str, Any]:
    report = request.app.state.services.reports.get_view(interview_id)
    return envelope(report, _ctx(request).request_id)


@router.post("/interviews/{interview_id}/report/improvements", status_code=202)
def generate_report_improvements(
    interview_id: str,
    payload: GenerateCoachingRequest,
    request: Request,
    background: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    key = _require_idempotency_key(idempotency_key)
    services = request.app.state.services
    report = services.reports.get_view(interview_id)
    accepted = services.content.accept_coaching(
        interview_id,
        expected_revision=payload.expected_revision,
        command=OperationCommand(
            kind="report.coach",
            resource_type="report",
            resource_id=report["id"],
            scope=canon_scope(
                WORKSPACE_ID,
                "POST",
                f"/api/v1/interviews/{interview_id}/report/improvements",
            ),
            idempotency_key=key,
            input=payload.model_dump(),
        ),
        capacity_available=services.runner.capacity_available,
    )
    if accepted.created:

        async def _run() -> dict[str, Any]:
            try:
                return await services.content.process_coaching(
                    operation_id=accepted.operation.id
                )
            except Exception:
                await _release_after_failure(
                    services.content.release_failed_operation,
                    accepted.operation.id,
                )
                raise

        background.add_task(
            services.runner.submit,
            OperationJob(
                operation_id=accepted.operation.id,
                kind=accepted.operation.kind,
                resource_id=accepted.operation.resource_id,
                run=_run,
            ),
        )
    return envelope(
        _accepted(accepted.operation).model_dump(),
        _ctx(request).request_id,
    )


@router.post("/profiles/{profile_id}/resume-drafts", status_code=202)
def create_resume_draft(
    profile_id: str,
    payload: CreateResumeDraftRequest,
    request: Request,
    background: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    key = _require_idempotency_key(idempotency_key)
    services = request.app.state.services

    def _command(draft_id: str, target_hash: str) -> OperationCommand:
        return OperationCommand(
            kind="resume.compose",
            resource_type="resume_draft",
            resource_id=draft_id,
            scope=canon_scope(
                WORKSPACE_ID,
                "POST",
                f"/api/v1/profiles/{profile_id}/resume-drafts",
            ),
            idempotency_key=key,
            input={**payload.model_dump(), "target_hash": target_hash},
        )

    accepted = services.content.accept_resume_draft(
        profile_id,
        expected_revision=payload.expected_revision,
        profile_snapshot_id=payload.profile_snapshot_id,
        interview_id=payload.interview_id,
        jd_text=payload.jd_text,
        source_name=None,
        command_factory=_command,
        capacity_available=services.runner.capacity_available,
    )
    if accepted.created:

        async def _run() -> dict[str, Any]:
            try:
                return await services.content.process_resume_draft(
                    operation_id=accepted.operation.id
                )
            except Exception:
                await _release_after_failure(
                    services.content.release_failed_operation,
                    accepted.operation.id,
                )
                raise

        background.add_task(
            services.runner.submit,
            OperationJob(
                operation_id=accepted.operation.id,
                kind=accepted.operation.kind,
                resource_id=accepted.operation.resource_id,
                run=_run,
            ),
        )
    return envelope(
        _accepted(accepted.operation).model_dump(),
        _ctx(request).request_id,
    )


@router.get("/resume-drafts/{draft_id}")
def get_resume_draft(draft_id: str, request: Request) -> dict[str, Any]:
    draft = request.app.state.services.content.get_resume_draft(draft_id)
    return envelope(draft, _ctx(request).request_id)


@router.post("/resume-drafts/{draft_id}/accept")
def accept_resume_draft(
    draft_id: str,
    payload: AcceptResumeDraftRequest,
    request: Request,
) -> dict[str, Any]:
    draft = request.app.state.services.content.accept_draft(
        draft_id, expected_revision=payload.expected_revision
    )
    return envelope(draft, _ctx(request).request_id)


@router.post("/operations/{operation_id}/retry", status_code=202)
def retry_operation(
    operation_id: str,
    payload: RetryOperationRequest,
    request: Request,
    background: BackgroundTasks,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    key = _require_idempotency_key(idempotency_key)
    services = request.app.state.services
    request_input = payload.model_dump()
    original = services.operations.get(operation_id)
    content_operation = original is not None and original.kind in {
        "report.coach",
        "resume.compose",
    }
    if original is not None and original.kind in {
        "profile.confirm",
        "profile.activate",
        "profile.delete",
    }:
        accepted = services.profiles.accept_retry(
            operation_id,
            expected_revision=payload.expected_revision,
            idempotency_key=key,
            request_input=request_input,
            capacity_available=services.runner.capacity_available,
        )
        if accepted.operation.kind == "profile.delete":
            _schedule_profile_deletion(services, background, accepted)
        else:
            _schedule_profile_activation(services, background, accepted)
        return envelope(
            _accepted(accepted.operation).model_dump(), _ctx(request).request_id
        )
    if content_operation:
        accepted = services.content.accept_retry(
            operation_id,
            expected_revision=payload.expected_revision,
            idempotency_key=key,
            request_input=request_input,
            capacity_available=services.runner.capacity_available,
        )
    else:
        accepted = services.interviews.accept_retry(
            operation_id,
            expected_revision=payload.expected_revision,
            idempotency_key=key,
            request_input=request_input,
            capacity_available=services.runner.capacity_available,
        )
    if accepted.created:

        async def _run() -> dict[str, Any]:
            try:
                if content_operation:
                    return await services.content.process_operation(accepted.operation)
                if accepted.operation.kind == "interview.answer":
                    return await services.interviews.process_answer(
                        operation_id=accepted.operation.id
                    )
                return await asyncio.to_thread(
                    services.interviews.process_control,
                    operation_id=accepted.operation.id,
                )
            except Exception:
                release = (
                    services.content.release_failed_operation
                    if content_operation
                    else services.interviews.release_failed_operation
                )
                await _release_after_failure(release, accepted.operation.id)
                raise

        background.add_task(
            services.runner.submit,
            OperationJob(
                operation_id=accepted.operation.id,
                kind=accepted.operation.kind,
                resource_id=accepted.operation.resource_id,
                run=_run,
            ),
        )
    return envelope(
        _accepted(accepted.operation).model_dump(),
        _ctx(request).request_id,
    )
