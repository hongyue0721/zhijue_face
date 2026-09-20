import { useCallback, useEffect, useState } from "react";
import { api, newCommandKey, type DocumentView, type OperationView, type ProfileView } from "../api";
import { ClaimConfirmList } from "../components/profile/ClaimConfirmList";
import { DocumentStatus } from "../components/profile/DocumentStatus";
import { DocumentUpload } from "../components/profile/DocumentUpload";
import { ManualFactForm } from "../components/profile/ManualFactForm";
import { ProfileReadyCard } from "../components/profile/ProfileReadyCard";
import { ErrorNotice } from "../components/common/ErrorNotice";
import { useOperationMonitor } from "../hooks/useOperationMonitor";
import { clearOperationId, loadOperationId, saveOperationId } from "../storage";
import { preparePath, startPath } from "../routing";

function profileNameFor(file: File): string {
  const stem = file.name.replace(/\.pdf$/i, "").trim();
  return stem || "候选人资料";
}

function resumeDocument(profile: ProfileView): DocumentView | null {
  return profile.documents.find((document) => document.kind === "resume") ?? null;
}

export function StartPage({
  profileId,
  serviceReady,
  navigate,
}: {
  profileId: string | null;
  serviceReady: boolean;
  navigate: (path: string, replace?: boolean) => void;
}) {
  const [profile, setProfile] = useState<ProfileView | null>(null);
  const [document, setDocument] = useState<DocumentView | null>(null);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [operationId, setOperationId] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [factBusy, setFactBusy] = useState(false);
  const [busyClaimId, setBusyClaimId] = useState<string | null>(null);
  const [error, setError] = useState<unknown>(null);

  const applyProfile = useCallback((next: ProfileView) => {
    setProfile(next);
    const resume = resumeDocument(next);
    setDocument(resume);
    if (resume) setSelectedName(resume.filename_display);
  }, []);

  const reloadProfile = useCallback(async (id = profileId) => {
    if (!id) return;
    applyProfile(await api.getProfile(id));
  }, [applyProfile, profileId]);

  useEffect(() => {
    if (!profileId) {
      setProfile(null);
      setDocument(null);
      setOperationId(null);
      return;
    }
    const controller = new AbortController();
    setError(null);
    api.getProfile(profileId, controller.signal)
      .then(applyProfile)
      .catch((nextError) => {
        if (!(nextError instanceof DOMException && nextError.name === "AbortError")) setError(nextError);
      });
    setOperationId(loadOperationId("profile", profileId));
    return () => controller.abort();
  }, [applyProfile, profileId]);

  const operationSettled = useCallback(async (settled: OperationView) => {
    const id = profile?.id ?? profileId;
    setSubmitting(false);
    setBusyClaimId(null);
    if (!id) return;
    try {
      if (settled.status === "succeeded") {
        const documentId = settled.result?.document_id;
        if (typeof documentId === "string") setDocument(await api.getDocument(documentId));
        await reloadProfile(id);
        clearOperationId("profile", id);
        setOperationId(null);
      } else {
        await reloadProfile(id);
      }
    } catch (nextError) {
      setError(nextError);
    }
  }, [profile?.id, profileId, reloadProfile]);

  const { operation, error: operationError } = useOperationMonitor(operationId, operationSettled);
  const operationActive = operation?.status === "queued" || operation?.status === "running";
  const commandBusy = submitting || operationActive;

  const upload = async (file: File) => {
    setError(null);
    setSelectedName(file.name);
    setSubmitting(true);
    try {
      const current = profile ?? await api.createProfile(profileNameFor(file), false);
      applyProfile(current);
      if (!profileId) navigate(startPath(current.id), true);
      const accepted = await api.uploadDocument(
        current.id,
        current.revision,
        file,
        newCommandKey("document"),
      );
      saveOperationId("profile", current.id, accepted.operation_id);
      setOperationId(accepted.operation_id);
    } catch (nextError) {
      setSubmitting(false);
      setError(nextError);
    }
  };

  const addFact = async (text: string): Promise<boolean> => {
    if (!profile) return false;
    setFactBusy(true);
    setError(null);
    try {
      applyProfile(await api.addFacts(profile.id, profile.revision, [text]));
      return true;
    } catch (nextError) {
      setError(nextError);
      return false;
    } finally {
      setFactBusy(false);
    }
  };

  const confirmClaim = async (claimId: string, action: "accept" | "reject") => {
    if (!profile) return;
    setBusyClaimId(claimId);
    setSubmitting(true);
    setError(null);
    try {
      const accepted = await api.confirm(
        profile.id,
        profile.revision,
        [{ claim_id: claimId, action }],
        newCommandKey("confirm"),
      );
      saveOperationId("profile", profile.id, accepted.operation_id);
      setOperationId(accepted.operation_id);
    } catch (nextError) {
      setSubmitting(false);
      setBusyClaimId(null);
      setError(nextError);
    }
  };

  return (
    <main className={`page-container start-page ${profile ? "start-page--progress" : "start-page--initial"}`}>
      <div className={`page-intro ${profile ? "" : "centered-intro"}`}>
        <p className="eyebrow">资料导入</p>
        <h1>准备你的面试资料</h1>
        <p>上传简历，让系统建立本场面试使用的候选人资料。</p>
      </div>
      <ErrorNotice error={error ?? operationError} onReload={profileId ? () => void reloadProfile() : undefined} />
      {!document && !operationActive ? (
        <DocumentUpload disabled={!serviceReady} busy={submitting} onSelect={upload} />
      ) : null}
      <DocumentStatus selectedName={selectedName} operation={operation} document={document} />
      {profile && !commandBusy ? (
        <ClaimConfirmList
          claims={profile.proposed_claims}
          busyClaimId={busyClaimId}
          disabled={!serviceReady}
          onDecision={confirmClaim}
        />
      ) : null}
      {profile && profile.proposed_claims.length === 0 && !commandBusy ? (
        <ManualFactForm disabled={!serviceReady} busy={factBusy} onSubmit={addFact} />
      ) : null}
      {profile ? (
        <ProfileReadyCard
          profile={profile}
          disabled={!serviceReady || commandBusy}
          onContinue={() => navigate(preparePath(profile.id))}
        />
      ) : null}
    </main>
  );
}
