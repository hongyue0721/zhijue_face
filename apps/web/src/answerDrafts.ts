import { clearTemporaryDraft, loadTemporaryDraft, saveTemporaryDraft, temporaryDraftKeys } from "./temporaryDrafts";

export type PendingSubmission = {
  questionId: string;
  expectedRevision: number;
  clientTurnId: string;
  idempotencyKey: string;
  answerText: string;
  retryReason: "network" | "capacity" | "service" | null;
};
export type AnswerDraft = { text: string; pending: PendingSubmission | null };

export function answerDraftKey(interviewId: string, questionId: string): string {
  return `answer:${JSON.stringify([interviewId, questionId])}`;
}

export function loadAnswerDraft(interviewId: string, questionId: string): AnswerDraft | undefined {
  const draft = loadTemporaryDraft(answerDraftKey(interviewId, questionId)) as AnswerDraft | undefined;
  if (!draft || typeof draft.text !== "string") return undefined;
  const pending = draft.pending;
  if (pending && (pending.questionId !== questionId || pending.answerText !== draft.text
    || typeof pending.clientTurnId !== "string" || typeof pending.idempotencyKey !== "string"
    || !Number.isInteger(pending.expectedRevision)
    || ![null, "network", "capacity", "service"].includes(pending.retryReason))) return undefined;
  return { text: draft.text, pending: pending ?? null };
}

export function saveAnswerDraft(profileId: string, interviewId: string, questionId: string, draft: AnswerDraft): boolean {
  return saveTemporaryDraft(answerDraftKey(interviewId, questionId), profileId, draft);
}

export function ownsPendingAnswerDraft(interviewId: string, command: PendingSubmission): boolean {
  const draft = loadAnswerDraft(interviewId, command.questionId);
  const pending = draft?.pending;
  return draft?.text === command.answerText && pending !== null && pending !== undefined
    && pending.questionId === command.questionId
    && pending.expectedRevision === command.expectedRevision
    && pending.clientTurnId === command.clientTurnId
    && pending.idempotencyKey === command.idempotencyKey
    && pending.answerText === command.answerText;
}

// Compare and mutate synchronously: a late request must not reclaim an edited/reset draft.
// null means ownership was lost, not a browser-storage failure.
export function resolvePendingAnswerDraft(
  profileId: string, interviewId: string, command: PendingSubmission, draft: AnswerDraft | null,
): boolean | null {
  if (!ownsPendingAnswerDraft(interviewId, command)) return null;
  return draft === null
    ? clearTemporaryDraft(answerDraftKey(interviewId, command.questionId))
    : saveAnswerDraft(profileId, interviewId, command.questionId, draft);
}

// Only the authoritative current question can retain an unsubmitted answer.
export function reconcileAnswerDrafts(interviewId: string, currentQuestionId: string | null): boolean {
  let cleared = true;
  for (const key of temporaryDraftKeys()) {
    if (!key.startsWith("answer:")) continue;
    try {
      const [owner, question] = JSON.parse(key.slice("answer:".length)) as [string, string];
      if (owner === interviewId && question !== currentQuestionId) cleared = clearTemporaryDraft(key) && cleared;
    } catch { /* Ignore keys not created by this feature. */ }
  }
  return cleared;
}
