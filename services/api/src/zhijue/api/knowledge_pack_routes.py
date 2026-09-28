"""岗位知识包 HTTP 契约（api.md §9）：列表 / 详情 / 异步导入。

边界（主文件 §6）：

- 列表、详情、导入不依赖模型或候选人 embedding 就绪（§6.4）；
  只有“生成面试”能力受包可选择性约束。
- 导入 = 202 受理 + Operation 观察；成功结果里的 review_status 永远
  来自服务端审核记录，绝不透传 ZIP 自带的 approved 声明。
- 相同 Idempotency-Key + 相同上传字节复用原操作；不同字节 409 冲突。
  相同内容不同 ZIP 重打包由内容 digest 去重在登记层复用 release。
"""

from __future__ import annotations

import asyncio
import hashlib
from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, BackgroundTasks, Header, Request, UploadFile

from zhijue.adapters.db.operations import OperationCommand
from zhijue.api.errors import ApiError
from zhijue.api.routes import (
    WORKSPACE_ID,
    _accepted,
    _ctx,
    _require_idempotency_key,
    canon_scope,
    envelope,
)
from zhijue.application.operations_runner import OperationJob
from zhijue.domain.operations import canonical_input_hash

if TYPE_CHECKING:
    from zhijue.api.app import Services

router = APIRouter(prefix="/api/v1", tags=["knowledge-packs"])

IMPORT_KIND = "knowledge_pack.import"


@router.get("/knowledge-packs")
def list_knowledge_packs(request: Request) -> dict[str, Any]:
    """真实 items；不补假卡片。默认项只影响新创建面试（无全局激活）。"""
    services: Services = request.app.state.services
    return envelope(services.knowledge_packs.list_view(), _ctx(request).request_id)


@router.get("/knowledge-packs/{release_id}")
def get_knowledge_pack(release_id: str, request: Request) -> dict[str, Any]:
    """详情与列表 ID 同源；含来源登记与校验明细，不含参考答案/评分细则。"""
    services: Services = request.app.state.services
    return envelope(
        services.knowledge_packs.detail_view(release_id), _ctx(request).request_id
    )


async def _read_upload_limited(file: UploadFile, max_bytes: int) -> bytes:
    """受控读取：超限立即 413，不把不可信大小整个吞进内存。"""
    chunks: list[bytes] = []
    total = 0
    while chunk := await file.read(64 * 1024):
        total += len(chunk)
        if total > max_bytes:
            raise ApiError(
                status_code=413,
                code="PACK_UPLOAD_TOO_LARGE",
                message=f"上传超过 {max_bytes} 字节上限。",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def _schedule_import(
    services: Services, background: BackgroundTasks, operation
) -> None:
    """把回执字节交给后台导入；重试复用同一 resource_id（回执）取回输入。"""

    async def _run() -> dict[str, Any]:
        receipt_id = operation.resource_id

        def _process() -> dict[str, Any]:
            zip_bytes = services.knowledge_packs.read_receipt_upload(receipt_id)
            outcome = services.knowledge_packs.import_pack_bytes(
                zip_bytes, operation_id=operation.id
            )
            services.knowledge_packs.complete_import_receipt(receipt_id, outcome)
            detail = services.knowledge_packs.detail_view(outcome.release.id)
            return {
                "release_id": outcome.release.id,
                "pack_id": outcome.release.pack_id,
                "version": outcome.release.version,
                "content_digest": outcome.release.content_digest,
                "reused": outcome.reused,
                # 审核状态取自服务端记录（外部上传默认 unreviewed）；
                # 导入成功不等于可用于技术评分。
                "review_status": detail["review_status"],
                "selectable_for_new_interview": detail["selectable"],
            }

        return await asyncio.to_thread(_process)

    background.add_task(
        services.runner.submit,
        OperationJob(
            operation_id=operation.id,
            kind=operation.kind,
            resource_id=operation.resource_id,
            run=_run,
        ),
    )


@router.post("/knowledge-packs/import", status_code=202)
async def import_knowledge_pack(
    request: Request,
    background: BackgroundTasks,
    file: UploadFile,
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict[str, Any]:
    """接收 ZIP → 受控保存回执 → 受理 Operation → 202。

    浏览器刷新不丢后台输入：字节按回执落在 runtime，恢复用 operation ID
    观察既有 SSE/polling；重试从回执取回同一份字节，不要求重新上传。
    """
    key = _require_idempotency_key(idempotency_key)
    services: Services = request.app.state.services
    data = await _read_upload_limited(
        file, services.knowledge_packs.limits.max_upload_bytes
    )
    upload_sha = hashlib.sha256(data).hexdigest()
    scope = canon_scope(WORKSPACE_ID, "POST", "/api/v1/knowledge-packs/import")

    # 幂等输入 = 内容事实（sha + 大小）；回执 ID 是本次请求新生成的，
    # 不参与哈希。重放比较 input_hash：同字节复用原操作、异字节冲突（E02）。
    input_payload = {"upload_sha256": upload_sha, "size": len(data)}
    replay = services.operations.find_by_key(scope=scope, idempotency_key=key)
    if replay is not None:
        if replay.input_hash == canonical_input_hash(input_payload):
            return envelope(_accepted(replay).model_dump(), _ctx(request).request_id)
        raise ApiError(
            status_code=409,
            code="IDEMPOTENCY_CONFLICT",
            message="相同 Idempotency-Key 收到不同内容；请换用新的键或同一文件重试。",
        )

    receipt = services.knowledge_packs.create_upload_receipt(data)
    try:
        operation, created = services.operations.accept_queued(
            OperationCommand(
                kind=IMPORT_KIND,
                resource_type="knowledge_pack_import",
                resource_id=receipt.id,
                scope=scope,
                idempotency_key=key,
                input=input_payload,
            ),
            capacity_available=services.runner.capacity_available,
        )
    except Exception:
        services.knowledge_packs.discard_upload_receipt(receipt.id)
        raise
    if not created:
        # 并发同键同内容竞争失败：复用赢家的操作，丢弃本地多余回执。
        services.knowledge_packs.discard_upload_receipt(receipt.id)
        return envelope(_accepted(operation).model_dump(), _ctx(request).request_id)

    _schedule_import(services, background, operation)
    return envelope(_accepted(operation).model_dump(), _ctx(request).request_id)
