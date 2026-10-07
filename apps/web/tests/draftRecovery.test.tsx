// @vitest-environment happy-dom
import { act, type ReactNode, type MouseEventHandler } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError, api, type InterviewView, type QuestionView, type ProfileView, type OperationAccepted, type OperationView } from "../src/api";
import { AnswerComposer } from "../src/components/interview/AnswerComposer";
import { JDInput } from "../src/components/prepare/JDInput";
import { InterviewPage } from "../src/pages/InterviewPage";
import { PreparePage } from "../src/pages/PreparePage";
import { loadAnswerDraft, saveAnswerDraft } from "../src/answerDrafts";
import { loadPrepareDraft, prepareDraftKey } from "../src/prepareDrafts";
import { clearProfileTemporaryDrafts, setTemporaryDraftsEnabled } from "../src/temporaryDrafts";

type FieldProps = { modelValue: string; onUpdateModelValue: (value: string) => void; disabled?: boolean; readonly?: boolean };
vi.mock("@any-design/anyui/react", () => ({
  Button: ({ children, disabled, loading, onClick }: { children?: ReactNode; disabled?: boolean; loading?: boolean; onClick?: MouseEventHandler<HTMLButtonElement> }) => <button disabled={disabled || loading} onClick={onClick}>{children}</button>,
  Input: ({ modelValue, onUpdateModelValue, disabled }: FieldProps) => <input value={modelValue} disabled={disabled} onInput={(event) => onUpdateModelValue(event.currentTarget.value)} />,
  Textarea: ({ modelValue, onUpdateModelValue, disabled, readonly }: FieldProps) => <textarea value={modelValue} disabled={disabled} readOnly={readonly} onInput={(event) => onUpdateModelValue(event.currentTarget.value)} />,
  Alert: ({ title, children }: { title?: string; children?: ReactNode }) => <section role="alert"><h2>{title}</h2>{children}</section>,
  Tag: ({ children }: { children?: ReactNode }) => <span>{children}</span>,
  Spinner: () => <span role="status" />,
  Progress: () => <progress />,
}));
const question: QuestionView = { id: "q", root_id: "root", kind: "main", seed_id: null, wording: "Explain your work", basis: {}, order_index: 1, accepted_answer: null };
const interview: InterviewView = {
  id: "interview", revision: 3, status: "active", run_mode: "fixture", profile_id: "draft-test", profile_snapshot_id: "snapshot",
  jd_text: "岗位要求", jd_requirements: [], jd_source: {
    id: "jd", source_type: "user_provided", source_name: "test role", content_hash: "hash", imported_at: "2026-10-03", version: 1,
    status: "ready", is_synthetic: false, source_url: null, retrieved_at: null, derived: false, upstream_source_name: null,
    upstream_url: null, upstream_retrieved_at: null, upstream_content_hash: null, derived_artifact_path: null, derived_content_hash: null, transformation_note: null,
  },
  root_plan: { slots: [], planner_version: "test", seed_bank_version: "test" }, coverage_map: [], current_question: question,
  root_results: [], active_operation_id: null, stop_requested: false, report_id: null, limitations: [], knowledge_pack: { binding: "legacy_unresolved", pack_release_id: null, profile_version: null, profile_digest: null, capabilities: [] },
};
const profile: ProfileView = {
  id: "draft-test", revision: 2, display_name: "Test", synthetic: false, status: "active", documents: [], proposed_claims: [], confirmed_claims: [],
  latest_snapshot_id: "snapshot", active_operation_id: null, snapshot_activation: { snapshot_id: "snapshot", status: "ready", operation_id: null },
};
let root: Root;
let host: HTMLDivElement;
async function render(node: ReactNode) { await act(async () => { root.render(node); }); }
async function click(pattern: RegExp) {
  const target = [...host.querySelectorAll("button")].find((button) => pattern.test(button.textContent ?? ""));
  if (!target) throw new Error(`Missing button ${pattern}`);
  await act(async () => { target.click(); });
}
async function input(element: HTMLInputElement | HTMLTextAreaElement, value: string) {
  await act(async () => { element.value = value; element.dispatchEvent(new Event("input", { bubbles: true })); });
}
const composerProps = { profileId: "draft-test", interviewId: "interview", question, acceptedAnswer: null, submitting: false, serviceReady: true,
  pendingRetryText: null, retryReason: null, canRetryAnalysis: false, retryBudgetExhausted: false, onSubmit: vi.fn(), onResetRetry: vi.fn(), onRetryAnalysis: vi.fn() };
beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  sessionStorage.clear();
  clearProfileTemporaryDrafts("draft-test");
  setTemporaryDraftsEnabled(false);
  host = document.createElement("div"); document.body.append(host); root = createRoot(host);
  vi.stubGlobal("EventSource", class { onerror = null; addEventListener() {} close() {} });
  vi.spyOn(api, "getOperation").mockReturnValue(Promise.withResolvers<OperationView>().promise);
  vi.spyOn(api, "getInterview").mockResolvedValue(interview);
  vi.spyOn(api, "getProfile").mockResolvedValue(profile);
  vi.spyOn(api, "listKnowledgePacks").mockResolvedValue({ items: [], default_pack_release_id: null, import_limits: { max_upload_bytes: 1, max_extracted_total_bytes: 1, max_single_file_bytes: 1, max_entries: 1, max_path_depth: 1 } });
});
afterEach(async () => { await act(async () => { root.unmount(); }); host.remove(); vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

describe("draft editing and recovery", () => {
  it("offers unchecked opt-in, restores JD navigation text, and visibly clears it", async () => {
    const key = prepareDraftKey("draft-test", null);
    const editor = <JDInput draftKey={key} disabled={false} busy={false} onGenerate={vi.fn()} />;
    await render(editor);
    expect(host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.checked).toBe(false);
    await input(host.querySelector("textarea")!, "Required private skill");
    expect(sessionStorage.length).toBe(0);
    await act(async () => { host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(); });
    await render(null); await render(editor);
    expect(host.querySelector("textarea")!.value).toBe("Required private skill");
    expect(host.textContent).toContain("已恢复本标签页暂存的文字");
    await click(/清除当前草稿/);
    expect(host.querySelector("textarea")!.value).toBe("");
    expect(loadPrepareDraft(key)).toBeUndefined();
  });

  it("shows storage denial rather than a saved claim", async () => {
    await render(<AnswerComposer {...composerProps} />);
    await input(host.querySelector("textarea")!, "Private answer");
    vi.spyOn(window, "sessionStorage", "get").mockImplementation(() => { throw new DOMException("Denied", "SecurityError"); });
    await act(async () => { host.querySelector<HTMLInputElement>('input[type="checkbox"]')!.click(); });
    expect(host.textContent).toContain("浏览器临时存储不可用");
    expect(host.textContent).not.toContain("已开启本标签页临时保存");
    expect(host.querySelector("textarea")!.value).toBe("Private answer");
  });

  it("restores only the matching question and never overwrites server accepted text", async () => {
    setTemporaryDraftsEnabled(true);
    saveAnswerDraft("draft-test", "interview", "q", { text: "Unsubmitted", pending: null });
    await render(<AnswerComposer {...composerProps} />);
    expect(host.querySelector("textarea")!.value).toBe("Unsubmitted");
    await render(<AnswerComposer {...composerProps} question={{ ...question, id: "next" }} />);
    expect(host.querySelector("textarea")!.value).toBe("");
    const accepted = { id: "accepted", client_turn_id: "turn", raw_text: "Server authority", evaluation_status: "evaluated" as const, retry_operation_id: null };
    await render(<AnswerComposer {...composerProps} acceptedAnswer={accepted} />);
    expect(host.querySelector("textarea")).toBeNull();
    expect(host.textContent).toContain("Server authority");
    expect(host.textContent).not.toContain("Unsubmitted");
    expect(loadAnswerDraft("interview", "q")).toBeUndefined();
  });

  it("advances to the next question after analysis without canceling its terminal resource refresh", async () => {
    const completedRead = Promise.withResolvers<InterviewView>();
    const terminal = Promise.withResolvers<OperationView>();
    vi.mocked(api.getInterview).mockResolvedValueOnce(interview)
      .mockResolvedValueOnce({ ...interview, revision: 4, active_operation_id: "analysis",
        current_question: { ...question, accepted_answer: {
          id: "accepted", client_turn_id: "turn", raw_text: "My work",
          evaluation_status: "pending", retry_operation_id: null,
        } },
      }).mockReturnValueOnce(completedRead.promise);
    vi.mocked(api.getOperation).mockReturnValue(terminal.promise);
    vi.spyOn(api, "submitAnswer").mockResolvedValue({
      operation_id: "analysis", resource_type: "interview", resource_id: interview.id, status: "queued", events_url: "",
    });
    await render(<InterviewPage interviewId={interview.id} serviceReady navigate={vi.fn()} />);
    await input(host.querySelector("textarea")!, "My work");
    await click(/^提交回答$/);
    await act(async () => terminal.resolve({
      id: "analysis", kind: "interview.answer", status: "succeeded",
      resource_type: "interview", resource_id: interview.id, parent_operation_id: null,
      retry_trigger: null, retry_reason: null, next_operation_id: null, attempts: 1, attempt_limit: 3,
      result: null, error: null, last_event_seq: 2,
      created_at: "2026-10-03T00:00:00Z", updated_at: "2026-10-03T00:00:01Z", chain_started_at: "2026-10-03T00:00:00Z",
    }));
    await act(async () => completedRead.resolve({
      ...interview, revision: 5, current_question: { ...question, id: "next", wording: "Next question" },
    }));
    expect(host.textContent).toContain("Next question");
    expect(host.querySelector("textarea")!.value).toBe("");
    expect(host.textContent).not.toContain("正在分析");
  });

  it("keeps unknown-response answer text paired with its original key after remount; editing creates a new key", async () => {
    setTemporaryDraftsEnabled(true);
    const submit = vi.spyOn(api, "submitAnswer").mockRejectedValue(new TypeError("offline"));
    const page = <InterviewPage interviewId="interview" serviceReady navigate={vi.fn()} />;
    await render(page);
    await input(host.querySelector("textarea")!, "Original answer");
    await click(/^提交回答$/);
    const original = submit.mock.calls[0];
    await render(null); await render(page);
    expect(host.querySelector("textarea")!.value).toBe("Original answer");
    await click(/^重新提交$/);
    expect(submit.mock.calls[1]).toEqual(original);
    await click(/^修改回答$/);
    await input(host.querySelector("textarea")!, "Changed answer");
    await click(/^提交回答$/);
    expect(submit.mock.calls[2][1].answer_text).toBe("Changed answer");
    expect(submit.mock.calls[2][2]).not.toBe(original[2]);
  });

  it.each([
    new TypeError("old network failure"),
    new ApiError(409, { code: "REVISION_CONFLICT", message: "old revision", retryable: false, details: {} }),
    new ApiError(409, { code: "OPERATION_IN_PROGRESS", message: "old conflict", retryable: false, details: {} }),
    new ApiError(422, { code: "INVALID_STATE", message: "old permanent failure", retryable: false, details: {} }),
    new ApiError(429, { code: "CAPACITY_LIMITED", message: "old capacity", retryable: true, details: {} }),
  ])("does not reclaim a newer same-question draft after a delayed failure: %s", async (failure) => {
    const response = Promise.withResolvers<OperationAccepted>();
    vi.spyOn(api, "submitAnswer").mockReturnValue(response.promise);
    const page = <InterviewPage interviewId="interview" serviceReady navigate={vi.fn()} />;
    await render(page);
    await input(host.querySelector("textarea")!, "Original in flight");
    await click(/^提交回答$/);
    await render(<main>Knowledge packs</main>);
    await render(page);
    await click(/^修改回答$/);
    await input(host.querySelector("textarea")!, "New edited draft");
    await act(async () => response.reject(failure));
    expect(loadAnswerDraft("interview", "q")).toEqual({ text: "New edited draft", pending: null });
    expect(host.textContent).not.toContain("old");
    await render(null); await render(page);
    expect(host.querySelector("textarea")!.value).toBe("New edited draft");
    expect(host.textContent).not.toContain("重新提交");
  });

  it("does not clear a newer draft or read/replace the returned session after stale acceptance", async () => {
    const response = Promise.withResolvers<OperationAccepted>();
    vi.spyOn(api, "submitAnswer").mockReturnValue(response.promise);
    const navigate = vi.fn();
    const page = <InterviewPage interviewId="interview" serviceReady navigate={navigate} />;
    await render(page);
    await input(host.querySelector("textarea")!, "Old accepted later");
    await click(/^提交回答$/);
    await render(null); await render(page);
    await click(/^修改回答$/);
    await input(host.querySelector("textarea")!, "New unsent body");
    const reads = vi.mocked(api.getInterview).mock.calls.length;
    await act(async () => response.resolve({ operation_id: "old-op", resource_id: "interview", resource_type: "interview", status: "queued", events_url: "" }));
    expect(loadAnswerDraft("interview", "q")).toEqual({ text: "New unsent body", pending: null });
    expect(host.querySelector("textarea")!.value).toBe("New unsent body");
    expect(api.getInterview).toHaveBeenCalledTimes(reads);
    expect(navigate).not.toHaveBeenCalled();
    await render(null); await render(page);
    expect(host.querySelector("textarea")!.value).toBe("New unsent body");
  });

  it("restores an unmounted unknown response only while its exact command still owns the draft", async () => {
    const response = Promise.withResolvers<OperationAccepted>();
    const submit = vi.spyOn(api, "submitAnswer").mockReturnValueOnce(response.promise).mockRejectedValue(new TypeError("offline again"));
    const page = <InterviewPage interviewId="interview" serviceReady navigate={vi.fn()} />;
    await render(page);
    await input(host.querySelector("textarea")!, "Owned unknown body");
    await click(/^提交回答$/);
    const original = submit.mock.calls[0];
    await render(null);
    await act(async () => response.reject(new TypeError("offline")));
    expect(loadAnswerDraft("interview", "q")?.pending?.retryReason).toBe("network");
    await render(page);
    await click(/^重新提交$/);
    expect(submit.mock.calls[1]).toEqual(original);
  });

  it("does not replace a newer pending command with the same text and different key", async () => {
    const oldResponse = Promise.withResolvers<OperationAccepted>();
    const newResponse = Promise.withResolvers<OperationAccepted>();
    const submit = vi.spyOn(api, "submitAnswer").mockReturnValueOnce(oldResponse.promise).mockReturnValueOnce(newResponse.promise);
    const page = <InterviewPage interviewId="interview" serviceReady navigate={vi.fn()} />;
    await render(page);
    await input(host.querySelector("textarea")!, "Same answer body");
    await click(/^提交回答$/);
    await render(null); await render(page);
    await click(/^修改回答$/);
    await click(/^提交回答$/);
    const pending = loadAnswerDraft("interview", "q")?.pending;
    expect(submit.mock.calls[1][2]).not.toBe(submit.mock.calls[0][2]);
    await act(async () => oldResponse.reject(new TypeError("old offline")));
    expect(loadAnswerDraft("interview", "q")?.pending).toEqual(pending);
    expect(host.textContent).not.toContain("old offline");
  });

  it("never restores a failed old command over an authoritative accepted answer", async () => {
    const response = Promise.withResolvers<OperationAccepted>();
    vi.spyOn(api, "submitAnswer").mockReturnValue(response.promise);
    const page = <InterviewPage interviewId="interview" serviceReady navigate={vi.fn()} />;
    await render(page);
    await input(host.querySelector("textarea")!, "Accepted while response unknown");
    await click(/^提交回答$/);
    await render(null);
    vi.mocked(api.getInterview).mockResolvedValue({ ...interview, revision: 4,
      current_question: { ...question, accepted_answer: {
        id: "server-answer", client_turn_id: "server-turn", raw_text: "Server accepted body",
        evaluation_status: "evaluated", retry_operation_id: null,
      } },
    });
    await render(page);
    await act(async () => response.reject(new TypeError("old offline")));
    expect(loadAnswerDraft("interview", "q")).toBeUndefined();
    expect(host.textContent).toContain("Server accepted body");
    expect(host.querySelector("textarea")).toBeNull();
  });

  it("retains drafts while submission is in flight and clears only after acceptance", async () => {
    const response = Promise.withResolvers<OperationAccepted>();
    vi.spyOn(api, "submitAnswer").mockReturnValue(response.promise);
    await render(<InterviewPage interviewId="interview" serviceReady navigate={vi.fn()} />);
    await input(host.querySelector("textarea")!, "Waiting answer");
    await click(/^提交回答$/);
    expect(loadAnswerDraft("interview", "q")?.pending?.answerText).toBe("Waiting answer");
    vi.mocked(api.getInterview).mockResolvedValue({ ...interview, revision: 4, current_question: { ...question, accepted_answer: { id: "answer", client_turn_id: "turn", raw_text: "Waiting answer", evaluation_status: "evaluated", retry_operation_id: null } } });
    await act(async () => { response.resolve({ operation_id: "op", resource_id: "interview", resource_type: "interview", status: "queued", events_url: "" }); });
    expect(loadAnswerDraft("interview", "q")).toBeUndefined();
    expect(host.textContent).toContain("已保存的回答");
  });

  it("does not resurrect an accepted submission when the follow-up snapshot read fails", async () => {
    vi.spyOn(api, "submitAnswer").mockResolvedValue({ operation_id: "accepted-op", resource_id: "interview", resource_type: "interview", status: "queued", events_url: "" });
    await render(<InterviewPage interviewId="interview" serviceReady navigate={vi.fn()} />);
    await input(host.querySelector("textarea")!, "Accepted body");
    vi.mocked(api.getInterview).mockRejectedValue(new TypeError("snapshot offline"));
    await click(/^提交回答$/);
    expect(loadAnswerDraft("interview", "q")).toBeUndefined();
    expect(host.textContent).not.toContain("重新提交");
  });

  it("retains the current draft for an unconfirmed skip, then empties the confirmed next question", async () => {
    const control = vi.spyOn(api, "controlInterview").mockRejectedValue(new TypeError("offline"));
    await render(<InterviewPage interviewId="interview" serviceReady navigate={vi.fn()} />);
    await input(host.querySelector("textarea")!, "Keep until confirmed");
    await click(/^跳过本题$/);
    await click(/^确认跳过本题$/);
    expect(loadAnswerDraft("interview", "q")?.text).toBe("Keep until confirmed");
    control.mockResolvedValue({ operation_id: "skip-op", resource_id: "interview", resource_type: "interview", status: "queued", events_url: "" });
    vi.mocked(api.getInterview).mockResolvedValue({ ...interview, revision: 4, current_question: { ...question, id: "next" } });
    await click(/^重试上次操作$/);
    expect(loadAnswerDraft("interview", "q")).toBeUndefined();
    expect(host.querySelector("textarea")!.value).toBe("");
  });

  it("restores a pending JD plan as the exact request, with job inputs before pack selection", async () => {
    setTemporaryDraftsEnabled(true);
    const create = vi.spyOn(api, "createInterview").mockRejectedValue(new TypeError("offline"));
    const page = <PreparePage profileId="draft-test" interviewId={null} serviceReady navigate={vi.fn()} />;
    await render(page);
    await input(host.querySelector<HTMLInputElement>('input:not([type="checkbox"])')!, "Role");
    await input(host.querySelector("textarea")!, "Required skill");
    expect(host.querySelector(".jd-input")!.compareDocumentPosition(host.querySelector(".pack-selector")!) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    await click(/根据岗位生成面试计划/);
    const original = create.mock.calls[0];
    await render(null); await render(page);
    await click(/^重试生成计划$/);
    expect(create.mock.calls[1]).toEqual(original);
    expect(host.querySelector("textarea")!.value).toBe("Required skill");
  });

  it("shows submission rather than unknown-response recovery while a plan POST is pending", async () => {
    const response = Promise.withResolvers<OperationAccepted>();
    const create = vi.spyOn(api, "createInterview").mockReturnValueOnce(response.promise).mockRejectedValue(new TypeError("offline again"));
    await render(<PreparePage profileId="draft-test" interviewId={null} serviceReady navigate={vi.fn()} />);
    await input(host.querySelector<HTMLInputElement>('input:not([type="checkbox"])')!, "Role");
    await input(host.querySelector("textarea")!, "Required skill");
    await click(/根据岗位生成面试计划/);
    expect(host.textContent).toContain("正在提交面试计划");
    expect(host.textContent).not.toContain("上次请求未确认完成");
    expect([...host.querySelectorAll("button")].some((item) => item.textContent === "重试生成计划")).toBe(false);
    await act(async () => response.reject(new TypeError("offline")));
    expect(host.textContent).toContain("上次请求未确认完成");
    await click(/^重试生成计划$/);
    expect(create.mock.calls[1]).toEqual(create.mock.calls[0]);
  });

  it("keeps a 202 plan operation authoritative across a temporary resource 404 until ready", async () => {
    vi.useFakeTimers();
    const accepted: OperationAccepted = { operation_id: "plan-op", resource_id: "planned", resource_type: "interview", status: "queued", events_url: "" };
    vi.spyOn(api, "createInterview").mockResolvedValue(accepted);
    const navigate = vi.fn();
    await render(<PreparePage profileId="draft-test" interviewId={null} serviceReady navigate={navigate} />);
    await input(host.querySelector<HTMLInputElement>('input:not([type="checkbox"])')!, "Role");
    await input(host.querySelector("textarea")!, "Required skill");
    await click(/根据岗位生成面试计划/);
    const processing: OperationView = {
      id: "plan-op", kind: "interview.plan", status: "running", resource_type: "interview", resource_id: "planned",
      parent_operation_id: null, retry_trigger: null, retry_reason: null, next_operation_id: null,
      attempts: 1, attempt_limit: null, result: null, error: null, last_event_seq: 1,
      created_at: "2026-10-03T00:00:00Z", chain_started_at: "2026-10-03T00:00:00Z", updated_at: "2026-10-03T00:00:01Z",
    };
    vi.mocked(api.getOperation).mockResolvedValue(processing);
    vi.mocked(api.getInterview).mockRejectedValueOnce(new ApiError(404, {
      code: "RESOURCE_NOT_FOUND", message: "not materialized yet", retryable: false, details: {},
    }));
    await render(<PreparePage profileId="draft-test" interviewId="planned" serviceReady navigate={navigate} />);
    expect(host.textContent).not.toContain("计划不存在");
    expect(host.textContent).not.toContain("上次请求未确认完成");
    expect(api.createInterview).toHaveBeenCalledTimes(1);
    vi.mocked(api.getInterview).mockResolvedValue({ ...interview, id: "planned", status: "ready" });
    vi.mocked(api.getOperation).mockResolvedValue({ ...processing, status: "succeeded", last_event_seq: 2 });
    await act(async () => { vi.advanceTimersByTime(800); });
    expect(host.textContent).toContain("开始模拟面试");
    expect(host.textContent).not.toContain("计划不存在");
    expect(navigate.mock.calls).toEqual([["/profiles/draft-test/prepare?interview=planned", true]]);
    vi.useRealTimers();
  });

  it("shows a normal start POST as submitting and offers recovery only after an unknown outcome", async () => {
    const response = Promise.withResolvers<OperationAccepted>();
    const start = vi.spyOn(api, "startInterview").mockReturnValueOnce(response.promise).mockRejectedValue(new TypeError("still offline"));
    vi.mocked(api.getInterview).mockResolvedValue({ ...interview, status: "ready" });
    await render(<PreparePage profileId="draft-test" interviewId="interview" serviceReady navigate={vi.fn()} />);
    await click(/^开始模拟面试$/);
    expect(host.textContent).toContain("正在提交开始面试请求");
    expect(host.textContent).not.toContain("上次请求未确认完成");
    await act(async () => response.reject(new TypeError("offline")));
    expect(host.textContent).toContain("上次请求未确认完成");
    await click(/^重试开始面试$/);
    expect(start.mock.calls[1]).toEqual(start.mock.calls[0]);
  });
});
