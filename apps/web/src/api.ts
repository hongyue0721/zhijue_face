// 唯一浏览器网络边界。网络 DTO 保持 snake_case，不在 UI 复制第二套契约。

export type ClaimStatus = "proposed" | "confirmed" | "disputed" | "retracted";
export type OperationStatus =
  | "queued"
  | "running"
  | "succeeded"
  | "failed"
  | "interrupted"
  | "canceled";

export interface ClaimView {
  id: string;
  text: string;
  status: ClaimStatus;
  source_block_ids: string[];
  source_quotes: Array<{
    exact_quote?: string;
    origin?: string;
    section?: string;
    text_context?: string;
  }>;
  supersedes_id: string | null;
}

export interface DocumentView {
  id: string;
  kind: string;
  filename_display: string;
  sha256: string;
  page_count: number | null;
  extract_status: "pending" | "parsed" | "requires_text" | "failed" | string;
  index_status: "pending" | "indexing" | "ready" | "failed" | string;
  warnings: string[];
}

export interface DocumentBlockView {
  id: string;
  document_id: string;
  page_number: number | null;
  block_index: number;
  text: string;
  text_hash: string;
  origin: string;
}

export interface DocumentBlocksPage {
  items: DocumentBlockView[];
  next_cursor: string | null;
}

export interface ProfileView {
  id: string;
  revision: number;
  display_name: string;
  synthetic: boolean;
  status: string;
  documents: DocumentView[];
  proposed_claims: ClaimView[];
  confirmed_claims: ClaimView[];
  latest_snapshot_id: string | null;
}

export interface OperationAccepted {
  operation_id: string;
  resource_type: string;
  resource_id: string;
  status: OperationStatus;
  events_url: string;
}

export interface OperationView {
  id: string;
  kind: string;
  status: OperationStatus;
  resource_type: string;
  resource_id: string;
  parent_operation_id: string | null;
  attempts: number;
  result: Record<string, unknown> | null;
  error: { code: string; message: string; retryable: boolean } | null;
  last_event_seq: number;
  created_at: string;
  updated_at: string;
}

export interface ReadinessView {
  status: "ok";
  run_mode: "live" | "fixture" | "replay" | string;
  data_mode: string;
  database: string;
  knowledge: string;
  model: string;
  seed_bank_version: string;
}

export interface JDSourceView {
  id: string;
  source_type: "synthetic_demo_jd" | "user_provided" | "official_posting" | "real_jd_derived";
  source_name: string;
  content_hash: string;
  imported_at: string;
  version: number;
  status: string;
  is_synthetic: boolean;
  source_url: string | null;
  retrieved_at: string | null;
  derived: boolean;
  upstream_source_name: string | null;
  upstream_url: string | null;
  upstream_retrieved_at: string | null;
  upstream_content_hash: string | null;
  derived_artifact_path: string | null;
  derived_content_hash: string | null;
  transformation_note: string | null;
}

export interface JDRequirementView {
  id: string;
  tier: "required" | "preferred" | "responsibility" | "contextual";
  competency_id: string;
  importance: number;
  statement: string;
  source_span: {
    section: string;
    start: number;
    end: number;
    quote: string;
    unit: "unicode_code_point";
    utf16_start: number;
    utf16_end: number;
  };
  extraction: string;
}

export interface CoverageEntryView {
  competency_id: string;
  status: "supported" | "claimed" | "unverified" | "unknown" | "contradicted";
  requirement_ids: string[];
  evidence_ids: string[];
  relation: "direct_claim" | "direct_experience" | "related_context" | "model_inference";
  related_context_ids: string[];
  is_weakness: boolean;
  note: string;
}

export interface InterviewSlotView {
  schema_version: "1.0.0";
  slot_id: string;
  competency: string;
  jd_requirement_ids: string[];
  candidate_evidence_ids: string[];
  current_verification_status: CoverageEntryView["status"];
  verification_goal: string;
  priority: number;
  difficulty: "easy" | "medium";
  reason_code: string;
  structured_reason: string;
  seed_id: string | null;
}

export type PolicyAction = "CLARIFY" | "PROBE" | "NEXT" | "END";

export interface AcceptedAnswerView {
  id: string;
  client_turn_id: string;
  raw_text: string;
  evaluation_status: "processing" | "evaluated" | "failed";
}

export interface QuestionBasisView {
  schema_version?: string;
  basis_type?: "resume" | "jd" | "gap" | string;
  slot_id?: string;
  competency_id?: string;
  verification_goal?: string;
  jd_requirement_ids?: string[];
  candidate_evidence_ids?: string[];
  current_verification_status?: CoverageEntryView["status"];
  reason_code?: string;
  structured_reason?: string;
  followup_intent?: string;
  decision_id?: string;
}

export interface QuestionView {
  id: string;
  root_id: string;
  kind: "main" | "probe" | "clarification";
  seed_id: string | null;
  wording: string;
  basis: QuestionBasisView;
  order_index: number;
  accepted_answer: AcceptedAnswerView | null;
}

export interface RootResultView {
  root_question_id: string;
  observation_id: string;
  action: PolicyAction;
  reason_code: string;
  reason_summary: string;
  target: {
    competency_id: string;
    criterion_id: string | null;
    followup_intent: string;
  } | null;
}

export interface InterviewView {
  id: string;
  revision: number;
  status:
    | "preparing"
    | "prepare_failed"
    | "ready"
    | "active"
    | "finishing"
    | "finish_failed"
    | "completed";
  run_mode: string;
  profile_snapshot_id: string;
  jd_requirements: JDRequirementView[];
  jd_source: JDSourceView;
  root_plan: {
    slots: InterviewSlotView[];
    planner_version: string;
    seed_bank_version: string;
  };
  coverage_map: CoverageEntryView[];
  current_question: QuestionView | null;
  root_results: RootResultView[];
  active_operation_id: string | null;
  stop_requested: boolean;
  report_id: string | null;
  limitations: string[];
}

export interface CreateInterviewOptions {
  jd_text?: string;
  jd_source_name?: string;
}

export const JD_TEXT_MAX_LENGTH = 8_000;
export const JD_SOURCE_NAME_MAX_LENGTH = 200;

export interface ErrorBody {
  code: string;
  message: string;
  retryable: boolean;
  details: Record<string, unknown>;
}

export class ApiError extends Error {
  readonly code: string;
  readonly retryable: boolean;
  readonly status: number;
  readonly details: Record<string, unknown>;

  constructor(status: number, body: ErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.retryable = body.retryable;
    this.details = body.details;
  }
}

export type RequestRetryReason = "capacity" | "service";

export function requestRetryReason(error: ApiError): RequestRetryReason | null {
  if (!error.retryable) return null;
  return error.code === "CAPACITY_LIMITED" ? "capacity" : "service";
}

const BASE = "/api/v1";

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers);
  if (init.body !== undefined && !(init.body instanceof FormData) && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const response = await fetch(`${BASE}${path}`, { ...init, headers });
  const text = await response.text();
  let parsed: { data?: T; error?: ErrorBody } = {};
  if (text) {
    try {
      parsed = JSON.parse(text) as typeof parsed;
    } catch {
      throw new ApiError(response.status || 500, {
        code: "INTERNAL_ERROR",
        message: "服务返回了无法读取的响应。",
        retryable: response.status >= 500,
        details: {},
      });
    }
  }
  if (!response.ok) {
    throw new ApiError(
      response.status,
      parsed.error ?? {
        code: "INTERNAL_ERROR",
        message: "请求失败。",
        retryable: false,
        details: {},
      },
    );
  }
  return parsed.data as T;
}

export function newCommandKey(prefix: string): string {
  return `web-${prefix}-${crypto.randomUUID()}`;
}

export const api = {
  ready: (signal?: AbortSignal) => request<ReadinessView>("/health/ready", { signal }),

  createProfile: (displayName: string, synthetic = false) =>
    request<ProfileView>("/profiles", {
      method: "POST",
      body: JSON.stringify({ display_name: displayName, synthetic }),
    }),

  getProfile: (profileId: string, signal?: AbortSignal) =>
    request<ProfileView>(`/profiles/${profileId}`, { signal }),

  uploadDocument: (
    profileId: string,
    expectedRevision: number,
    file: File,
    idempotencyKey: string,
  ) => {
    const form = new FormData();
    form.append("file", file);
    form.append("kind", "resume");
    form.append("expected_revision", String(expectedRevision));
    return request<OperationAccepted>(`/profiles/${profileId}/documents`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: form,
    });
  },

  getDocument: (documentId: string, signal?: AbortSignal) =>
    request<DocumentView>(`/documents/${documentId}`, { signal }),

  getDocumentBlocks: (
    documentId: string,
    cursor?: string,
    limit = 100,
    signal?: AbortSignal,
  ) => {
    const query = new URLSearchParams({ limit: String(limit) });
    if (cursor) query.set("cursor", cursor);
    return request<DocumentBlocksPage>(`/documents/${documentId}/blocks?${query}`, { signal });
  },

  addFacts: (profileId: string, expectedRevision: number, texts: string[]) =>
    request<ProfileView>(`/profiles/${profileId}/facts`, {
      method: "POST",
      body: JSON.stringify({
        expected_revision: expectedRevision,
        items: texts.map((text) => ({ section: "project", text })),
      }),
    }),

  confirm: (
    profileId: string,
    expectedRevision: number,
    decisions: Array<{ claim_id: string; action: "accept" | "reject" | "correct"; corrected_text?: string }>,
    idempotencyKey: string,
  ) =>
    request<OperationAccepted>(`/profiles/${profileId}/confirm`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ expected_revision: expectedRevision, decisions }),
    }),

  getOperation: (operationId: string, signal?: AbortSignal) =>
    request<OperationView>(`/operations/${operationId}`, { signal }),

  eventsUrl: (operationId: string, after?: number) => {
    const query = after === undefined ? "" : `?after=${after}`;
    return `${BASE}/operations/${operationId}/events${query}`;
  },

  createInterview: (
    profileId: string,
    profileRevision: number,
    options: CreateInterviewOptions,
    idempotencyKey: string,
  ) =>
    request<OperationAccepted>("/interviews", {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({
        profile_id: profileId,
        profile_revision: profileRevision,
        role_preset: "embedded_junior",
        ...options,
      }),
    }),

  getInterview: (interviewId: string, signal?: AbortSignal) =>
    request<InterviewView>(`/interviews/${interviewId}`, { signal }),

  startInterview: (interviewId: string, expectedRevision: number, idempotencyKey: string) =>
    request<OperationAccepted>(`/interviews/${interviewId}/start`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ expected_revision: expectedRevision }),
    }),

  submitAnswer: (
    interviewId: string,
    input: {
      expected_revision: number;
      question_id: string;
      client_turn_id: string;
      answer_text: string;
    },
    idempotencyKey: string,
  ) =>
    request<OperationAccepted>(`/interviews/${interviewId}/answers`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify(input),
    }),

  retryOperation: (operationId: string, expectedRevision: number, idempotencyKey: string) =>
    request<OperationAccepted>(`/operations/${operationId}/retry`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ expected_revision: expectedRevision }),
    }),
};
