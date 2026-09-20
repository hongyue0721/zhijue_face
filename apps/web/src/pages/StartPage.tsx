import { Button, Tag } from "@any-design/anyui/react";
import { useCallback, useEffect, useState } from "react";
import { api, newCommandKey, type DocumentView, type OperationView, type ProfileView } from "../api";
import { ClaimConfirmList } from "../components/profile/ClaimConfirmList";
import { DocumentStatus } from "../components/profile/DocumentStatus";
import { DocumentUpload } from "../components/profile/DocumentUpload";
import { ManualFactForm } from "../components/profile/ManualFactForm";
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
  const [claimPage, setClaimPage] = useState(0);
  const [manualFactVisible, setManualFactVisible] = useState(false);

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
  const claimPageSize = 5;
  const pendingClaimCount = profile?.proposed_claims.length ?? 0;
  const claimPageCount = Math.max(1, Math.ceil(pendingClaimCount / claimPageSize));
  const visibleClaimPage = Math.min(claimPage, claimPageCount - 1);
  const visibleClaims = profile?.proposed_claims.slice(
    visibleClaimPage * claimPageSize,
    (visibleClaimPage + 1) * claimPageSize,
  ) ?? [];

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
      {profile ? (
        <header className="compact-page-heading start-ready-heading">
          <div>
            <p className="eyebrow">资料导入</p>
            <h1>核对本场面试资料</h1>
            <p>
              已确认 {profile.confirmed_claims.length} 条
              {" · "}待确认 {profile.proposed_claims.length} 条
              {" · "}材料 {profile.documents.length} 份
            </p>
          </div>
          <div className="heading-actions">
            <Tag>{profile.latest_snapshot_id ? "资料快照已更新" : "等待资料确认"}</Tag>
            <Button
              type="primary"
              size="large"
              disabled={!serviceReady || commandBusy || !profile.latest_snapshot_id}
              onClick={() => navigate(preparePath(profile.id))}
            >
              进入面试准备
            </Button>
          </div>
        </header>
      ) : (
        <div className="page-intro centered-intro">
          <p className="eyebrow">资料导入</p>
          <h1>准备你的面试资料</h1>
          <p>上传简历，让系统建立本场面试使用的候选人资料。</p>
        </div>
      )}
      <ErrorNotice
        error={error ?? operationError}
        onReload={profileId ? () => void reloadProfile() : undefined}
      />
      {!profile ? (
        <>
          <DocumentUpload disabled={!serviceReady} busy={submitting} onSelect={upload} />
          <DocumentStatus selectedName={selectedName} operation={operation} document={document} />
        </>
      ) : (
        <section className="start-workspace" aria-label="资料核对工作区">
          <div className="start-material-column">
            {!document && !operationActive ? (
              <DocumentUpload disabled={!serviceReady} busy={submitting} onSelect={upload} />
            ) : null}
            <DocumentStatus selectedName={selectedName} operation={operation} document={document} />
            <Button
              type="secondary"
              onClick={() => setManualFactVisible((current) => !current)}
            >
              {manualFactVisible ? "收起补充经历" : "补充经历"}
            </Button>
            {manualFactVisible ? (
              <ManualFactForm
                disabled={!serviceReady || commandBusy}
                busy={factBusy}
                onSubmit={addFact}
              />
            ) : null}
          </div>

          <div className="start-claims-column">
            {profile.proposed_claims.length ? (
              <>
                <ClaimConfirmList
                  claims={visibleClaims}
                  totalCount={profile.proposed_claims.length}
                  busyClaimId={busyClaimId}
                  disabled={!serviceReady || commandBusy}
                  onDecision={confirmClaim}
                />
                {claimPageCount > 1 ? (
                  <nav className="claim-pagination" aria-label="待确认资料分页">
                    <Button
                      type="secondary"
                      size="small"
                      disabled={visibleClaimPage === 0 || commandBusy}
                      onClick={() => setClaimPage((current) => Math.max(0, current - 1))}
                    >
                      上一页
                    </Button>
                    <span>第 {visibleClaimPage + 1} / {claimPageCount} 页</span>
                    <Button
                      type="secondary"
                      size="small"
                      disabled={visibleClaimPage >= claimPageCount - 1 || commandBusy}
                      onClick={() => setClaimPage((current) => current + 1)}
                    >
                      下一页
                    </Button>
                  </nav>
                ) : null}
              </>
            ) : (
              <section className="surface-card claims-empty-state">
                <p className="eyebrow">资料确认</p>
                <h2>没有待确认信息</h2>
                <p>当前没有新的候选事实；可继续使用已确认资料，或手工补充经历。</p>
                <Button type="secondary" onClick={() => setManualFactVisible(true)}>
                  手工补充经历
                </Button>
              </section>
            )}
          </div>
        </section>
      )}
    </main>
  );
}
