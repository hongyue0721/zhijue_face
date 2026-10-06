// @vitest-environment happy-dom
// Dynamic imports intentionally exercise fresh module heaps across browser-refresh boundaries.
import { beforeEach, afterEach, describe, expect, it, vi } from "vitest";

beforeEach(() => { sessionStorage.clear(); localStorage.clear(); vi.resetModules(); });
afterEach(() => { vi.restoreAllMocks(); });

describe("explicit tab-session draft recovery", () => {
  it("keeps private text out of browser storage by default and restores it only after opt-in", async () => {
    const drafts = await import("../src/prepareDrafts");
    const storage = await import("../src/temporaryDrafts");
    const key = drafts.prepareDraftKey("profile", null);
    const body = { jobName: "Private role", sections: { required: "Private requirement", preferred: "", responsibilities: "" }, unassigned: [] };
    drafts.savePrepareDraft(key, body);
    expect(sessionStorage.length).toBe(0);
    expect(drafts.loadPrepareDraft(key)).toEqual(body);
    expect(storage.setTemporaryDraftsEnabled(true)).toBe(true);
    vi.resetModules(); // A new module heap simulates a real refresh, not just a component remount.
    const refreshed = await import("../src/prepareDrafts");
    expect(refreshed.loadPrepareDraft(key)).toEqual(body);
    expect(refreshed.loadPrepareDraft(refreshed.prepareDraftKey("other", null))).toBeUndefined();
    expect(refreshed.loadPrepareDraft(refreshed.prepareDraftKey("profile", "other-plan"))).toBeUndefined();
    expect(localStorage.length).toBe(0);
  });

  it("restores pending answer body and command IDs together, and rejects mismatched bodies", async () => {
    const storage = await import("../src/temporaryDrafts");
    const drafts = await import("../src/answerDrafts");
    storage.setTemporaryDraftsEnabled(true);
    const pending = { questionId: "q", expectedRevision: 4, clientTurnId: "turn", idempotencyKey: "answer", answerText: "Exact body", retryReason: null };
    drafts.saveAnswerDraft("profile", "interview", "q", { text: pending.answerText, pending });
    vi.resetModules();
    const refreshed = await import("../src/answerDrafts");
    expect(refreshed.loadAnswerDraft("interview", "q")).toEqual({ text: pending.answerText, pending });
    expect(refreshed.loadAnswerDraft("other", "q")).toBeUndefined();
    refreshed.saveAnswerDraft("profile", "interview", "q", { text: "Changed body", pending });
    expect(refreshed.loadAnswerDraft("interview", "q")).toBeUndefined();
  });

  it("clears only the matching interview on advance/end and only the deleted profile", async () => {
    const storage = await import("../src/temporaryDrafts");
    const drafts = await import("../src/answerDrafts");
    storage.setTemporaryDraftsEnabled(true);
    drafts.saveAnswerDraft("profile", "interview", "old", { text: "old", pending: null });
    drafts.saveAnswerDraft("profile", "interview", "new", { text: "new", pending: null });
    drafts.saveAnswerDraft("other", "other-interview", "q", { text: "other", pending: null });
    drafts.reconcileAnswerDrafts("interview", "new");
    expect(drafts.loadAnswerDraft("interview", "old")).toBeUndefined();
    expect(drafts.loadAnswerDraft("interview", "new")?.text).toBe("new");
    drafts.reconcileAnswerDrafts("interview", null);
    expect(drafts.loadAnswerDraft("interview", "new")).toBeUndefined();
    storage.saveTemporaryDraft("plan:profile", "profile", { key: "same-key", body: "private" });
    expect(storage.clearProfileTemporaryDrafts("profile")).toBe(true);
    expect(storage.loadTemporaryDraft("plan:profile")).toBeUndefined();
    expect(drafts.loadAnswerDraft("other-interview", "q")?.text).toBe("other");
    vi.resetModules();
    expect((await import("../src/temporaryDrafts")).loadTemporaryDraft("plan:profile")).toBeUndefined();
  });

  it("reports denied storage and retains in-memory text without claiming refresh recovery", async () => {
    const storage = await import("../src/temporaryDrafts");
    vi.spyOn(window, "sessionStorage", "get").mockImplementation(() => { throw new DOMException("Denied", "SecurityError"); });
    expect(storage.setTemporaryDraftsEnabled(true)).toBe(false);
    expect(storage.saveTemporaryDraft("jd:key", "profile", "private")).toBe(false);
    expect(storage.loadTemporaryDraft("jd:key")).toBe("private");
    expect(localStorage.length).toBe(0);
  });

  it("withdraws consent without losing in-app text, and never persists volatile plan attempts", async () => {
    const storage = await import("../src/temporaryDrafts");
    storage.saveTemporaryDraft("attempt", "profile", "already submitted", false);
    storage.saveTemporaryDraft("draft", "profile", "unsubmitted");
    storage.setTemporaryDraftsEnabled(true);
    expect(sessionStorage.getItem("zhijue:temporary-draft:attempt")).toBeNull();
    expect(storage.setTemporaryDraftsEnabled(false)).toBe(true);
    expect(sessionStorage.length).toBe(0);
    expect(storage.loadTemporaryDraft("draft")).toBe("unsubmitted");
    vi.resetModules();
    expect((await import("../src/temporaryDrafts")).loadTemporaryDraft("draft")).toBeUndefined();
  });
});
