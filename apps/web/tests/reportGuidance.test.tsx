// @vitest-environment happy-dom
import { act, type ReactNode, type MouseEventHandler } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { api, type InterviewView, type OperationView, type ReportView, type RootAssessmentView } from "../src/api";
import { ReportPage } from "../src/pages/ReportPage";
import { loadOperationId, saveOperationId } from "../src/storage";

vi.mock("@any-design/anyui/react", () => ({
  Button: ({ children, disabled, onClick }: { children?: ReactNode; disabled?: boolean; onClick?: MouseEventHandler<HTMLButtonElement> }) => <button disabled={disabled} onClick={onClick}>{children}</button>,
  Alert: ({ children, title }: { children?: ReactNode; title?: string }) => <section role="alert"><h2>{title}</h2>{children}</section>,
  Tag: ({ children }: { children?: ReactNode }) => <span>{children}</span>,
  Spinner: () => <span role="status" />,
}));

const interview: InterviewView = {
  id: "interview", revision: 1, status: "completed", run_mode: "fixture",
  profile_id: "profile", profile_snapshot_id: "snapshot", jd_text: null,
  jd_requirements: [], jd_source: {
    id: "jd", source_type: "user_provided", source_name: "test", content_hash: "hash",
    imported_at: "2026-10-03", version: 1, status: "ready", is_synthetic: false,
    source_url: null, retrieved_at: null, derived: false, upstream_source_name: null,
    upstream_url: null, upstream_retrieved_at: null, upstream_content_hash: null,
    derived_artifact_path: null, derived_content_hash: null, transformation_note: null,
  },
  root_plan: { slots: [], planner_version: "test", seed_bank_version: "test" },
  coverage_map: [], current_question: null, root_results: [], active_operation_id: null,
  stop_requested: false, report_id: "report", limitations: [],
  knowledge_pack: { binding: "legacy_unresolved", pack_release_id: null, profile_version: null, profile_digest: null, capabilities: [] },
};

function assessment(id: string, score: number | null): RootAssessmentView {
  return {
    id: `assessment-${id}`, root_question_id: id, question_text: `Question ${id}`,
    status: score === null ? "insufficient" : "scored", score, coverage: score === null ? 0 : 1,
    answers: [{ answer_id: `answer-${id}`, question_id: id, question_kind: "main", question_text: `Question ${id}`, raw_text: `Original ${id}` }],
    criterion_results: [], answer_ids: [`answer-${id}`],
  };
}

function report(assessments: RootAssessmentView[]): ReportView {
  return {
    id: "report", revision: 1, interview_id: "interview", completion: "complete", overall_score: null,
    root_assessments: assessments, improvements_status: "ready", active_operation_id: null,
    improved_answers: assessments.map((item) => ({
      root_question_id: item.root_question_id, original_answers: item.answers,
      rewritten_answer: `Rewritten ${item.root_question_id}\nKeep the exact text.`,
      segments: [], used_claim_ids: [], changes: [], cautions: [],
      missing_facts: item.root_question_id === "three" ? [{ prompt: "补充测量条件", reason: "原回答未说明条件" }] : [],
    })),
    source_claims: [],
    knowledge_pack: interview.knowledge_pack,
    coverage: {
      planned_root_count: assessments.length, asked_root_count: assessments.length,
      answered_root_count: assessments.length, scored_root_count: assessments.filter((item) => item.status === "scored").length,
      insufficient_root_count: assessments.filter((item) => item.status === "insufficient").length,
      disputed_root_count: 0, skipped_root_count: 0, unmeasured_root_count: 0, skipped_question_count: 0, overall_eligible: false,
    },
    limitations: [], run_metadata: { run_mode: "fixture", seed_bank_version: "test", rubric_version: "test", prompt_versions: {}, policy_version: "test", model_fingerprint: null, sdk_version: null, scoring_version: "test" },
  };
}

let root: Root;
let host: HTMLDivElement;
const eventSources: EventTarget[] = [];

function button(text: string): HTMLButtonElement {
  const result = [...host.querySelectorAll<HTMLButtonElement>("button")].find((item) => item.textContent === text);
  if (!result) throw new Error(`Missing button: ${text}`);
  return result;
}

async function renderReport(value: ReportView) {
  vi.spyOn(api, "getInterview").mockResolvedValue(interview);
  vi.spyOn(api, "getReport").mockResolvedValue(value);
  await act(async () => root.render(<ReportPage interviewId="interview" serviceReady contentGenerationReady navigate={vi.fn()} />));
}

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  eventSources.length = 0;
  vi.stubGlobal("EventSource", class extends EventTarget {
    onerror: (() => void) | null = null;
    close = vi.fn();
    constructor() {
      super();
      eventSources.push(this);
    }
  });
  sessionStorage.clear();
  localStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
});

afterEach(async () => {
  await act(async () => root.unmount());
  host.remove();
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("report frozen capability provenance", () => {
  it("reads capability labels and rule identity from the report, not current interview metadata", async () => {
    const capability = { competency_id: "python.mutable", label: "报告冻结的能力名称" };
    const value: ReportView = {
      ...report([assessment("one", 80)]),
      knowledge_pack: {
        binding: "frozen", pack_release_id: "kpr_0123456789abcdef", name: "报告冻结岗位包",
        profile_version: "4.5.6", profile_digest: "sha256:report-rules", capabilities: [capability],
      },
      limitations: [`未覆盖 ${capability.competency_id}`],
    };
    await renderReport(value);
    expect(host.querySelector(".report-limitations")?.textContent).toContain(capability.label);
    expect(host.querySelector(".report-limitations")?.textContent).not.toContain(capability.competency_id);
    expect(host.querySelector(".report-limitations")?.textContent).toContain(value.knowledge_pack.profile_version);
    expect(host.querySelector(".report-limitations")?.textContent).toContain(value.knowledge_pack.profile_digest);
  });

  it("retains IDs rather than guessing labels when historical rules cannot be read", async () => {
    const competency = "embedded.c.basics";
    await renderReport({
      ...report([assessment("one", 80)]),
      knowledge_pack: { binding: "frozen_unavailable", pack_release_id: "kpr_0123456789abcdef", profile_version: null, profile_digest: null, capabilities: [] },
      limitations: [competency],
    });
    expect(host.querySelector(".report-limitations li")?.textContent).toBe(competency);
  });
});

describe("improvement segments", () => {
  it("highlights the exact quote and lists the confirmed claim cited by the clicked segment", async () => {
    const base = report([assessment("one", 80)]);
    const item = base.improved_answers[0];
    const segmented: ReportView = {
      ...base,
      improved_answers: [{
        ...item,
        rewritten_answer: "Original one，并且负责 UART 接收。",
        segments: [
          { text: "Original one", source_refs: [{ type: "answer_quote", answer_id: "answer-one", exact_quote: "Original" }] },
          { text: "，并且负责 UART 接收。", source_refs: [{ type: "claim", claim_id: "claim-uart" }] },
        ],
        used_claim_ids: ["claim-uart"],
      }],
      source_claims: [{ id: "claim-uart", text: "负责 STM32 端 UART 接收与解析" }],
    };
    await renderReport(segmented);
    await act(async () => (host.querySelector("#report-tab-improvement") as HTMLButtonElement).click());
    const segments = [...host.querySelectorAll<HTMLButtonElement>(".improved-segment")];
    expect(segments.map((segment) => segment.textContent)).toEqual(["Original one", "，并且负责 UART 接收。"]);
    expect(host.querySelector(".segment-sources")).toBeNull();

    await act(async () => segments[0].click());
    expect(host.querySelector(".answer-comparison mark")?.textContent).toBe("Original");
    expect(host.querySelector(".segment-sources")?.textContent).toContain("你的原话");

    await act(async () => segments[1].click());
    expect(host.querySelector(".answer-comparison mark")).toBeNull();
    expect(host.querySelector(".segment-sources blockquote")?.textContent).toBe("负责 STM32 端 UART 接收与解析");
    expect(segments[1].getAttribute("aria-pressed")).toBe("true");
  });

  it("replaces the comparison and resets the selected segment when switching questions", async () => {
    await renderReport(report([assessment("one", 80), assessment("two", 60), assessment("three", 70)]));
    await act(async () => (host.querySelector("#report-tab-improvement") as HTMLButtonElement).click());
    for (const index of [2, 0, 1, 2]) {
      await act(async () => host.querySelectorAll<HTMLButtonElement>(".question-rail-item")[index].click());
    }
    expect(host.querySelectorAll(".answer-comparison")).toHaveLength(1);
    expect(host.querySelectorAll(".selected-improvement details")).toHaveLength(1);
    expect(host.querySelector(".answer-comparison")?.textContent).toContain("Original three");
  });

  it("falls back to the whole rewritten text when segments do not reproduce it", async () => {
    await renderReport(report([assessment("one", 80)]));
    await act(async () => (host.querySelector("#report-tab-improvement") as HTMLButtonElement).click());
    expect(host.querySelector(".improved-segment")).toBeNull();
    expect(host.querySelector(".answer-comparison")?.textContent).toContain("Rewritten one");
  });
});

describe("report next review guidance", () => {
  it("selects the lower-scored question without reordering chronology and opens generated missing facts", async () => {
    await renderReport(report([assessment("one", 90), assessment("two", 40), assessment("three", 60)]));
    expect([...host.querySelectorAll(".question-rail-title")].map((item) => item.textContent)).toEqual(["Question one", "Question two", "Question three"]);
    await act(async () => button("查看第 2 题评分依据").click());
    expect(host.querySelector(".report-question-context h2")?.textContent).toBe("Question two");
    expect(host.querySelector("#report-tab-assessment")?.getAttribute("aria-selected")).toBe("true");
    await act(async () => button("查看第 3 题待补充项").click());
    expect(host.querySelector(".report-question-context h2")?.textContent).toBe("Question three");
    expect(host.querySelector("#report-tab-improvement")?.getAttribute("aria-selected")).toBe("true");
    expect(host.querySelector(".selected-improvement details")?.hasAttribute("open")).toBe(true);
    expect(host.querySelector(".answer-comparison")?.textContent).toContain("Original three");
    expect(host.querySelector(".selected-improvement")?.textContent).toContain("补充测量条件：原回答未说明条件");
  });

  it("keeps all-unscored results neutral and links the existing status", async () => {
    await renderReport(report([assessment("one", null), assessment("two", null)]));
    await act(async () => button("查看第 1 题状态与回答").click());
    expect(host.querySelector(".report-question-context h2")?.textContent).toBe("Question one");
    expect(host.querySelector("#report-tab-assessment")?.getAttribute("aria-selected")).toBe("true");
  });

  it("offers all five questions in the compact chooser and preserves tab keyboard/focus semantics", async () => {
    const narrowMedia = {
      matches: true, media: "(max-width: 820px)", onchange: null,
      addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn(),
      addListener: vi.fn(), removeListener: vi.fn(),
    };
    vi.spyOn(window, "matchMedia").mockReturnValue(narrowMedia);
    await renderReport(report([
      assessment("one", 90), assessment("two", 40), assessment("three", 60),
      assessment("four", 75), assessment("five", 80),
    ]));
    const overview = host.querySelector<HTMLDetailsElement>(".report-action-overview")!;
    expect(overview.open).toBe(false);
    const chooser = host.querySelector<HTMLSelectElement>(".report-question-chooser select")!;
    expect(chooser.labels?.[0]?.textContent).toContain("逐题查看");
    expect([...chooser.options].map((item) => item.value)).toEqual(["one", "two", "three", "four", "five"]);
    await act(async () => {
      chooser.value = "five";
      chooser.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(host.querySelector(".report-question-context h2")?.textContent).toBe("Question five");
    expect(host.querySelector(".report-original-answers")?.textContent).toContain("Original five");
    const assessmentTab = host.querySelector<HTMLButtonElement>("#report-tab-assessment")!;
    await act(async () => {
      assessmentTab.focus();
      assessmentTab.dispatchEvent(new KeyboardEvent("keydown", { key: "ArrowRight", bubbles: true }));
      const frame = Promise.withResolvers<number>();
      requestAnimationFrame(frame.resolve);
      await frame.promise;
    });
    const improvementTab = host.querySelector<HTMLButtonElement>("#report-tab-improvement")!;
    expect(improvementTab.getAttribute("aria-selected")).toBe("true");
    expect(document.activeElement).toBe(improvementTab);
    expect(assessmentTab.tabIndex).toBe(-1);
    expect(host.querySelector("#report-panel-improvement")?.getAttribute("aria-labelledby")).toBe(improvementTab.id);
    expect(host.querySelector(".selected-improvement")?.textContent).toContain("Rewritten five");
    await act(async () => {
      improvementTab.dispatchEvent(new KeyboardEvent("keydown", { key: "Home", bubbles: true }));
      const frame = Promise.withResolvers<number>();
      requestAnimationFrame(frame.resolve);
      await frame.promise;
    });
    expect(document.activeElement).toBe(assessmentTab);
    expect(assessmentTab.getAttribute("aria-selected")).toBe("true");
    await act(async () => host.querySelector<HTMLElement>(".report-action-overview summary")!.click());
    expect(overview.open).toBe(true);
    await act(async () => button("查看第 2 题评分依据").click());
    expect(chooser.value).toBe("two");
    expect(host.querySelector(".report-question-context h2")?.textContent).toBe("Question two");
  });

  it.each(["unavailable", "denied"])("reports honest clipboard failure when %s", async (reason) => {
    vi.spyOn(navigator, "clipboard", "get").mockReturnValue(reason === "unavailable"
      ? undefined as unknown as Clipboard
      : { writeText: vi.fn().mockRejectedValue(new Error("denied")) } as unknown as Clipboard);
    await renderReport(report([assessment("three", 60)]));
    await act(async () => button("查看第 1 题待补充项").click());
    await act(async () => button("复制优化后的回答").click());
    const message = host.querySelector(".report-copy-action [role='status']")?.textContent;
    expect(message).toContain("手动复制");
    expect(message).not.toContain("已复制");
  });
});

describe("report automatic successor recovery", () => {
  const parent: OperationView = {
    id: "coach-parent", kind: "report.coach", status: "failed", resource_type: "report",
    resource_id: "report", parent_operation_id: null, retry_trigger: null,
    retry_reason: null, chain_started_at: "2026-10-03T00:00:00Z", attempt_limit: 3,
    next_operation_id: "coach-child", attempts: 1, result: null,
    error: { code: "MODEL_REQUEST_FAILED", message: "parent-failure", retryable: false },
    last_event_seq: 3, created_at: "2026-10-03T00:00:00Z", updated_at: "2026-10-03T00:00:01Z",
  };
  const automatic: OperationView = {
    ...parent, id: "coach-child", parent_operation_id: parent.id, retry_trigger: "automatic", retry_reason: "transient",
    next_operation_id: null, status: "running", attempts: 2, error: null,
  };

  it("keeps polling after a transient status-read error without claiming it stopped or sending another command", async () => {
    vi.useFakeTimers();
    const value = { ...report([assessment("one", 73)]), improvements_status: "failed" as const,
      active_operation_id: automatic.id, improved_answers: [],
    };
    vi.spyOn(api, "getInterview").mockResolvedValue(interview);
    vi.spyOn(api, "getReport").mockResolvedValue(value);
    const get = vi.spyOn(api, "getOperation").mockRejectedValueOnce(new TypeError("temporary offline")).mockResolvedValue(automatic);
    const retry = vi.spyOn(api, "retryOperation");
    const generate = vi.spyOn(api, "generateReportImprovements");
    await act(async () => root.render(<ReportPage interviewId="interview" serviceReady contentGenerationReady navigate={vi.fn()} />));
    await act(async () => host.querySelector<HTMLButtonElement>("#report-tab-improvement")!.click());
    expect(host.textContent).toContain("页面仍会继续查询处理状态");
    expect(host.textContent).not.toContain("停止重复查询");
    await act(async () => { vi.advanceTimersByTime(800); });
    expect(get).toHaveBeenCalledTimes(2);
    expect(host.textContent).toContain("正在自动重试");
    expect(host.textContent).not.toContain("页面仍会继续查询处理状态");
    expect(retry).not.toHaveBeenCalled();
    expect(generate).not.toHaveBeenCalled();
  });

  it.each([true, false])("retains scores and gates manual retry on the child budget (%s)", async (retryable) => {
    const original = report([assessment("one", 73)]);
    let resource: ReportView = {
      ...original, improvements_status: "failed", active_operation_id: parent.id, improved_answers: [],
    };
    let child = automatic;
    vi.spyOn(api, "getInterview").mockResolvedValue(interview);
    vi.spyOn(api, "getReport").mockImplementation(async () => resource);
    vi.spyOn(api, "getOperation").mockImplementation(async (id) => id === parent.id ? parent : child);
    const retry = vi.spyOn(api, "retryOperation");
    const generate = vi.spyOn(api, "generateReportImprovements");
    await act(async () => root.render(<ReportPage interviewId="interview" serviceReady contentGenerationReady navigate={vi.fn()} />));
    await act(async () => host.querySelector<HTMLButtonElement>("#report-tab-improvement")!.click());
    expect(loadOperationId("report", "report")).toBe(child.id);
    expect(host.textContent).toContain("自动重试");
    expect(host.textContent).toContain("已尝试 2 次");
    expect(host.textContent).not.toContain("parent-failure");
    expect(host.querySelector(".question-rail")?.textContent).toContain("73");
    expect([...host.querySelectorAll("button")].some((item) => /重试回答优化/.test(item.textContent ?? ""))).toBe(false);
    resource = { ...resource, revision: 3, active_operation_id: child.id };
    child = {
      ...child, status: "failed", last_event_seq: 4,
      error: { code: "MODEL_REQUEST_FAILED", message: "child-failure", retryable },
    };
    await act(async () => eventSources.at(-1)!.dispatchEvent(new Event("operation.failed")));
    expect(host.textContent).toContain("child-failure");
    expect([...host.querySelectorAll("button")].some((item) => /重试回答优化/.test(item.textContent ?? ""))).toBe(retryable);
    expect(host.querySelector(".question-rail")?.textContent).toContain("73");
    expect(retry).not.toHaveBeenCalled();
    expect(generate).not.toHaveBeenCalled();
  });

  it("recovers a server-selected child and keeps its accepted output after stale parent data", async () => {
    const ready = { ...report([assessment("one", 73)]), revision: 4 };
    let resource: ReportView = {
      ...ready, revision: 2, improvements_status: "generating",
      active_operation_id: automatic.id, improved_answers: [],
    };
    const lateChild = Promise.withResolvers<OperationView>();
    saveOperationId("report", "report", parent.id);
    vi.spyOn(api, "getInterview").mockResolvedValue(interview);
    vi.spyOn(api, "getReport").mockImplementation(async () => resource);
    const get = vi.spyOn(api, "getOperation").mockResolvedValue(automatic);
    get.mockImplementationOnce(() => lateChild.promise);
    await act(async () => root.render(<ReportPage interviewId="interview" serviceReady contentGenerationReady navigate={vi.fn()} />));
    expect(get.mock.calls.map(([id]) => id)).toEqual([automatic.id]);
    resource = ready;
    get.mockResolvedValue({ ...automatic, status: "succeeded", last_event_seq: 4 });
    await act(async () => eventSources.at(-1)!.dispatchEvent(new Event("operation.completed")));
    await act(async () => host.querySelector<HTMLButtonElement>("#report-tab-improvement")!.click());
    expect(host.querySelector(".selected-improvement")?.textContent).toContain("Rewritten one");
    expect(loadOperationId("report", "report")).toBeNull();
    await act(async () => lateChild.resolve(parent));
    expect(host.querySelector(".selected-improvement")?.textContent).toContain("Rewritten one");
    expect(host.textContent).not.toContain("parent-failure");
    expect(host.querySelector(".question-rail")?.textContent).toContain("73");
  });
});
