import { Alert, Button } from "@any-design/anyui/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, newCommandKey, shouldPreserveWriteCommand, type OperationAccepted, type OperationView, type ProfileView } from "../api";
import { ClaimConfirmList } from "../components/profile/ClaimConfirmList";
import { calculateDecisionUpdate, type ClaimDecision } from "../components/profile/claimDecisions";
import { DocumentStatus } from "../components/profile/DocumentStatus";
import { DocumentUpload } from "../components/profile/DocumentUpload";
import { ResumeScan } from "../components/profile/ResumeScan";
import { FactModal } from "../components/profile/FactModal";
import { UploadModal } from "../components/profile/UploadModal";
import { ErrorNotice } from "../components/common/ErrorNotice";
import { useOperationMonitor } from "../hooks/useOperationMonitor";
import { clearOperationId, clearRecoverableCommand, loadOperationId, loadRecoverableCommand, saveOperationId, saveRecoverableCommand, type RecoverableCommand } from "../storage";
import { preparePath, resumeDraftPath, startPath } from "../routing";

type ProfileCommand = {
  profileId: string;
  revision: number;
  key: string;
} & (
  | { kind: "upload"; file: File }
  | { kind: "confirm"; decisions: ClaimDecision[] }
  | { kind: "activate" }
  | { kind: "retry"; operationId: string }
  | { kind: "delete" }
);
type ResumeCommand = Extract<RecoverableCommand, { kind: "profile-resume" }>;

function profileOperationToMonitor(profile: ProfileView): string | null {
  if (profile.active_operation_id) return profile.active_operation_id;
  const activation = profile.snapshot_activation;
  return activation && activation.status !== "ready" ? activation.operation_id : null;
}

export function StartPage({ profileId, serviceReady, navigate }: {
  profileId: string | null;
  serviceReady: boolean;
  navigate: (path: string, replace?: boolean) => void;
}) {
  const [profile, setProfile] = useState<ProfileView | null>(null);
  const [selectedName, setSelectedName] = useState<string | null>(null);
  const [operationId, setOperationId] = useState<string | null>(null);
  const [resumeOperationId, setResumeOperationId] = useState<string | null>(null);
  const [uploadRequestActive, setUploadRequestActive] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [factBusy, setFactBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [pendingCommand, setPendingCommand] = useState<ProfileCommand | null>(null);
  const [pendingResume, setPendingResume] = useState<ResumeCommand | null>(null);
  const [decisions, setDecisions] = useState<Record<string, ClaimDecision>>({});
  const [selectionError, setSelectionError] = useState<string | null>(null);
  const [list, setList] = useState<"proposed" | "confirmed">("proposed");
  const [manualFactVisible, setManualFactVisible] = useState(false);
  const [uploadVisible, setUploadVisible] = useState(false);
  const [confirmSuccessFlash, setConfirmSuccessFlash] = useState(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const requestInFlight = useRef(false);
  const manualFactTriggerRef = useRef<HTMLDivElement>(null);
  const uploadTriggerRef = useRef<HTMLDivElement>(null);
  const confirmSuccessTimerRef = useRef<number | null>(null);
  const previousProfileId = useRef(profileId);

  const applyProfile = useCallback((next: ProfileView) => {
    setProfile(next);
    setDecisions((current) => {
      const ids = new Set([...next.proposed_claims, ...next.confirmed_claims].map((claim) => claim.id));
      return Object.fromEntries(Object.entries(current).filter(([id]) => ids.has(id)));
    });
  }, []);

  const reloadProfile = useCallback(async () => {
    const id = profile?.id ?? profileId;
    if (!id) return;
    try {
      const next = await api.getProfile(id);
      applyProfile(next);
      const authoritativeOperationId = profileOperationToMonitor(next);
      if (authoritativeOperationId) {
        saveOperationId("profile", id, authoritativeOperationId);
      } else {
        clearOperationId("profile", id);
      }
      setOperationId(authoritativeOperationId);
      setError(null);
    } catch (nextError) {
      setError(nextError);
    }
  }, [applyProfile, profile?.id, profileId]);

  useEffect(() => {
    setUploadVisible(false);
    if (previousProfileId.current && previousProfileId.current !== profileId) {
      setProfile(null);
      setPendingCommand(null);
      setDecisions({});
      setSelectedName(null);
      setError(null);
      setList("proposed");
    }
    previousProfileId.current = profileId;
    if (!profileId) {
      setProfile(null);
      setOperationId(null);
      setResumeOperationId(null);
      setPendingCommand(null);
      setPendingResume(null);
      setDecisions({});
      setSelectedName(null);
      return;
    }
    const controller = new AbortController();
    api.getProfile(profileId, controller.signal).then((next) => {
      applyProfile(next);
      const authoritativeOperationId = profileOperationToMonitor(next);
      if (authoritativeOperationId) {
        saveOperationId("profile", profileId, authoritativeOperationId);
      } else {
        clearOperationId("profile", profileId);
      }
      setOperationId(authoritativeOperationId);
    }).catch((nextError) => {
      if (!(nextError instanceof DOMException && nextError.name === "AbortError")) setError(nextError);
    });
    const command = loadRecoverableCommand("profile-resume", profileId);
    setPendingResume(command?.kind === "profile-resume" ? command : null);
    setResumeOperationId(loadOperationId("resume", profileId));

    return () => controller.abort();
  }, [applyProfile, profileId]);
  useEffect(() => {
    setConfirmSuccessFlash(false);
    return () => {
      if (confirmSuccessTimerRef.current !== null) {
        window.clearTimeout(confirmSuccessTimerRef.current);
      }
    };
  }, [profileId]);

  const operationSettled = useCallback(async (settled: OperationView) => {
    const id = profile?.id ?? profileId;
    if (!id) return;
    if (settled.kind === "profile.delete") {
      // 档案行已物理删除，GET /profiles 必然 404：成功即回到无档案入口；
      // 失败则重读 deleting 状态并保留失败 Operation，供原操作重试。
      if (settled.status === "succeeded") {
        clearOperationId("profile", id);
        clearOperationId("prepare", id);
        clearOperationId("resume", id);
        clearRecoverableCommand("profile-resume", id);
        navigate("/start", true);
        return;
      }
      try {
        applyProfile(await api.getProfile(id));
      } catch (nextError) {
        setError(nextError);
      }
      return;
    }
    try {
      if (settled.resource_type === "resume_draft") {
        if (settled.status === "succeeded") {
          clearOperationId("profile", id);
          clearOperationId("resume", id);
          clearRecoverableCommand("profile-resume", id);
          navigate(resumeDraftPath(settled.resource_id));
        }
        return;
      }
      applyProfile(await api.getProfile(id));
      if (settled.status === "succeeded") {
        clearOperationId("profile", id);
        setOperationId(null);
        if (settled.kind === "profile.confirm") {
          setConfirmSuccessFlash(true);
          if (confirmSuccessTimerRef.current !== null) {
            window.clearTimeout(confirmSuccessTimerRef.current);
          }
          confirmSuccessTimerRef.current = window.setTimeout(() => {
            setConfirmSuccessFlash(false);
            confirmSuccessTimerRef.current = null;
          }, 2400);
        }
      }
    } catch (nextError) {
      setError(nextError);
    }
  }, [applyProfile, navigate, profile?.id, profileId]);

  const resumeSettled = useCallback(async (settled: OperationView) => {
    const id = profile?.id ?? profileId;
    if (!id) return;
    try {
      if (settled.status === "succeeded" && settled.resource_type === "resume_draft") {
        clearOperationId("resume", id);
        clearRecoverableCommand("profile-resume", id);
        setPendingResume(null);
        navigate(resumeDraftPath(settled.resource_id));
        return;
      }
      applyProfile(await api.getProfile(id));
    } catch (nextError) {
      setError(nextError);
    }
  }, [applyProfile, navigate, profile?.id, profileId]);

  const operationUnavailable = useCallback(() => {
    const id = profile?.id ?? profileId;
    if (id) clearOperationId("profile", id);
    setOperationId(null);
    setProfile((current) => {
      if (!current) return current;
      return {
        ...current,
        active_operation_id: null,
        snapshot_activation: current.snapshot_activation
          ? { ...current.snapshot_activation, operation_id: null }
          : null,
      };
    });
  }, [profile?.id, profileId]);
  const resumeUnavailable = useCallback(() => {
    const id = profile?.id ?? profileId;
    if (id) clearOperationId("resume", id);
    setResumeOperationId(null);
  }, [profile?.id, profileId]);
  const { operation, error: operationError } = useOperationMonitor(
    operationId,
    operationSettled,
    operationUnavailable,
  );
  const { operation: resumeOperation, error: resumeError } = useOperationMonitor(
    resumeOperationId,
    resumeSettled,
    resumeUnavailable,
  );
  const operationActive = operation?.status === "queued" || operation?.status === "running";
  const resumeActive = resumeOperation?.status === "queued" || resumeOperation?.status === "running";
  const operationLoading = Boolean(operationId && !operation && !operationError);
  const resumeLoading = Boolean(resumeOperationId && !resumeOperation && !resumeError);
  const profileOperationActive = Boolean(profile?.active_operation_id)
    && (!operation || operationActive);
  const busy = submitting || factBusy || operationActive || resumeActive
    || operationLoading || resumeLoading || profileOperationActive;
  const mutationDisabled = !serviceReady || busy || Boolean(pendingCommand || pendingResume);
  const activation = profile?.snapshot_activation;
  const confirmedCount = profile?.confirmed_claims.length ?? 0;
  const interviewReady = confirmedCount > 0 && activation?.status === "ready" && activation.snapshot_id === profile?.latest_snapshot_id;
  const selection = Object.values(decisions);
  const invalidCorrection = selection.some((decision) => decision.action === "correct" && !decision.corrected_text?.trim());
  let document: ProfileView["documents"][number] | null = null;
  for (const item of profile?.documents ?? []) {
    if (item.kind === "resume") document = item;
  }
  const documentOperation = operation?.kind === "document.import" ? operation : null;

  const confirmSubmitting = submitting && pendingCommand?.kind === "confirm";
  const confirmOperationActive =
    operation?.kind === "profile.confirm" &&
    (operation.status === "queued" || operation.status === "running");
  const confirmOperationFailed =
    operation?.kind === "profile.confirm" &&
    ["failed", "interrupted", "canceled"].includes(operation.status);
  const confirmRetrySubmitting =
    submitting && pendingCommand?.kind === "retry" && confirmOperationFailed;
  const isProcessingConfirm =
    confirmSubmitting || confirmRetrySubmitting || confirmOperationActive;
  const deleteOperationFailed = operation?.kind === "profile.delete"
    && ["failed", "interrupted"].includes(operation.status);
  const trackAccepted = (accepted: OperationAccepted, id: string) => {
    if (accepted.resource_type === "resume_draft") {
      saveOperationId("resume", id, accepted.operation_id);
      setResumeOperationId(accepted.operation_id);
    } else {
      saveOperationId("profile", id, accepted.operation_id);
      setOperationId(accepted.operation_id);
    }
  };

  // File and corrected text intentionally stay in memory, never browser storage.
  const runProfileCommand = async (command: ProfileCommand) => {
    if (requestInFlight.current) return;
    requestInFlight.current = true;
    setSubmitting(true);
    setError(null);
    setPendingCommand(command);
    try {
      let accepted: OperationAccepted;
      switch (command.kind) {
        case "upload":
          accepted = await api.uploadDocument(command.profileId, command.revision, command.file, command.key);
          setUploadVisible(false);
          break;
        case "confirm":
          accepted = await api.confirm(command.profileId, command.revision, command.decisions, command.key);
          break;
        case "activate":
          accepted = await api.activateProfile(command.profileId, command.revision, command.key);
          break;
        case "retry":
          accepted = await api.retryOperation(command.operationId, command.revision, command.key);
          break;
        case "delete":
          accepted = await api.deleteProfile(command.profileId, command.revision, command.key);
          break;
      }
      setPendingCommand(null);
      if (command.kind === "confirm") {
        // 只清本批提交的 claim；提交期间用户新勾选的不该被误删。
        const submitted = new Set(command.decisions.map((decision) => decision.claim_id));
        setDecisions((current) => Object.fromEntries(Object.entries(current).filter(([id]) => !submitted.has(id))));
      }
      trackAccepted(accepted, command.profileId);
    } catch (nextError) {
      if (!shouldPreserveWriteCommand(nextError)) setPendingCommand(null);
      setError(nextError);
    } finally {
      requestInFlight.current = false;
      setSubmitting(false);
    }
  };

  const upload = async (file: File) => {
    if (mutationDisabled || requestInFlight.current) return;
    setError(null);
    setSelectedName(file.name);
    setUploadRequestActive(true);
    let current = profile;
    if (!current) {
      requestInFlight.current = true;
      setSubmitting(true);
      try {
        current = await api.createProfile(file.name.replace(/\.pdf$/i, "").trim() || "候选人资料", false);
        applyProfile(current);
        navigate(startPath(current.id), true);
      } catch (nextError) {
        setError(nextError);
      } finally {
        requestInFlight.current = false;
        setSubmitting(false);
      }
    }
    if (current) await runProfileCommand({ kind: "upload", profileId: current.id, revision: current.revision, file, key: newCommandKey("document") });
    setUploadRequestActive(false);
  };

  const addFact = async (text: string): Promise<boolean> => {
    if (mutationDisabled || requestInFlight.current) return false;
    requestInFlight.current = true;
    setFactBusy(true);
    setError(null);
    try {
      const current = profile ?? await api.createProfile("我的经历资料", false);
      if (!profile) {
        applyProfile(current);
        navigate(startPath(current.id), true);
      }
      applyProfile(await api.addFacts(current.id, current.revision, [text]));
      setList("proposed");
      return true;
    } catch (nextError) {
      setError(nextError);
      return false;
    } finally {
      requestInFlight.current = false;
      setFactBusy(false);
    }
  };

  const createResume = async () => {
    if (!profile || requestInFlight.current || !serviceReady || busy || pendingCommand) return;
    const command: ResumeCommand | null = pendingResume ?? (profile.latest_snapshot_id && confirmedCount > 0 ? {
      kind: "profile-resume",
      idempotencyKey: newCommandKey("profile-resume"),
      input: { profile_id: profile.id, expected_revision: profile.revision, profile_snapshot_id: profile.latest_snapshot_id },
    } : null);
    if (!command) return;
    requestInFlight.current = true;
    setSubmitting(true);
    setError(null);
    setPendingResume(command);
    saveRecoverableCommand("profile-resume", profile.id, command);
    try {
      const accepted = await api.createResumeDraft(command.input.profile_id, {
        expected_revision: command.input.expected_revision,
        profile_snapshot_id: command.input.profile_snapshot_id,
      }, command.idempotencyKey);
      trackAccepted(accepted, profile.id);
      clearRecoverableCommand("profile-resume", profile.id);
      setPendingResume(null);
    } catch (nextError) {
      if (!shouldPreserveWriteCommand(nextError)) {
        clearRecoverableCommand("profile-resume", profile.id);
        setPendingResume(null);
      }
      setError(nextError);
    } finally {
      requestInFlight.current = false;
      setSubmitting(false);
    }
  };

  const changeDecision = (claimId: string, decision: ClaimDecision | null): boolean => {
    const { decisions: next, error: limitError } = calculateDecisionUpdate(decisions, claimId, decision, 50);
    setSelectionError(limitError);
    if (limitError) return false;
    setDecisions(next);
    return true;
  };

  const importing = uploadRequestActive || (documentOperation !== null && operationActive)
    || (operationLoading && Boolean(selectedName) && !profile?.proposed_claims.length && !confirmedCount);
  const hasReview = Boolean(profile && (profile.proposed_claims.length || confirmedCount));
  const reviewComplete = Boolean(profile && !profile.proposed_claims.length && confirmedCount > 0 && selection.length === 0);
  const showList = hasReview && (!reviewComplete || list === "confirmed");
  const resumeDisabled = !serviceReady || busy || Boolean(pendingCommand)
    || (!pendingResume && (!profile?.latest_snapshot_id || confirmedCount === 0));

  const profileManagement = profile ? (
                <details className="profile-tools">
                  <summary>资料管理</summary>
                  <div className="profile-tool-actions">
                    <Button ref={uploadTriggerRef} type="secondary" disabled={mutationDisabled} onClick={() => setUploadVisible(true)}>添加 PDF</Button>
                    <Button ref={manualFactTriggerRef} type="secondary" disabled={mutationDisabled} onClick={() => setManualFactVisible(true)}>补充经历</Button>
                    <Button type="secondary" disabled={mutationDisabled} onClick={() => setConfirmDelete(true)}>删除档案</Button>
                  </div>
                </details>
  ) : null;

  return (
    <main className={`page-container start-page progressive-profile ${!hasReview || importing ? "profile-stage-centered" : ""}`}>
      {profile && !hasReview && !importing ? <div className="profile-empty-tools">{profileManagement}</div> : null}
      <ErrorNotice error={error ?? operationError ?? resumeError} onReload={profile || profileId ? () => void reloadProfile() : undefined} />
      {pendingCommand && !submitting && (pendingCommand.kind !== "upload" || !uploadVisible) ? (
        <Alert type="warn" title="上次请求未确认完成">
          <Button type="secondary" disabled={!serviceReady || submitting} onClick={() => void runProfileCommand(pendingCommand)}>继续上次操作</Button>
        </Alert>
      ) : null}
      <UploadModal
        isOpen={uploadVisible}
        disabled={mutationDisabled || Boolean(profileId && !profile)}
        busy={submitting && (!pendingCommand || pendingCommand.kind === "upload")}
        pending={pendingCommand?.kind === "upload"}
        error={uploadVisible ? error : null}
        returnFocusElement={uploadTriggerRef.current?.querySelector<HTMLElement>("button, [role='button']") ?? uploadTriggerRef.current}
        onSelect={(file) => void upload(file)}
        onRetry={() => { if (pendingCommand?.kind === "upload") void runProfileCommand(pendingCommand); }}
        onClose={() => setUploadVisible(false)}
      />
      {manualFactVisible ? (
        <FactModal
          returnFocusElement={manualFactTriggerRef.current?.querySelector<HTMLElement>("button, [role='button']") ?? manualFactTriggerRef.current}
          mode="create" isOpen disabled={mutationDisabled} busy={factBusy}
          onSave={addFact} onClose={() => setManualFactVisible(false)}
        />
      ) : null}
      {importing ? <ResumeScan label={uploadRequestActive ? "正在上传简历" : "正在识别简历"} /> : (
        <>
          {!hasReview ? (
            <div className="profile-upload-center">
              {profileId && !profile ? <p role="status">正在读取资料</p> : (
                <>
                  <DocumentUpload disabled={mutationDisabled} busy={uploadRequestActive} onSelect={(file) => void upload(file)} />
                  <Button ref={manualFactTriggerRef} type="secondary" className="text-action" disabled={mutationDisabled} onClick={() => setManualFactVisible(true)}>手动填写经历</Button>
                </>
              )}
              <DocumentStatus selectedName={selectedName} operation={documentOperation} document={document} />
            </div>
          ) : (
            <>
              <header className="profile-review-heading">
                <h1>{reviewComplete ? "经历已确认" : "核对你的经历"}</h1>
                {profileManagement}
              </header>
              <DocumentStatus selectedName={selectedName} operation={documentOperation} document={document} />
              {reviewComplete ? (
                <section className="profile-ready-state" aria-label="核对完成">
                  <span className="completion-mark" aria-hidden="true">✓</span>
                  <h2>{confirmedCount} 条经历已确认</h2>
                  {interviewReady ? <Button type="primary" size="large" disabled={mutationDisabled} onClick={() => navigate(preparePath(profile!.id))}>进入面试准备</Button> : null}
                  <Button type="secondary" className="text-action" disabled={resumeDisabled} onClick={() => void createResume()}>{pendingResume ? "继续生成简历" : "整理简历"}</Button>
                  {list !== "confirmed" ? <button className="text-action" onClick={() => setList("confirmed")}>查看已确认经历</button> : <button className="text-action" onClick={() => setList("proposed")}>收起经历</button>}
                </section>
              ) : null}
              {!reviewComplete && confirmedCount > 0 && selection.length === 0 ? (
                <div className="profile-continue-actions">
                  {interviewReady ? <Button type="primary" disabled={mutationDisabled} onClick={() => navigate(preparePath(profile!.id))}>使用已确认经历准备面试</Button> : null}
                  <Button type="secondary" className="text-action" disabled={resumeDisabled} onClick={() => void createResume()}>整理已确认经历的简历</Button>
                </div>
              ) : null}
              {showList && profile ? (
                <section className="profile-review-workspace">
                  <div className="fact-list-tabs" role="group" aria-label="切换事实列表">
                    <button aria-pressed={list === "proposed"} onClick={() => setList("proposed")}>待确认 {profile.proposed_claims.length}</button>
                    <button aria-pressed={list === "confirmed"} onClick={() => setList("confirmed")}>已确认 {confirmedCount}</button>
                  </div>
                  <ClaimConfirmList claims={list === "proposed" ? profile.proposed_claims : profile.confirmed_claims} confirmed={list === "confirmed"} decisions={decisions} onDecision={changeDecision} />
                  <Button ref={manualFactTriggerRef} type="secondary" className="text-action add-fact-action" disabled={mutationDisabled} onClick={() => setManualFactVisible(true)}>＋ 补充一条经历</Button>
                </section>
              ) : null}
            </>
          )}
        </>
      )}
      {profile && activation && activation.status !== "ready" ? (
        <section className="profile-activation-status" aria-label="资料准备状态">
          {activation.status === "indexing" || confirmOperationActive ? <p role="status">正在准备已确认资料</p> : null}
          {activation.status === "pending" ? <Button disabled={mutationDisabled} onClick={() => void runProfileCommand({ kind: "activate", profileId: profile.id, revision: profile.revision, key: newCommandKey("activate") })}>继续准备资料</Button> : null}
          {activation.status === "failed" ? (
            <Alert type="danger" title="已确认经历，资料准备未完成">
              <p>{operation?.error?.message ?? "正在读取失败详情"}</p>
              {activation.operation_id && operation?.error?.retryable === true ? <Button disabled={mutationDisabled} onClick={() => void runProfileCommand({ kind: "retry", profileId: profile.id, revision: profile.revision, operationId: activation.operation_id!, key: newCommandKey("profile-retry") })}>重试资料准备</Button> : null}
            </Alert>
          ) : null}
        </section>
      ) : null}
      {profile && (selection.length > 0 || isProcessingConfirm || (confirmOperationFailed && activation?.status !== "failed")) ? (
        <section className="fact-submit-bar" aria-label="提交核对选择">
          <div role="status">{isProcessingConfirm ? "正在保存选择" : `${selection.length} 条待提交`}</div>
          {selectionError ? <p className="field-error" role="alert">{selectionError}</p> : null}
          {invalidCorrection ? <p className="field-error">请填写更正正文。</p> : null}
          {confirmOperationFailed && activation?.status !== "failed" ? <p role="alert">{operation?.error?.message}</p> : null}
          <div className="button-row">
            {selection.length > 0 ? <Button type="secondary" className="text-action" disabled={isProcessingConfirm} onClick={() => { setDecisions({}); setSelectionError(null); }}>撤销选择</Button> : null}
            {selection.length > 0 ? <Button type="primary" loading={isProcessingConfirm} disabled={mutationDisabled || selection.length > 50 || invalidCorrection} onClick={() => void runProfileCommand({ kind: "confirm", profileId: profile.id, revision: profile.revision, decisions: selection.map((decision) => decision.action === "correct" ? { ...decision, corrected_text: decision.corrected_text!.trim() } : decision), key: newCommandKey("confirm") })}>提交 {selection.length} 条选择</Button> : null}
          </div>
        </section>
      ) : null}
      {confirmSuccessFlash && !reviewComplete ? <p role="status" className="inline-success">选择已保存</p> : null}
      {pendingResume && !submitting && !reviewComplete ? <Button disabled={resumeDisabled} onClick={() => void createResume()}>继续生成简历</Button> : null}
      {resumeOperation ? (
        <section aria-label="简历生成状态">
          <p role="status">{resumeActive ? "正在生成简历" : resumeOperation.status === "succeeded" ? "简历已生成" : resumeOperation.error?.message ?? "简历生成未完成"}</p>
          {!resumeActive && resumeOperation.resource_type === "resume_draft" ? <Button onClick={() => navigate(resumeDraftPath(resumeOperation.resource_id))}>查看简历草稿</Button> : null}
        </section>
      ) : null}
      {confirmDelete && profile ? (
        <Alert type="danger" title="永久删除这份档案？">
          <p>档案、解析文本、已确认事实、面试和报告会被永久删除，无法恢复。</p>
          <div className="button-row">
            <Button disabled={mutationDisabled} onClick={() => { setConfirmDelete(false); void runProfileCommand({ kind: "delete", profileId: profile.id, revision: profile.revision, key: newCommandKey("delete") }); }}>确认永久删除</Button>
            <Button onClick={() => setConfirmDelete(false)}>取消</Button>
          </div>
        </Alert>
      ) : null}
      {deleteOperationFailed && profile ? (
        <Alert type="danger" title="档案删除未完成">
          <p>{operation.error?.message}</p>
          {operation.error?.retryable === true ? <Button disabled={!serviceReady || submitting} onClick={() => void runProfileCommand({ kind: "retry", profileId: profile.id, revision: profile.revision, operationId: operation.id, key: newCommandKey("delete-retry") })}>继续删除</Button> : <p>服务端未允许重试，请检查服务后刷新状态。</p>}
        </Alert>
      ) : null}
    </main>
  );
}
