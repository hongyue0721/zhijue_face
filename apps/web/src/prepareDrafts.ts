import type { JDSections } from "./jdSections";
import { clearTemporaryDraft, loadTemporaryDraft, saveTemporaryDraft } from "./temporaryDrafts";

export interface PrepareDraft {
  jobName: string;
  sections: JDSections;
  unassigned: string[];
}

// Heap navigation recovery is always available; browser recovery is explicit opt-in.

export function prepareDraftKey(profileId: string, interviewId: string | null): string {
  return JSON.stringify([profileId, interviewId]);
}

export function loadPrepareDraft(key: string): PrepareDraft | undefined {
  const value = loadTemporaryDraft(`jd:${key}`) as PrepareDraft | undefined;
  return value && typeof value.jobName === "string"
    && value.sections && ["required", "preferred", "responsibilities"].every(
      (field) => typeof value.sections[field as keyof JDSections] === "string",
    ) && Array.isArray(value.unassigned) && value.unassigned.every((line) => typeof line === "string")
    ? value : undefined;
}

export function savePrepareDraft(key: string, draft: PrepareDraft): boolean {
  const [profileId] = JSON.parse(key) as [string, string | null];
  return saveTemporaryDraft(`jd:${key}`, profileId, draft);
}

export function clearPrepareDraft(key: string): boolean {
  return clearTemporaryDraft(`jd:${key}`);
}
