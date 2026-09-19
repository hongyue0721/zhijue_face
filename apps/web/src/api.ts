// API 客户端：唯一网络边界。字段沿用 generated-type 语义（snake_case），
// 不在前端另造一套字段名（AGENTS §7）。错误统一走 ApiError，不用假成功兜底。

export type ClaimStatus = "proposed" | "confirmed" | "disputed" | "retracted";

export interface ClaimView {
  id: string;
  text: string;
  status: ClaimStatus;
  source_block_ids: string[];
  source_quotes: Array<{ exact_quote?: string; origin?: string; section?: string }>;
  supersedes_id: string | null;
}

export interface DocumentView {
  id: string;
  kind: string;
  filename_display: string;
  sha256: string;
  page_count: number | null;
  extract_status: string;
  index_status: string;
  warnings: string[];
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
  status: string;
  events_url: string;
}

export interface OperationView {
  id: string;
  kind: string;
  status: "queued" | "running" | "succeeded" | "failed" | "interrupted";
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

export interface QuestionView {
  id: string;
  root_id: string;
  kind: "main" | "probe" | "clarification";
  seed_id: string | null;
  wording: string;
  basis: Record<string, unknown>;
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
  status: "ready" | "active" | "finishing" | "completed" | "failed";
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

  constructor(status: number, body: ErrorBody) {
    super(body.message);
    this.name = "ApiError";
    this.status = status;
    this.code = body.code;
    this.retryable = body.retryable;
  }
}

const BASE = "/api/v1";

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${BASE}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const text = await response.text();
  const parsed = text ? JSON.parse(text) : {};
  if (!response.ok) {
    const body: ErrorBody = parsed.error ?? {
      code: "INTERNAL_ERROR",
      message: "请求失败。",
      retryable: false,
      details: {},
    };
    throw new ApiError(response.status, body);
  }
  return parsed.data as T;
}

export const api = {
  ready: () => request<Record<string, unknown>>("/health/ready"),

  createProfile: (displayName: string) =>
    request<ProfileView>("/profiles", {
      method: "POST",
      body: JSON.stringify({ display_name: displayName, synthetic: true }),
    }),

  getProfile: (profileId: string) => request<ProfileView>(`/profiles/${profileId}`),

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
    decisions: Array<{ claim_id: string; action: string; corrected_text?: string }>,
  ) =>
    request<OperationAccepted>(`/profiles/${profileId}/confirm`, {
      method: "POST",
      headers: { "Idempotency-Key": `web-confirm-${crypto.randomUUID()}` },
      body: JSON.stringify({ expected_revision: expectedRevision, decisions }),
    }),

  getOperation: (operationId: string) =>
    request<OperationView>(`/operations/${operationId}`),

  eventsUrl: (operationId: string) => `${BASE}/operations/${operationId}/events`,

  createInterview: (profileId: string, profileRevision: number) =>
    request<OperationAccepted>("/interviews", {
      method: "POST",
      headers: { "Idempotency-Key": `web-interview-${crypto.randomUUID()}` },
      body: JSON.stringify({
        profile_id: profileId,
        profile_revision: profileRevision,
        role_preset: "embedded_junior",
      }),
    }),

  getInterview: (interviewId: string) =>
    request<InterviewView>(`/interviews/${interviewId}`),

  startInterview: (
    interviewId: string,
    expectedRevision: number,
    idempotencyKey: string,
  ) =>
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

  retryOperation: (
    operationId: string,
    expectedRevision: number,
    idempotencyKey: string,
  ) =>
    request<OperationAccepted>(`/operations/${operationId}/retry`, {
      method: "POST",
      headers: { "Idempotency-Key": idempotencyKey },
      body: JSON.stringify({ expected_revision: expectedRevision }),
    }),
};
