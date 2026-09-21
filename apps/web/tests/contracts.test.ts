import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  ApiError,
  api,
  requestRetryReason,
  shouldPreserveWriteCommand,
  type OperationAccepted,
  type OperationView,
} from "../src/api";
import {
  isTerminalOperation,
  preferObservedOperation,
} from "../src/hooks/useOperationMonitor";
import { scoreText } from "../src/presentation";
import { parseRoute, preparePath, reportPath, resumeDraftPath } from "../src/routing";
import {
  clearRecoverableCommand,
  loadRecoverableCommand,
  saveRecoverableCommand,
  type RecoverableCommand,
} from "../src/storage";

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

function installSessionStorage(): void {
  const values = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return values.size;
    },
    clear: () => values.clear(),
    getItem: (key) => values.get(key) ?? null,
    key: (index) => [...values.keys()][index] ?? null,
    removeItem: (key) => values.delete(key),
    setItem: (key, value) => values.set(key, value),
  };
  vi.stubGlobal("window", { sessionStorage: storage });
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


  it("replays lost 202 responses with the original body and idempotency key", async () => {
    installSessionStorage();
    const improvements: RecoverableCommand = {
      kind: "report-improvements",
      idempotencyKey: "coaching-key-lost-0001",
      input: { expected_revision: 7 },
    };
    saveRecoverableCommand("report-improvements", "report_1", improvements);
    fetchMock.mockRejectedValueOnce(new TypeError("response lost"));
    let networkError: unknown;
    try {
      await api.generateReportImprovements(
        "interview_1",
        improvements.input.expected_revision,
        improvements.idempotencyKey,
      );
    } catch (error) {
      networkError = error;
    }
    expect(shouldPreserveWriteCommand(networkError)).toBe(true);
    const recoveredImprovements = loadRecoverableCommand(
      "report-improvements",
      "report_1",
    );
    expect(recoveredImprovements).toEqual(improvements);
    if (recoveredImprovements?.kind !== "report-improvements") {
      throw new Error("report improvements command was not recovered");
    }
    await api.generateReportImprovements(
      "interview_1",
      recoveredImprovements.input.expected_revision,
      recoveredImprovements.idempotencyKey,
    );

    const resume: RecoverableCommand = {
      kind: "report-resume",
      idempotencyKey: "resume-key-lost-0001",
      input: {
        profile_id: "profile_1",
        expected_revision: 8,
        profile_snapshot_id: "snapshot_1",
        interview_id: "interview_1",
      },
    };
    saveRecoverableCommand("report-resume", "report_1", resume);
    fetchMock.mockRejectedValueOnce(new TypeError("response lost"));
    try {
      await api.createResumeDraft(
        resume.input.profile_id,
        {
          expected_revision: resume.input.expected_revision,
          profile_snapshot_id: resume.input.profile_snapshot_id,
          interview_id: resume.input.interview_id,
        },
        resume.idempotencyKey,
      );
    } catch (error) {
      networkError = error;
    }
    expect(shouldPreserveWriteCommand(networkError)).toBe(true);
    const recoveredResume = loadRecoverableCommand("report-resume", "report_1");
    expect(recoveredResume).toEqual(resume);
    if (recoveredResume?.kind !== "report-resume") {
      throw new Error("resume command was not recovered");
    }
    await api.createResumeDraft(
      recoveredResume.input.profile_id,
      {
        expected_revision: recoveredResume.input.expected_revision,
        profile_snapshot_id: recoveredResume.input.profile_snapshot_id,
        interview_id: recoveredResume.input.interview_id,
      },
      recoveredResume.idempotencyKey,
    );

    const retry: RecoverableCommand = {
      kind: "report-retry",
      idempotencyKey: "retry-key-lost-0001",
      input: { operation_id: "operation_failed_1", expected_revision: 9 },
    };
    saveRecoverableCommand("report-retry", "report_1", retry);
    fetchMock.mockRejectedValueOnce(new TypeError("response lost"));
    try {
      await api.retryOperation(
        retry.input.operation_id,
        retry.input.expected_revision,
        retry.idempotencyKey,
      );
    } catch (error) {
      networkError = error;
    }
    expect(shouldPreserveWriteCommand(networkError)).toBe(true);
    const recoveredRetry = loadRecoverableCommand("report-retry", "report_1");
    expect(recoveredRetry).toEqual(retry);
    if (recoveredRetry?.kind !== "report-retry") {
      throw new Error("retry command was not recovered");
    }
    await api.retryOperation(
      recoveredRetry.input.operation_id,
      recoveredRetry.input.expected_revision,
      recoveredRetry.idempotencyKey,
    );

    const resumeRetry: RecoverableCommand = {
      kind: "resume-retry",
      idempotencyKey: "resume-retry-key-lost-0001",
      input: { operation_id: "operation_failed_2", expected_revision: 10 },
    };
    saveRecoverableCommand("resume-retry", "resume_1", resumeRetry);
    fetchMock.mockRejectedValueOnce(new TypeError("response lost"));
    try {
      await api.retryOperation(
        resumeRetry.input.operation_id,
        resumeRetry.input.expected_revision,
        resumeRetry.idempotencyKey,
      );
    } catch (error) {
      networkError = error;
    }
    expect(shouldPreserveWriteCommand(networkError)).toBe(true);
    const recoveredResumeRetry = loadRecoverableCommand("resume-retry", "resume_1");
    expect(recoveredResumeRetry).toEqual(resumeRetry);
    if (recoveredResumeRetry?.kind !== "resume-retry") {
      throw new Error("resume retry command was not recovered");
    }
    await api.retryOperation(
      recoveredResumeRetry.input.operation_id,
      recoveredResumeRetry.input.expected_revision,
      recoveredResumeRetry.idempotencyKey,
    );

    const calls = fetchMock.mock.calls as unknown as Array<[string, RequestInit]>;
    const signatures = calls.map(([url, init]) => ({
      url,
      body: String(init.body),
      key: new Headers(init.headers).get("Idempotency-Key"),
    }));
    expect(signatures[0]).toEqual(signatures[1]);
    expect(signatures[2]).toEqual(signatures[3]);
    expect(signatures[4]).toEqual(signatures[5]);
    expect(signatures[6]).toEqual(signatures[7]);
    clearRecoverableCommand("report-improvements", "report_1");
    clearRecoverableCommand("report-resume", "report_1");
    clearRecoverableCommand("report-retry", "report_1");
    clearRecoverableCommand("resume-retry", "resume_1");

  });
});

describe("URL and presentation contracts", () => {
  it("recognizes the five functional route shapes", () => {
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
    expect(parseRoute("/interviews/interview_1/report", "")).toEqual({
      page: "report",
      interviewId: "interview_1",
    });
    expect(parseRoute("/resume-drafts/resume_1", "")).toEqual({
      page: "resume",
      draftId: "resume_1",
    });
    expect(preparePath("profile 1", "interview/1")).toBe(
      "/profiles/profile%201/prepare?interview=interview%2F1",
    );
    expect(reportPath("interview/1")).toBe("/interviews/interview%2F1/report");
    expect(resumeDraftPath("resume/1")).toBe("/resume-drafts/resume%2F1");
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

  it("keeps the first terminal operation snapshot when older transport data arrives", () => {
    const running = { status: "running" } as OperationView;
    const failed = { status: "failed" } as OperationView;
    const succeeded = { status: "succeeded" } as OperationView;

    expect(preferObservedOperation(running, failed)).toBe(failed);
    expect(preferObservedOperation(failed, running)).toBe(failed);
    expect(preferObservedOperation(succeeded, failed)).toBe(succeeded);
  });


  it("distinguishes an observed zero score from an unmeasured result", () => {
    expect(scoreText(null, "UNMEASURED")).toBe("UNMEASURED");
    expect(Number.parseFloat(scoreText(0, "UNMEASURED"))).toBe(0);
  });
});
