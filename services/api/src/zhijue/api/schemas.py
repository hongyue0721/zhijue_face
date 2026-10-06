"""请求/响应 DTO：与 api.md 字段逐一对齐（snake_case，网络边界专用）。

DTO 只做形状与范围校验；业务语义校验（section 白名单、revision 冲突、
claim 归属）仍在 application 层，避免同一规则写两遍后漂移。
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

FactSection = Literal["basic", "education", "project", "skill", "award", "other"]
DecisionAction = Literal["accept", "reject", "correct"]


class FactItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    section: FactSection
    text: str


class FactsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    items: list[FactItem] = Field(min_length=1)


class Decision(BaseModel):
    model_config = ConfigDict(extra="forbid")

    claim_id: str = Field(min_length=1)
    action: DecisionAction
    corrected_text: str | None = None


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    decisions: list[Decision] = Field(min_length=1)


class ActivateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)


class CreateProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str = Field(min_length=1, max_length=200)
    synthetic: bool = True


class ProfileClaim(BaseModel):
    id: str
    text: str
    status: str
    source_block_ids: list[str]
    source_quotes: list[dict[str, object]]
    supersedes_id: str | None


class ProfileDocumentView(BaseModel):
    id: str
    kind: str
    filename_display: str
    sha256: str
    page_count: int | None
    extract_status: str
    index_status: str
    warnings: list[object]


class ProfileSnapshotActivationView(BaseModel):
    snapshot_id: str
    status: Literal["pending", "indexing", "ready", "failed"]
    operation_id: str | None


class ProfileViewDto(BaseModel):
    """api.md §3 ProfileView：服务端完整快照，不含服务器绝对路径。"""

    id: str
    revision: int
    display_name: str
    synthetic: bool
    status: str
    documents: list[ProfileDocumentView]
    proposed_claims: list[ProfileClaim]
    confirmed_claims: list[ProfileClaim]
    latest_snapshot_id: str | None
    active_operation_id: str | None
    snapshot_activation: ProfileSnapshotActivationView | None


class OperationAccepted(BaseModel):
    operation_id: str
    resource_type: str
    resource_id: str
    status: str
    events_url: str


class OperationView(BaseModel):
    id: str
    kind: str
    status: str
    resource_type: str
    resource_id: str
    parent_operation_id: str | None
    retry_trigger: Literal["automatic", "manual"] | None
    next_operation_id: str | None
    retry_reason: Literal["transient", "correction"] | None
    chain_started_at: str
    attempt_limit: int | None
    attempts: int
    result: dict[str, Any] | None
    error: dict[str, Any] | None
    last_event_seq: int
    created_at: str
    updated_at: str


class OperationResponse(BaseModel):
    data: OperationView
    meta: dict[str, str]


class CreateInterviewRequest(BaseModel):
    """api.md §6：POST /interviews。"""

    model_config = ConfigDict(extra="forbid")

    profile_id: str = Field(min_length=1)
    profile_revision: int = Field(ge=0)
    jd_text: str | None = Field(default=None, max_length=8000)
    role_preset: Literal["embedded_junior"] = "embedded_junior"
    memory_enabled: bool = False
    observer_mode: bool = False
    jd_source_name: str | None = Field(default=None, min_length=1, max_length=200)
    # 受理时冻结的岗位包 release（api.md §6 增量）；省略 = 服务端解析默认，
    # 但解析结果不进幂等哈希（D05），也不影响任何已创建面试。
    pack_release_id: str | None = Field(default=None, pattern=r"^kpr_[0-9a-f]{16}$")


class StartInterviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)


class ControlInterviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    action: Literal["skip", "end"]


class SubmitAnswerRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    question_id: str = Field(min_length=1, max_length=128)
    client_turn_id: str = Field(min_length=1, max_length=128)
    answer_text: str = Field(min_length=1, max_length=6000)


class RetryOperationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)


class GenerateCoachingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)


class CreateResumeDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
    profile_snapshot_id: str = Field(min_length=1, max_length=128)
    interview_id: str | None = Field(default=None, min_length=1, max_length=128)
    jd_text: str | None = Field(default=None, min_length=1, max_length=8000)

    @model_validator(mode="after")
    def one_target_source(self) -> CreateResumeDraftRequest:
        if self.interview_id is not None and self.jd_text is not None:
            raise ValueError("interview_id and jd_text are mutually exclusive")
        return self


class AcceptResumeDraftRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_revision: int = Field(ge=0)
