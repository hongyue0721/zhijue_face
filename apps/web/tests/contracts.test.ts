import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  api,
  requestRetryReason,
  type CoverageEntryView,
  type JDRequirementView,
  type JDSourceView,
  type OperationAccepted,
  type OperationView,
} from "../src/api";
import { isTerminalOperation } from "../src/hooks/useOperationMonitor";
import {
  coverageExplanation,
  followupIntentText,
  jdSourceText,
  requirementTitle,
} from "../src/presentation";
import { parseRoute, preparePath } from "../src/routing";

const accepted: OperationAccepted = {
  operation_id: "operation_contract_001",
  resource_type: "profile",
  resource_id: "profile_contract_001",
  status: "queued",
  events_url: "/api/v1/operations/operation_contract_001/events",
};

function ok<T>(data: T): Response {
  return new Response(JSON.stringify({ data, meta: { request_id: "request_test" } }), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });
}


function errorResponse(
  status: number,
  error: { code: string; message: string; retryable: boolean },
): Response {
  return new Response(JSON.stringify({ error: { ...error, details: {} } }), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
describe("browser API boundary", () => {
  const fetchMock = vi.fn(async () => ok(accepted));

  beforeEach(() => {
    fetchMock.mockClear();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => vi.unstubAllGlobals());

  it("uploads the PDF as browser-managed multipart without a forced content type", async () => {
    const file = new File(["%PDF-1.4 contract"], "resume.pdf", { type: "application/pdf" });

    await api.uploadDocument("profile_1", 4, file, "document-key-0001");

    const [url, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const headers = new Headers(init.headers);
    expect(url).toBe("/api/v1/profiles/profile_1/documents");
    expect(headers.get("Content-Type")).toBeNull();
    expect(headers.get("Idempotency-Key")).toBe("document-key-0001");
    expect(init.body).toBeInstanceOf(FormData);
    const form = init.body as FormData;
    expect(form.get("file")).toBe(file);
    expect(form.get("kind")).toBe("resume");
    expect(form.get("expected_revision")).toBe("4");
  });

  it("sends user JD fields but never sends a client-authored source type", async () => {
    await api.createInterview(
      "profile_1",
      3,
      { jd_text: "真实岗位要求", jd_source_name: "嵌入式岗位" },
      "plan-key-0001",
    );

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const body = JSON.parse(String(init.body));
    expect(body).toMatchObject({
      profile_id: "profile_1",
      profile_revision: 3,
      role_preset: "embedded_junior",
      jd_text: "真实岗位要求",
      jd_source_name: "嵌入式岗位",
    });
    expect(body).not.toHaveProperty("source_type");
  });

  it("selects the server demo JD by omitting user JD fields", async () => {
    await api.createInterview("profile_1", 3, {}, "plan-key-0002");

    const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
    const body = JSON.parse(String(init.body));
    expect(body).not.toHaveProperty("jd_text");
    expect(body).not.toHaveProperty("jd_source_name");
    expect(body).not.toHaveProperty("source_type");
  });
  it("forwards a caller-owned answer identity unchanged across retries", async () => {
    const input = {
      expected_revision: 5,
      question_id: "question_1",
      client_turn_id: "turn-stable-0001",
      answer_text: "同一条原始回答",
    };

    await api.submitAnswer("interview_1", input, "answer-key-stable-0001");
    await api.submitAnswer("interview_1", input, "answer-key-stable-0001");

    const calls = fetchMock.mock.calls as unknown as Array<[string, RequestInit]>;
    const requests = calls.map(([, init]) => ({
      body: String(init.body),
      key: new Headers(init.headers).get("Idempotency-Key"),
    }));
    expect(requests[0]).toEqual(requests[1]);
    expect(JSON.parse(requests[0].body).client_turn_id).toBe("turn-stable-0001");
    expect(requests[0].key).toBe("answer-key-stable-0001");
  });

  it("keeps a 429 CAPACITY_LIMITED response retryable without treating it as success", async () => {
    fetchMock.mockResolvedValueOnce(errorResponse(429, {
      code: "CAPACITY_LIMITED",
      message: "操作队列已满，请稍后重试。",
      retryable: true,
    }));

    let caught: unknown;
    try {
      await api.submitAnswer(
        "interview_1",
        {
          expected_revision: 5,
          question_id: "question_1",
          client_turn_id: "turn-capacity-0001",
          answer_text: "等待容量恢复后复用原请求",
        },
        "answer-key-capacity-0001",
      );
    } catch (error) {
      caught = error;
    }

    expect(caught).toBeInstanceOf(ApiError);
    const apiError = caught as ApiError;
    expect(apiError).toMatchObject({
      status: 429,
      code: "CAPACITY_LIMITED",
      retryable: true,
    });
    expect(requestRetryReason(apiError)).toBe("capacity");
    expect(requestRetryReason(apiError)).not.toBe("service");
  });

});

describe("URL and presentation contracts", () => {
  it("recognizes only the three P0 route shapes", () => {
    expect(parseRoute("/start", "?profile=profile_1")).toEqual({
      page: "start",
      profileId: "profile_1",
    });
    expect(parseRoute("/profiles/profile_1/prepare", "?interview=interview_1")).toEqual({
      page: "prepare",
      profileId: "profile_1",
      interviewId: "interview_1",
    });
    expect(parseRoute("/interviews/interview_1", "")).toEqual({
      page: "interview",
      interviewId: "interview_1",
    });
    expect(preparePath("profile 1", "interview/1")).toBe(
      "/profiles/profile%201/prepare?interview=interview%2F1",
    );
  });

  it("uses returned requirement text and preserves the unknown-is-not-weakness rule", () => {
    const requirement = {
      id: "requirement_1",
      statement: "能够解释 UART DMA 排障过程",
    } as JDRequirementView;
    const coverage = {
      status: "unknown",
      relation: "direct_claim",
      evidence_ids: [],
      note: "",
    } as CoverageEntryView;

    expect(requirementTitle([requirement], [requirement.id])).toBe(requirement.statement);
    expect(requirementTitle([requirement], ["missing"])).toBe("岗位相关能力验证");
    expect(coverageExplanation(coverage)).toContain("材料未体现不代表不会");
  });

  it("maps every JD source type from the server without inferring trust from its name", () => {
    const source = (sourceType: JDSourceView["source_type"]) => ({
      source_type: sourceType,
      source_name: "相同来源名称不能改变 source_type",
    }) as JDSourceView;

    expect(jdSourceText(source("synthetic_demo_jd"))).toBe("演示岗位配置");
    expect(jdSourceText(source("user_provided"))).toBe("用户提供岗位描述");
    expect(jdSourceText(source("official_posting"))).toBe("官方公开岗位");
    expect(jdSourceText(source("real_jd_derived"))).toBe("公开岗位衍生材料");
  });

  it("keeps counterfactual, pushback, and reflection follow-up intents distinct", () => {
    expect(followupIntentText("counterfactual")).toBe("条件变化下的调整");
    expect(followupIntentText("pushback")).toBe("回应反例或限制条件");
    expect(followupIntentText("reflection")).toBe("复盘与经验总结");
    expect(followupIntentText("pushback")).not.toBe(followupIntentText("counterfactual"));
    expect(followupIntentText("unrecognized_internal_intent")).toBe("围绕当前回答继续核对");
  });

  it("treats only persisted operation terminal states as complete", () => {
    const operation = (status: OperationView["status"]) => ({ status }) as OperationView;
    expect(isTerminalOperation(operation("queued"))).toBe(false);
    expect(isTerminalOperation(operation("running"))).toBe(false);
    expect(isTerminalOperation(operation("succeeded"))).toBe(true);
    expect(isTerminalOperation(operation("failed"))).toBe(true);
    expect(isTerminalOperation(operation("interrupted"))).toBe(true);
    expect(isTerminalOperation(operation("canceled"))).toBe(true);
  });
});
