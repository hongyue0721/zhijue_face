// @vitest-environment happy-dom
import { act, type ReactNode, type Ref, type MouseEventHandler } from "react";
import { createRoot, type Root } from "react-dom/client";
import { afterEach, beforeEach, describe, expect, it, vi, type Mock } from "vitest";
import App from "../src/App";
import { api, type OperationAccepted, type OperationView, type ProfileView, type ReadinessView, type ResumeDraftView } from "../src/api";
import { KnowledgePacksPage } from "../src/pages/KnowledgePacksPage";
import { ResumeDraftPage } from "../src/pages/ResumeDraftPage";
import { useOperationMonitor } from "../src/hooks/useOperationMonitor";
import { OperationStatus } from "../src/components/common/OperationStatus";
import { acceptsProfileSnapshot } from "../src/profileSnapshots";
import { clearPrepareDraft, prepareDraftKey } from "../src/prepareDrafts";
import { knowledgePacksPath, knowledgeReturnPath, parseRoute, preparePath, resumeDraftPath, startPath } from "../src/routing";
import { loadOperationId, saveOperationId } from "../src/storage";

type ChildrenProps = { children?: ReactNode };
type ButtonProps = ChildrenProps & {
  disabled?: boolean; loading?: boolean; onClick?: MouseEventHandler<HTMLButtonElement>;
  ref?: Ref<HTMLButtonElement>; "aria-label"?: string;
};
type FieldProps<T> = {
  modelValue: string; onUpdateModelValue: (value: string) => void; disabled?: boolean; ref?: Ref<T>;
};

// Keep application hooks, API orchestration, routes and dialogs real. Only the
// design-system bridge is replaced with native controls for DOM interaction.
vi.mock("@any-design/anyui/react", () => ({
  Button: ({ children, disabled, loading, onClick, ref, ...props }: ButtonProps) => (
    <button ref={ref} disabled={disabled || loading} onClick={onClick} aria-label={props["aria-label"]}>{children}</button>
  ),
  Input: ({ modelValue, onUpdateModelValue, disabled }: FieldProps<HTMLInputElement>) => (
    <input value={modelValue} disabled={disabled} onInput={(event) => onUpdateModelValue(event.currentTarget.value)} />
  ),
  Textarea: ({ modelValue, onUpdateModelValue, disabled, ref }: FieldProps<HTMLTextAreaElement>) => (
    <textarea ref={ref} value={modelValue} disabled={disabled} onInput={(event) => onUpdateModelValue(event.currentTarget.value)} />
  ),
  Alert: ({ title, children }: ChildrenProps & { title?: string }) => <section role="alert"><h2>{title}</h2>{children}</section>,
  Tag: ({ children }: ChildrenProps) => <span>{children}</span>,
  Spinner: () => <span role="status" />,
  Progress: () => <progress />,
  Drawer: ({ children, isOpen }: ChildrenProps & { isOpen?: boolean }) => isOpen ? <aside>{children}</aside> : null,
  Collapse: ({ children }: ChildrenProps) => <div>{children}</div>,
}));


function profile(id: string, revision = 1, confirmed = false): ProfileView {
  const claim = {
    id: `${id}-claim`, text: `${id} factual experience`, status: confirmed ? "confirmed" as const : "proposed" as const,
    source_block_ids: [], source_quotes: [{ origin: "user_input" }], supersedes_id: null,
  };
  return {
    id, revision, display_name: id, synthetic: false, status: "active", documents: [],
    proposed_claims: confirmed ? [] : [claim], confirmed_claims: confirmed ? [claim] : [],
    latest_snapshot_id: confirmed ? `${id}-snapshot` : null, active_operation_id: null,
    snapshot_activation: confirmed ? { snapshot_id: `${id}-snapshot`, status: "ready", operation_id: null } : null,
  };
}

function readiness(run_mode: ReadinessView["run_mode"], content_generation: ReadinessView["content_generation"]): ReadinessView {
  return { status: "ok", run_mode, content_generation, data_mode: "user", database: "ready", knowledge: "ready", model: "ready", seed_bank_version: "test" };
}

function operation(id: string, retryable: boolean): OperationView {
  return {
    id, kind: "knowledge_pack.import", status: "failed", resource_type: "knowledge_pack", resource_id: "import",
    parent_operation_id: null, retry_trigger: null, next_operation_id: null, attempts: 1, result: null,
    retry_reason: null, chain_started_at: "2026-10-03T00:00:00Z", attempt_limit: null,
    error: { code: retryable ? "DEPENDENCY_UNAVAILABLE" : "INVALID_PACK", message: `failure-${id}`, retryable },
    last_event_seq: 2, created_at: "2026-10-03T00:00:00Z", updated_at: "2026-10-03T00:00:01Z",
  };
}

let root: Root;
let host: HTMLDivElement;
const eventSources: Array<EventTarget & { url: string; close: Mock }> = [];

async function render(node: ReactNode) {
  await act(async () => { root.render(node); });
}

function button(pattern: RegExp): HTMLButtonElement {
  const found = [...document.querySelectorAll<HTMLButtonElement>("button")]
    .find((item) => pattern.test(item.getAttribute("aria-label") ?? item.textContent ?? ""));
  if (!found) throw new Error(`Missing action ${pattern}`);
  return found;
}

async function click(element: HTMLElement) {
  await act(async () => { element.click(); });
}

async function input(element: HTMLInputElement | HTMLTextAreaElement, value: string) {
  await act(async () => {
    element.value = value;
    element.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

beforeEach(() => {
  vi.stubGlobal("IS_REACT_ACT_ENVIRONMENT", true);
  eventSources.length = 0;
  vi.stubGlobal("EventSource", class extends EventTarget {
    onerror: (() => void) | null = null;
    close = vi.fn();
    constructor(public url: string) {
      super();
      eventSources.push(this);
    }
  });
  Object.defineProperty(HTMLDialogElement.prototype, "showModal", { configurable: true, value() { this.open = true; } });
  Object.defineProperty(HTMLDialogElement.prototype, "close", { configurable: true, value() { this.open = false; } });
  vi.spyOn(window, "scrollTo").mockImplementation(() => undefined);
  window.history.replaceState({}, "", "/start");
  sessionStorage.clear();
  localStorage.clear();
  host = document.createElement("div");
  document.body.append(host);
  root = createRoot(host);
  vi.spyOn(api, "ready").mockResolvedValue(readiness("live", "configured"));
  vi.spyOn(api, "listKnowledgePacks").mockResolvedValue({
    items: [], default_pack_release_id: null,
    import_limits: { max_upload_bytes: 1024, max_extracted_total_bytes: 2048, max_single_file_bytes: 1024, max_entries: 10, max_path_depth: 3 },
  });
});

afterEach(async () => {
  await act(async () => { root.unmount(); });
  host.remove();
  clearPrepareDraft(prepareDraftKey("draft-profile", null));
  vi.useRealTimers();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

describe("profile response ownership", () => {
  it("rejects old revisions and responses from another profile", () => {
    const current = profile("one", 8);
    expect(acceptsProfileSnapshot(current, profile("one", 7), "one")).toBe(false);
    expect(acceptsProfileSnapshot(current, profile("two", 90), "one")).toBe(false);
    expect(acceptsProfileSnapshot(null, profile("one"), "two")).toBe(false);
    expect(acceptsProfileSnapshot(current, profile("one", 9), "one")).toBe(true);
  });

  it("adopts the creation snapshot without a racing GET and confirms the written revision", async () => {
    const created = { ...profile("new-profile"), proposed_claims: [] };
    const written = profile(created.id, 2);
    const factResponse = Promise.withResolvers<ProfileView>();
    vi.spyOn(api, "createProfile").mockResolvedValue(created);
    const add = vi.spyOn(api, "addFacts").mockReturnValue(factResponse.promise);
    const get = vi.spyOn(api, "getProfile").mockResolvedValue(written);
    const confirm = vi.spyOn(api, "confirm").mockResolvedValue({ operation_id: "confirm-1", resource_id: written.id, resource_type: "profile", status: "queued", events_url: "" });
    vi.spyOn(api, "getOperation").mockReturnValue(Promise.withResolvers<OperationView>().promise);
    await render(<App />);
    await click(button(/手动填写/));
    await input(document.querySelector("textarea")!, "I measured interrupt latency on the target device.");
    await click(button(/加入待核对/));
    expect(add).toHaveBeenCalledWith(created.id, 1, ["I measured interrupt latency on the target device."]);
    expect(get).not.toHaveBeenCalled();
    expect(window.location.search).toBe(`?profile=${created.id}`);
    await act(async () => { factResponse.resolve(written); });
    expect(window.location.search).toBe(`?profile=${written.id}`);
    await click(button(/^采用该事实$/));
    await click(button(/提交.*条选择/));
    expect(confirm).toHaveBeenCalledWith(written.id, 2, [{ claim_id: written.proposed_claims[0].id, action: "accept" }], expect.any(String));
  });

  it("does not show a late GET from the profile left through history navigation", async () => {
    const old = Promise.withResolvers<ProfileView>();
    vi.spyOn(api, "getProfile").mockImplementation((id) => id === "old" ? old.promise : Promise.resolve(profile("new", 5)));
    window.history.replaceState({}, "", startPath("old"));
    await render(<App />);
    await act(async () => {
      window.history.pushState({}, "", startPath("new"));
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await act(async () => { old.resolve(profile("old", 90)); });
    expect(host.textContent).toContain("new factual experience");
    expect(host.textContent).not.toContain("old factual experience");
    expect(window.location.search).toBe("?profile=new");
  });

  it("ignores the completed first write after switching to another profile", async () => {
    const pending = Promise.withResolvers<ProfileView>();
    vi.spyOn(api, "createProfile").mockResolvedValue({ ...profile("created"), proposed_claims: [] });
    vi.spyOn(api, "addFacts").mockReturnValue(pending.promise);
    vi.spyOn(api, "getProfile").mockResolvedValue(profile("other", 9));
    await render(<App />);
    await click(button(/手动填写/));
    await input(document.querySelector("textarea")!, "An unfinished write belonging to the old profile.");
    await click(button(/加入待核对/));
    await act(async () => {
      window.history.pushState({}, "", startPath("other"));
      window.dispatchEvent(new PopStateEvent("popstate"));
    });
    await act(async () => { pending.resolve(profile("created", 2)); });
    expect(window.location.search).toBe("?profile=other");
    expect(host.textContent).toContain("other factual experience");
    expect(host.textContent).not.toContain("created factual experience");
  });
});

describe("knowledge import recovery", () => {
  it("allows closing an accepted import without losing recovery or enabling duplicate submission", async () => {
    saveOperationId("packs", "import", "queued-import");
    vi.spyOn(api, "getOperation").mockResolvedValue({
      ...operation("queued-import", false), status: "queued", error: null,
    });
    await render(<KnowledgePacksPage releaseId={null} returnTo="/start" navigate={vi.fn()} />);
    await click(button(/^导入岗位包$/));
    expect(button(/^关闭$/).disabled).toBe(false);
    expect(button(/^后台处理中/).disabled).toBe(true);
    await click(button(/^关闭$/));
    expect(document.querySelector("dialog")?.open ?? false).toBe(false);
    expect(loadOperationId("packs", "import")).toBe("queued-import");
    await click(button(/^导入岗位包$/));
    expect(button(/^后台处理中/).disabled).toBe(true);
  });

  it("retains terminal failure across remount, retries it, and clears it only after a replacement file", async () => {
    saveOperationId("packs", "import", "failed-original");
    vi.spyOn(api, "getOperation").mockImplementation(async (id) => operation(id, id === "failed-original"));
    const retry = vi.spyOn(api, "retryOperation").mockResolvedValue({ operation_id: "failed-retry", resource_type: "knowledge_pack", resource_id: "import", status: "queued", events_url: "" });
    const navigate = vi.fn();
    const page = <KnowledgePacksPage releaseId={null} returnTo={startPath("profile-a")} navigate={navigate} />;
    await render(page);
    expect(host.textContent).toContain("failure-failed-original");
    expect(loadOperationId("packs", "import")).toBe("failed-original");
    await render(null);
    await render(page);
    await click(button(/^重试导入$/));
    expect(retry).toHaveBeenCalledWith("failed-original", 1, expect.any(String));
    expect(host.textContent).toContain("failure-failed-retry");
    expect(loadOperationId("packs", "import")).toBe("failed-retry");
    await click(button(/^导入岗位包$/));
    const submit = button(/^提交导入$/);
    expect(submit.disabled).toBe(true);
    const picker = document.querySelector<HTMLInputElement>('input[type="file"]')!;
    await act(async () => {
      Object.defineProperty(picker, "files", { configurable: true, value: [new File(["replacement"], "fixed.zip", { type: "application/zip" })] });
      picker.dispatchEvent(new Event("change", { bubbles: true }));
    });
    expect(loadOperationId("packs", "import")).toBeNull();
    expect(host.textContent).not.toContain("failure-failed-retry");
    expect(submit.disabled).toBe(false);
  });

  it("clears a successful operation and leaves a completion result", async () => {
    saveOperationId("packs", "import", "successful");
    vi.spyOn(api, "getOperation").mockResolvedValue({ ...operation("successful", false), status: "succeeded", error: null, result: { pack_id: "registered-pack", version: "3", review_status: "unreviewed", selectable_for_new_interview: false } });
    await render(<KnowledgePacksPage releaseId={null} returnTo="/start" navigate={vi.fn()} />);
    expect(loadOperationId("packs", "import")).toBeNull();
    expect(host.textContent).toContain("registered-pack");
  });
});

describe("profile review selection", () => {
  it("keeps every choice made within one frame and selects a section only on explicit request", async () => {
    const base = profile("review-profile", 3);
    const claims = ["a", "b", "c"].map((id) => ({
      ...base.proposed_claims[0], id: `claim-${id}`, text: `fact ${id}`,
      source_quotes: [{ origin: "text_layer", section: "project", exact_quote: `fact ${id}` }],
    }));
    vi.spyOn(api, "getProfile").mockResolvedValue({ ...base, proposed_claims: claims });
    const confirm = vi.spyOn(api, "confirm");
    window.history.replaceState({}, "", startPath("review-profile"));
    await render(<App />);
    const accepts = [...host.querySelectorAll<HTMLButtonElement>('button[aria-label="采用该事实"]')];
    expect(accepts).toHaveLength(3);
    expect(host.textContent).not.toContain("尚未提交");
    // 同一帧内两次选择：旧实现用闭包里的旧 decisions 计算，后一次会覆盖前一次。
    await act(async () => { accepts[0].click(); accepts[1].click(); });
    expect(host.textContent).toContain("已选择 2 条，尚未提交");
    await click(button(/^本组全部采用$/));
    expect(host.textContent).toContain("已选择 3 条，尚未提交");
    await click(button(/^清除本组选择$/));
    expect(host.textContent).not.toContain("尚未提交");
    expect(confirm).not.toHaveBeenCalled();
  });
});

describe("knowledge round trips and privacy", () => {
  it("keeps the actual profile/interview return address when switching selected releases", () => {
    const returnTo = preparePath("profile a", "interview/b");
    const path = knowledgePacksPath("release a", returnTo);
    const url = new URL(path, "https://local.invalid");
    const route = parseRoute(url.pathname, url.search);
    expect(route).toEqual({ page: "packs", releaseId: "release a", returnTo });
    expect(knowledgeReturnPath("https://elsewhere.invalid/")).toBe("/start");
    expect(knowledgeReturnPath("//elsewhere.invalid/")).toBe("/start");
    expect(knowledgeReturnPath("/knowledge-packs?returnTo=/knowledge-packs")).toBe("/start");
  });

  it("restores unsubmitted JD fields through both preparation and header navigation without browser storage", async () => {
    vi.spyOn(api, "getProfile").mockResolvedValue(profile("draft-profile", 6, true));
    window.history.replaceState({}, "", preparePath("draft-profile"));
    await render(<App />);
    const fields = [...host.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>('input:not([type="checkbox"]), textarea')];
    const values = [" private role ", " required raw line\n", " optional raw line ", " responsibility raw line "];
    expect(fields).toHaveLength(values.length);
    for (let index = 0; index < fields.length; index += 1) await input(fields[index], values[index]);
    for (const entry of [/管理岗位知识包/, /^岗位知识$/]) {
      await click(button(entry));
      expect(window.location.pathname).toBe("/knowledge-packs");
      await click(button(/返回上一页/));
      expect(window.location.pathname).toBe(preparePath("draft-profile"));
      expect([...host.querySelectorAll<HTMLInputElement | HTMLTextAreaElement>('input:not([type="checkbox"]), textarea')].map((field) => field.value)).toEqual(values);
    }
    for (const storage of [sessionStorage, localStorage]) {
      const body = Array.from({ length: storage.length }, (_, index) => storage.getItem(storage.key(index)!)).join("");
      for (const value of values) expect(body).not.toContain(value.trim());
    }
  });
});

describe("content capability gates", () => {
  it.each([
    ["fixture", "absent", false], ["live", "absent", false],
    ["fixture", "configured", true], ["live", "configured", true],
  ] as const)("uses actual capability in %s / %s", async (mode, capability, enabled) => {
    vi.mocked(api.ready).mockResolvedValue(readiness(mode, capability));
    vi.spyOn(api, "getProfile").mockResolvedValue(profile("content-profile", 4, true));
    const create = vi.spyOn(api, "createResumeDraft").mockReturnValue(Promise.withResolvers<OperationAccepted>().promise);
    window.history.replaceState({}, "", startPath("content-profile"));
    await render(<App />);
    const generate = button(/^整理简历$/);
    expect(generate.disabled).toBe(!enabled);
    await click(generate);
    expect(create).toHaveBeenCalledTimes(enabled ? 1 : 0);
    expect(button(/进入面试准备/).disabled).toBe(enabled); // only an in-flight generation blocks unrelated writes
  });
});

describe("existing resume access without generation", () => {
  const draft: ResumeDraftView = {
    id: "existing-draft", revision: 7, profile_id: "existing-profile",
    profile_snapshot_id: "existing-snapshot", interview_id: null, status: "draft",
    sections: [], source_claims: [], source_claim_ids: [], changes: [], missing_facts: [],
    cautions: [], target_context: { kind: "generic" }, active_operation_id: null, run_metadata: {},
  };

  it("still confirms an existing draft when generation is absent", async () => {
    vi.mocked(api.ready).mockResolvedValue(readiness("fixture", "absent"));
    vi.spyOn(api, "getResumeDraft").mockResolvedValue(draft);
    const accept = vi.spyOn(api, "acceptResumeDraft").mockResolvedValue({ ...draft, status: "accepted", revision: 8 });
    window.history.replaceState({}, "", resumeDraftPath(draft.id));
    await render(<App />);
    expect(button(/确认这版草稿/).disabled).toBe(false);
    await click(button(/确认这版草稿/));
    expect(accept).toHaveBeenCalledWith(draft.id, 7);
    expect(button(/打印简历/).disabled).toBe(false);
  });

  it("does not offer an executable retry for failed generation without the capability", async () => {
    vi.mocked(api.ready).mockResolvedValue(readiness("live", "absent"));
    vi.spyOn(api, "getResumeDraft").mockResolvedValue({ ...draft, status: "generation_failed", active_operation_id: "resume-failure" });
    vi.spyOn(api, "getOperation").mockResolvedValue({ ...operation("resume-failure", true), kind: "resume.compose", resource_type: "resume_draft", resource_id: draft.id });
    const retry = vi.spyOn(api, "retryOperation");
    window.history.replaceState({}, "", resumeDraftPath(draft.id));
    await render(<App />);
    const action = button(/重试简历生成/);
    expect(action.disabled).toBe(true);
    await click(action);
    expect(retry).not.toHaveBeenCalled();
  });
});

describe("automatic content retry recovery", () => {
  const draft: ResumeDraftView = {
    id: "retry-draft", revision: 1, profile_id: "profile", profile_snapshot_id: "snapshot",
    interview_id: null, status: "generation_failed", sections: [], source_claims: [],
    source_claim_ids: [], changes: [], missing_facts: [], cautions: [],
    target_context: { kind: "generic" }, active_operation_id: "parent", run_metadata: {},
  };
  const parent: OperationView = {
    ...operation("parent", false), kind: "resume.compose", resource_type: "resume_draft",
    resource_id: draft.id, next_operation_id: "automatic", attempt_limit: 3,
  };
  const automatic: OperationView = {
    ...parent, id: "automatic", parent_operation_id: "parent", retry_trigger: "automatic", retry_reason: "transient",
    next_operation_id: null, status: "queued", error: null, attempts: 1,
  };

  it("follows a successor across SSE/poll races and ignores a late parent after child success", async () => {
    vi.useFakeTimers();
    const lateParent = Promise.withResolvers<OperationView>();
    let child: OperationView = { ...automatic, status: "running", attempts: 2 };
    const get = vi.spyOn(api, "getOperation")
      .mockImplementation(async (id) => id === "parent" ? parent : child);
    get.mockImplementationOnce(() => lateParent.promise);
    const terminal = vi.fn();
    const retry = vi.spyOn(api, "retryOperation");
    function Monitor() {
      const { operation: observed } = useOperationMonitor("parent", terminal);
      return <output>{observed?.id}:{observed?.status}</output>;
    }
    await render(<Monitor />);
    await act(async () => { vi.advanceTimersByTime(800); });
    expect(host.textContent).toBe("automatic:running");
    expect(eventSources[0].close).toHaveBeenCalled();
    expect(get.mock.calls[0][1]?.aborted).toBe(true);
    expect(terminal).not.toHaveBeenCalled();

    child = { ...child, status: "succeeded", last_event_seq: 3 };
    await act(async () => { eventSources[1].dispatchEvent(new Event("operation.completed")); });
    expect(host.textContent).toBe("automatic:succeeded");
    expect(terminal).toHaveBeenCalledTimes(1);
    expect(terminal.mock.calls[0][0].id).toBe("automatic");
    await act(async () => { lateParent.resolve({ ...parent, next_operation_id: null }); });
    await act(async () => { vi.advanceTimersByTime(2400); });
    expect(host.textContent).toBe("automatic:succeeded");
    expect(terminal).toHaveBeenCalledTimes(1);
    expect(retry).not.toHaveBeenCalled();
  });

  it.each([true, false])("only permits manual retry when the failed child has budget (%s)", async (retryable) => {
    let child = automatic;
    const getDraft = vi.spyOn(api, "getResumeDraft").mockResolvedValue(draft);
    vi.spyOn(api, "getOperation").mockImplementation(async (id) => id === "parent" ? parent : child);
    const retry = vi.spyOn(api, "retryOperation");
    const create = vi.spyOn(api, "createResumeDraft");
    await render(<ResumeDraftPage draftId={draft.id} serviceReady contentGenerationReady navigate={vi.fn()} />);
    expect(loadOperationId("resume", draft.id)).toBe("automatic");
    expect(host.textContent).toContain("自动重试");
    expect(host.textContent).toContain("已尝试 1 次");
    expect(host.textContent).not.toContain("failure-parent");
    expect([...host.querySelectorAll("button")].some((item) => /重试简历生成/.test(item.textContent ?? ""))).toBe(false);

    child = { ...automatic, status: "running", attempts: 2, last_event_seq: 3 };
    await act(async () => { eventSources.at(-1)!.dispatchEvent(new Event("operation.started")); });
    expect(host.textContent).toContain("已尝试 2 次");
    getDraft.mockResolvedValue({ ...draft, revision: 3, active_operation_id: "automatic" });
    child = {
      ...child, status: "failed", last_event_seq: 4,
      error: { code: "MODEL_REQUEST_FAILED", message: "child-failure", retryable },
    };
    await act(async () => { eventSources.at(-1)!.dispatchEvent(new Event("operation.failed")); });
    expect(host.textContent).toContain("child-failure");
    expect([...host.querySelectorAll("button")].some((item) => /重试简历生成/.test(item.textContent ?? ""))).toBe(retryable);
    expect(retry).not.toHaveBeenCalled();
    expect(create).not.toHaveBeenCalled();
    if (retryable) {
      retry.mockReturnValue(Promise.withResolvers<OperationAccepted>().promise);
      await click(button(/重试简历生成/));
      expect(retry).toHaveBeenCalledWith("automatic", 3, expect.any(String));
    }
  });

  it("restores the server child rather than a locally cached failed parent", async () => {
    saveOperationId("resume", draft.id, "parent");
    vi.spyOn(api, "getResumeDraft").mockResolvedValue({
      ...draft, status: "generating", revision: 2, active_operation_id: "automatic",
    });
    const get = vi.spyOn(api, "getOperation").mockResolvedValue({ ...automatic, status: "running", attempts: 2 });
    await render(<ResumeDraftPage draftId={draft.id} serviceReady contentGenerationReady navigate={vi.fn()} />);
    expect(get.mock.calls.map(([id]) => id)).toEqual(["automatic"]);
    expect(loadOperationId("resume", draft.id)).toBe("automatic");
    expect(host.textContent).toContain("自动重试");
    expect(host.textContent).not.toContain("failure-parent");
  });

  it("does not let a previous draft's late manual acceptance replace the current child watch", async () => {
    const accepted = Promise.withResolvers<OperationAccepted>();
    const getDraft = vi.spyOn(api, "getResumeDraft").mockResolvedValue(draft);
    const get = vi.spyOn(api, "getOperation").mockResolvedValue({
      ...parent, next_operation_id: null,
      error: { code: "MODEL_REQUEST_FAILED", message: "retryable-parent", retryable: true },
    });
    vi.spyOn(api, "retryOperation").mockReturnValue(accepted.promise);
    await render(<ResumeDraftPage draftId={draft.id} serviceReady contentGenerationReady navigate={vi.fn()} />);
    await click(button(/重试简历生成/));
    const other: ResumeDraftView = {
      ...draft, id: "other-draft", status: "generating", active_operation_id: "other-child",
    };
    getDraft.mockResolvedValue(other);
    get.mockResolvedValue({ ...automatic, id: "other-child", resource_id: other.id, status: "running", attempts: 2 });
    await render(<ResumeDraftPage draftId={other.id} serviceReady contentGenerationReady navigate={vi.fn()} />);
    const currentSource = eventSources.at(-1)!;
    await act(async () => accepted.resolve({
      operation_id: "old-manual", resource_type: "resume_draft", resource_id: draft.id,
      status: "queued", events_url: "",
    }));
    expect(currentSource.close).not.toHaveBeenCalled();
    expect(loadOperationId("resume", other.id)).toBe("other-child");
    expect(get.mock.calls.at(-1)![0]).toBe("other-child");
    expect(host.textContent).toContain("自动重试");
    expect(host.textContent).not.toContain("retryable-parent");
  });

  it("does not apply an old terminal resource response after navigating to another draft", async () => {
    const lateDraft = Promise.withResolvers<ResumeDraftView>();
    const getDraft = vi.spyOn(api, "getResumeDraft")
      .mockResolvedValueOnce(draft)
      .mockImplementationOnce(() => lateDraft.promise);
    vi.spyOn(api, "getOperation").mockResolvedValue({ ...parent, next_operation_id: null });
    await render(<ResumeDraftPage draftId={draft.id} serviceReady contentGenerationReady navigate={vi.fn()} />);
    const other = { ...draft, id: "other-draft", revision: 7, status: "accepted" as const, active_operation_id: null };
    getDraft.mockResolvedValue(other);
    await render(<ResumeDraftPage draftId={other.id} serviceReady contentGenerationReady navigate={vi.fn()} />);
    expect(button(/打印简历/).disabled).toBe(false);
    await act(async () => { lateDraft.resolve({ ...draft, revision: 3, active_operation_id: "parent" }); });
    expect(button(/打印简历/).disabled).toBe(false);
    expect(host.textContent).not.toContain("failure-parent");
    expect(getDraft.mock.calls[1][1]?.aborted).toBe(true);
  });
});

describe("operation waiting facts", () => {
  it.each([1, 2, 3])("shows root-chain elapsed time and configured attempt limit %s without posting from timers", async (limit) => {
    vi.useFakeTimers();
    vi.setSystemTime(new Date("2026-10-03T00:02:05Z"));
    const retry = vi.spyOn(api, "retryOperation");
    const submit = vi.spyOn(api, "submitAnswer");
    const queued: OperationView = {
      ...operation("child", false), kind: "interview.answer", status: "queued",
      parent_operation_id: "root", retry_trigger: "automatic", retry_reason: "transient",
      attempts: limit - 1, attempt_limit: limit, error: null,
      created_at: "2026-10-03T00:02:00Z", chain_started_at: "2026-10-03T00:00:00Z",
    };
    await render(<OperationStatus operation={queued} label="回答分析" />);
    expect(host.textContent).toContain("已等待 2 分 5 秒");
    expect(host.textContent).toContain(`已尝试 ${limit - 1} 次，最多 ${limit} 次`);
    expect(host.textContent).toContain("尚未开始模型调用");
    expect(host.textContent).toContain("暂时性网络或服务故障");
    expect(host.textContent).not.toContain("自动修正输出");
    await act(async () => { vi.advanceTimersByTime(2000); });
    expect(host.textContent).toContain("已等待 2 分 7 秒");
    await render(<OperationStatus operation={{ ...queued, status: "running", attempts: limit }} label="回答分析" />);
    expect(host.textContent).toContain(`已尝试 ${limit} 次，最多 ${limit} 次`);
    expect(host.textContent).not.toContain("尚未开始模型调用");
    expect(host.textContent).toContain("已等待 2 分 7 秒");
    expect(retry).not.toHaveBeenCalled();
    expect(submit).not.toHaveBeenCalled();
  });

  it("distinguishes correction from transport retry and retains the original terminal error", async () => {
    const correcting: OperationView = {
      ...operation("correction", false), kind: "resume.compose", status: "running",
      retry_trigger: "automatic", retry_reason: "correction", attempt_limit: 2, error: null,
    };
    await render(<OperationStatus operation={correcting} label="简历生成" />);
    expect(host.textContent).toContain("正在自动修正输出");
    expect(host.textContent).toContain("上次输出未通过校验");
    expect(host.textContent).not.toContain("暂时性网络或服务故障");
    await render(<OperationStatus operation={{
      ...correcting, id: "original", status: "failed", retry_trigger: null, retry_reason: null,
      error: { code: "MODEL_OUTPUT_INVALID", message: "Original validation detail", retryable: false },
    }} label="简历生成" />);
    expect(host.textContent).toContain("Original validation detail");
    expect(host.textContent).not.toContain("正在自动");
    await render(<OperationStatus operation={operation("non-model", false)} label="知识包导入" />);
    expect(host.textContent).not.toContain("已尝试");
  });
});
