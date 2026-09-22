import { Alert, Button, Tag } from "@any-design/anyui/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { api, newCommandKey, shouldPreserveWriteCommand, type OperationAccepted, type OperationView, type ProfileView } from "../api";
import { ClaimConfirmList } from "../components/profile/ClaimConfirmList";
import { calculateDecisionUpdate, type ClaimDecision } from "../components/profile/claimDecisions";
import { DocumentStatus } from "../components/profile/DocumentStatus";
import { DocumentUpload } from "../components/profile/DocumentUpload";
import { ManualFactForm } from "../components/profile/ManualFactForm";
import { FactModal } from "../components/profile/FactModal";
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

  return (
    <main className={`page-container start-page ${profile ? "start-page--progress" : "start-page--initial"}`}>
      {profile ? (
        <header className="compact-page-heading start-ready-heading">
          <div>
            <p className="eyebrow">资料核对</p>
            <h1>确认你的经历事实</h1>
            <p>已确认 {confirmedCount} 条 · 待确认 {profile.proposed_claims.length} 条 · 材料 {profile.documents.length} 份</p>
          </div>
          <div className="heading-actions">
            <Button type="secondary" disabled={!serviceReady || busy || Boolean(pendingCommand) || (!pendingResume && (!profile.latest_snapshot_id || confirmedCount === 0))} onClick={() => void createResume()}>{pendingResume ? "继续未完成的生成" : "生成通用简历草稿"}</Button>
            <Button type="primary" size="large" disabled={mutationDisabled || !interviewReady} onClick={() => navigate(preparePath(profile.id))}>进入面试准备</Button>
          </div>
        </header>
      ) : (
        <div className="page-intro centered-intro">
          <p className="eyebrow">资料导入</p>
          <h1>准备你的经历资料</h1>
          <p>上传简历 PDF，或直接填写经历。不需要先有简历，也不需要先面试才能生成简历草稿。</p>
        </div>
      )}
      <ErrorNotice error={error ?? operationError ?? resumeError} onReload={profile || profileId ? () => void reloadProfile() : undefined} />
      {pendingCommand && !submitting ? (
        <Alert type="warn" title="上次请求未确认完成">
          <p>本次操作已保留，点“重新提交”会继续原请求，不会重复创建。{pendingCommand.kind === "upload" ? "PDF 文件只暂存在本页面；关闭或刷新后需重新选择。" : pendingCommand.kind === "confirm" ? "更正后的正文也只暂存在本页面。" : ""}</p>
          <Button type="secondary" disabled={!serviceReady || submitting} onClick={() => void runProfileCommand(pendingCommand)}>重新提交</Button>
        </Alert>
      ) : null}
      {pendingResume && !submitting ? <Alert type="warn" title="简历生成请求未确认完成">已保留本次生成请求，点上方“生成通用简历草稿”按钮会显示“继续未完成的生成”，点击即可续上，不会重复生成第二份。</Alert> : null}
      {profile ? (
        <section className="surface-card profile-activation" aria-label="资料准备状态">
          <div className="card-heading-row">
            <Tag>{activation ? ({ pending: "资料等待准备", indexing: "正在准备资料", ready: "资料已就绪", failed: "资料准备失败" }[activation.status]) : "还没有已确认的经历"}</Tag>
            {activation?.status === "pending" ? <Button type="secondary" disabled={mutationDisabled} onClick={() => void runProfileCommand({ kind: "activate", profileId: profile.id, revision: profile.revision, key: newCommandKey("activate") })}>继续准备资料</Button> : null}
            {activation?.status === "failed" && activation.operation_id ? <Button type="secondary" disabled={mutationDisabled || operation?.error?.retryable !== true} onClick={() => void runProfileCommand({ kind: "retry", profileId: profile.id, revision: profile.revision, operationId: activation.operation_id!, key: newCommandKey("profile-retry") })}>重试资料准备</Button> : null}
          </div>
          <p>{confirmedCount === 0 ? "至少确认一条经历事实，才能开始面试或生成简历草稿。" : interviewReady ? "可以开始面试了；也可以直接生成通用简历草稿，不必先面试。" : "已确认的经历可以直接用来生成通用简历；开始面试需等资料准备完成。"}</p>
          {operation && operation.kind !== "document.import" && operation.status !== "succeeded" ? <p role="status">{operationActive ? "正在处理资料，请稍候。" : operation.error?.message ?? "资料操作未完成，请刷新查看最新状态。"}</p> : null}
        </section>
      ) : null}
      {resumeOperation ? (
        <section className="surface-card profile-resume-status" aria-label="通用简历生成状态">
          <p role="status">{resumeActive ? "正在生成通用简历草稿，完成后将自动打开。" : resumeOperation.status === "succeeded" ? "通用简历草稿已生成。" : resumeOperation.error?.message ?? "通用简历生成未完成。"}</p>
          {!resumeActive && resumeOperation.resource_type === "resume_draft" ? <Button type="secondary" onClick={() => navigate(resumeDraftPath(resumeOperation.resource_id))}>查看简历草稿</Button> : null}
        </section>
      ) : null}
      {deleteOperationFailed ? (
        <Alert type="danger" title="档案删除未完成">
          <p>{operation.error?.message ?? "删除过程中出现错误，档案仍处于删除中。"}</p>
          {operation.error?.retryable === true ? (
            <Button
              type="secondary"
              disabled={!serviceReady || submitting}
              onClick={() => profile && void runProfileCommand({
                kind: "retry",
                profileId: profile.id,
                revision: profile.revision,
                operationId: operation.id,
                key: newCommandKey("delete-retry"),
              })}
            >
              继续删除
            </Button>
          ) : (
            <p>服务端未允许自动重试；请重新检查服务后刷新状态。</p>
          )}
        </Alert>
      ) : null}
      <section className={profile ? "start-workspace profile-facts-workspace" : "start-entry-options"} aria-label="资料工作区">
        <div className="start-material-column">
          <DocumentStatus selectedName={selectedName} operation={documentOperation} document={document} />
          {profile ? (
            <details className="profile-material-upload" open={uploadVisible} onToggle={(event) => setUploadVisible(event.currentTarget.open)}>
              <summary>{document ? "重新上传 / 添加 PDF" : "上传简历 PDF（可选）"}</summary>
              <DocumentUpload disabled={mutationDisabled} busy={submitting && pendingCommand?.kind === "upload"} onSelect={(file) => void upload(file)} />
            </details>
          ) : <DocumentUpload disabled={mutationDisabled || Boolean(profileId)} busy={submitting} onSelect={(file) => void upload(file)} />}
          {profile ? <Button ref={manualFactTriggerRef} type="secondary" onClick={() => setManualFactVisible(true)}>+ 补充经历事实</Button> : null}
          {profile ? (
            <details className="profile-danger-zone" onToggle={(event) => !event.currentTarget.open && setConfirmDelete(false)}>
              <summary>删除档案</summary>
              {!confirmDelete ? (
                <Button type="secondary" disabled={mutationDisabled} onClick={() => setConfirmDelete(true)}>我要删除档案</Button>
              ) : (
                <>
                  <p className="field-error" role="alert">这会永久删除档案、解析文本、已确认事实、面试和报告，删除后无法恢复。</p>
                  <div className="button-row">
                    <Button type="primary" disabled={mutationDisabled} loading={submitting && pendingCommand?.kind === "delete"} onClick={() => { setConfirmDelete(false); void runProfileCommand({ kind: "delete", profileId: profile.id, revision: profile.revision, key: newCommandKey("delete") }); }}>确认永久删除</Button>
                    <Button disabled={submitting} onClick={() => setConfirmDelete(false)}>取消，保留档案</Button>
                  </div>
                </>
              )}
            </details>
          ) : null}
        </div>
        <div className="start-claims-column">
          {!profile ? <ManualFactForm disabled={mutationDisabled || Boolean(profileId && !profile)} busy={factBusy} onSubmit={addFact} /> : null}
          {profile && manualFactVisible ? (
            <FactModal
              returnFocusElement={manualFactTriggerRef.current?.querySelector<HTMLElement>("button, [role='button']") ?? manualFactTriggerRef.current}
              mode="create"
              isOpen={manualFactVisible}
              disabled={mutationDisabled}
              busy={factBusy}
              onSave={addFact}
              onClose={() => setManualFactVisible(false)}
            />
          ) : null}
          {profile ? (
            <>
              <div className="fact-list-tabs" role="group" aria-label="切换事实列表">
                <Button type={list === "proposed" ? "primary" : "secondary"} aria-pressed={list === "proposed"} onClick={() => setList("proposed")}>待确认（{profile.proposed_claims.length}）</Button>
                <Button type={list === "confirmed" ? "primary" : "secondary"} aria-pressed={list === "confirmed"} onClick={() => setList("confirmed")}>已确认（{confirmedCount}）</Button>
              </div>
              {/* 选择/更正编辑是本地动作（docs/08 §2）：后台操作进行中仍可选择，
                  只有“批量提交”本身被 mutationDisabled 门禁。 */}
              <ClaimConfirmList claims={list === "proposed" ? profile.proposed_claims : profile.confirmed_claims} confirmed={list === "confirmed"} decisions={decisions} onDecision={changeDecision} />
              <div className={`surface-card fact-submit-bar ${isProcessingConfirm ? "fact-submit-bar--submitting" : ""} ${confirmSuccessFlash ? "fact-submit-bar--success" : ""}`}>
                <div className="submit-bar-status">
                  <div className="submit-bar-text">
                    <p aria-live="polite">
                      {confirmSubmitting
                        ? "正在提交你的选择..."
                        : confirmRetrySubmitting
                          ? "正在重新提交保存操作..."
                          : confirmOperationActive
                            ? "正在保存你的选择并更新资料..."
                            : confirmSuccessFlash
                              ? "选择已保存，资料已更新！"
                              : `已勾选 ${selection.length} 条（单次最多 50 条）；勾选只是暂存，还没提交。`}
                    </p>
                  </div>
                  {isProcessingConfirm ? (
                    <span className="live-pulse-indicator" aria-hidden="true" title="操作进行中" />
                  ) : confirmSuccessFlash ? (
                    <span className="success-badge-indicator" aria-hidden="true">✓</span>
                  ) : null}
                </div>
                {confirmOperationFailed && operation?.error ? (
                  <div className="confirm-failed-notice">
                    <p className="field-error" role="alert">
                      {operation.error.message}
                    </p>
                    {operation.error.retryable && operationId ? (
                      <Button
                        size="small"
                        type="secondary"
                        disabled={mutationDisabled}
                        onClick={() =>
                          void runProfileCommand({
                            kind: "retry",
                            profileId: profile.id,
                            revision: profile.revision,
                            operationId,
                            key: newCommandKey("confirm-retry"),
                          })
                        }
                      >
                        重试保存操作
                      </Button>
                    ) : (
                      <p className="operation-terminal-note">
                        你的选择已保存，但这一版资料准备未能完成且无法重试。请刷新页面查看最新状态。
                      </p>
                    )}
                  </div>
                ) : null}
                {selectionError ? <p className="field-error" role="alert">{selectionError}</p> : null}
                {invalidCorrection ? <p className="field-error">请填写更正正文，或取消该条编辑。</p> : null}
                <div className="button-row">
                  <Button type="secondary" disabled={selection.length === 0} onClick={() => { setDecisions({}); setSelectionError(null); }}>取消全部选择</Button>
                  <Button type="primary" loading={isProcessingConfirm} disabled={mutationDisabled || selection.length === 0 || selection.length > 50 || invalidCorrection} onClick={() => void runProfileCommand({ kind: "confirm", profileId: profile.id, revision: profile.revision, decisions: selection.map((decision) => decision.action === "correct" ? { ...decision, corrected_text: decision.corrected_text!.trim() } : decision), key: newCommandKey("confirm") })}>批量提交 {selection.length} 条选择</Button>
                </div>
              </div>
            </>
          ) : null}
        </div>
      </section>
    </main>
  );
}
