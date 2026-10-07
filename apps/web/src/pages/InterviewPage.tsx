import { Spinner } from "@any-design/anyui/react";
import { Alert, Button } from "../components/common/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, newCommandKey, requestRetryReason, type InterviewView, type OperationView } from "../api";
import { ErrorNotice } from "../components/common/ErrorNotice";
import { OperationStatus } from "../components/common/OperationStatus";
import { AnswerComposer } from "../components/interview/AnswerComposer";
import { DecisionPanel, PreviousDecisionNote } from "../components/interview/DecisionPanel";
import { Icon } from "../components/common/icons";
import { EvidencePanel } from "../components/interview/EvidencePanel";
import { InterviewProgress } from "../components/interview/InterviewProgress";
import { QuestionCard } from "../components/interview/QuestionCard";
import { useOperationMonitor } from "../hooks/useOperationMonitor";
import { interviewRoleText } from "../presentation";
import { reportPath, startPath } from "../routing";
import {
  clearOperationId, loadOperationId, saveOperationId,
  clearRecoverableCommand, loadRecoverableCommand, saveRecoverableCommand,
  type RecoverableCommand,
} from "../storage";
import { loadAnswerDraft, ownsPendingAnswerDraft, reconcileAnswerDrafts, resolvePendingAnswerDraft, saveAnswerDraft, type PendingSubmission } from "../answerDrafts";

type ControlCommand = Extract<RecoverableCommand, { kind: "interview-control" | "interview-control-retry" }>;

function restoreControl(interviewId: string): ControlCommand | null {
  const retry = loadRecoverableCommand("interview-control-retry", interviewId);
  if (retry?.kind === "interview-control-retry") return retry;
  const control = loadRecoverableCommand("interview-control", interviewId);
  return control?.kind === "interview-control" ? control : null;
}

export function InterviewPage(props: Parameters<typeof InterviewSession>[0]) {
  return <InterviewSession key={props.interviewId} {...props} />;
}

function InterviewSession({
  interviewId,
  serviceReady,
  navigate,
}: {
  interviewId: string;
  serviceReady: boolean;
  navigate: (path: string) => void;
}) {
  const [interview, setInterview] = useState<InterviewView | null>(null);
  const [operationId, setOperationId] = useState<string | null>(null);
  const [pendingSubmission, setPendingSubmission] = useState<PendingSubmission | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [draftStorageAvailable, setDraftStorageAvailable] = useState(true);
  const submittingRef = useRef(false);
  const mounted = useRef(false);
  const interviewRef = useRef<InterviewView | null>(null);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  const [controlOperationId, setControlOperationId] = useState<string | null>(() => loadOperationId("interview-control", interviewId));
  const [pendingControl, setPendingControl] = useState<ControlCommand | null>(() => restoreControl(interviewId));
  const [controlSubmitting, setControlSubmitting] = useState(false);
  const [controlError, setControlError] = useState<unknown>(null);
  const [confirmAction, setConfirmAction] = useState<"skip" | "end" | null>(null);
  const controlSubmittingRef = useRef(false);

  const applyInterview = useCallback((next: InterviewView) => {
    if (!mounted.current || next.id !== interviewId
      || (interviewRef.current && interviewRef.current.revision > next.revision)) return;
    interviewRef.current = next;
    setInterview((current) => current?.id === next.id && current.revision > next.revision ? current : next);
    const controlId = loadOperationId("interview-control", next.id);
    if (controlId && next.active_operation_id === controlId) {
      setControlOperationId(controlId);
    } else if (controlId) {
      clearOperationId("interview-control", next.id);
      setControlOperationId(null);
    }
    // 服务端回答恢复键/active_operation_id 是权威；本地键不能压过新快照。
    const recoverableOperation =
      next.current_question?.accepted_answer?.retry_operation_id
      ?? (next.active_operation_id !== controlId ? next.active_operation_id : null);
    if (recoverableOperation) {
      saveOperationId("interview", next.id, recoverableOperation);
      setOperationId(recoverableOperation);
    } else {
      clearOperationId("interview", next.id);
      setOperationId(null);
    }
  }, [interviewId]);

  useEffect(() => {
    if (!interview || interview.id !== interviewId) return;
    const question = interview.current_question;
    const keepQuestion = interview.status === "active" && !interview.stop_requested && !question?.accepted_answer
      ? question?.id ?? null : null;
    setDraftStorageAvailable(reconcileAnswerDrafts(interview.id, keepQuestion));
    const pending = keepQuestion ? loadAnswerDraft(interview.id, keepQuestion)?.pending : null;
    setPendingSubmission(pending ? { ...pending, retryReason: pending.retryReason ?? "network" } : null);
  }, [interview, interviewId]);

  const reload = useCallback(async () => {
    applyInterview(await api.getInterview(interviewId));
  }, [applyInterview, interviewId]);

  useEffect(() => {
    const controller = new AbortController();
    setInterview(null);
    setPendingSubmission(null);
    setError(null);
    setPendingControl(restoreControl(interviewId));
    setControlOperationId(loadOperationId("interview-control", interviewId));
    setControlError(null);
    setConfirmAction(null);
    api.getInterview(interviewId, controller.signal)
      .then(applyInterview)
      .catch((nextError) => {
        if (!(nextError instanceof DOMException && nextError.name === "AbortError")) setError(nextError);
      });
    return () => controller.abort();
  }, [applyInterview, interviewId]);

  const operationSettled = useCallback(async (settled: OperationView, signal: AbortSignal) => {
    try {
      const next = await api.getInterview(interviewId, signal);
      if (!mounted.current || signal.aborted) return;
      if (!interviewRef.current || interviewRef.current.revision <= next.revision) interviewRef.current = next;
      setInterview((current) => current && current.revision > next.revision ? current : next);
      if (settled.status === "succeeded") {
        if (loadOperationId("interview", interviewId) === settled.id) clearOperationId("interview", interviewId);
        setOperationId((current) => current === settled.id ? null : current);
      }
      if (settled.kind.startsWith("interview.control.") && settled.status === "succeeded" && next.status === "completed" && next.report_id) {
        navigate(reportPath(next.id));
      }
    } catch (nextError) {
      if (mounted.current && !signal.aborted) setError(nextError);
    }
  }, [interviewId, navigate]);

  const operationUnavailable = useCallback((nextError: ApiError) => {
    clearOperationId("interview", interviewId);
    setOperationId(null);
    setError(nextError);
  }, [interviewId]);
  const { operation, error: operationError } = useOperationMonitor(
    operationId,
    operationSettled,
    operationUnavailable,
  );

  const controlSettled = useCallback(async (settled: OperationView, signal: AbortSignal) => {
    try {
      const next = await api.getInterview(interviewId);
      if (!mounted.current || signal.aborted) return;
      if (!interviewRef.current || interviewRef.current.revision <= next.revision) interviewRef.current = next;
      setInterview((current) => current && current.revision > next.revision ? current : next);
      if (settled.status === "succeeded") {
        if (loadOperationId("interview-control", interviewId) === settled.id) clearOperationId("interview-control", interviewId);
        setControlOperationId((current) => current === settled.id ? null : current);
        if (next.status === "completed" && next.report_id) navigate(reportPath(next.id));
      }
    } catch (nextError) {
      if (mounted.current && !signal.aborted) setControlError(nextError);
    }
  }, [interviewId, navigate]);
  const controlUnavailable = useCallback((nextError: ApiError) => {
    clearOperationId("interview-control", interviewId);
    setControlOperationId(null);
    setControlError(nextError);
  }, [interviewId]);
  const { operation: monitoredControl, error: controlOperationError } = useOperationMonitor(
    controlOperationId,
    controlSettled,
    controlUnavailable,
  );
  const controlOperation = monitoredControl ?? (operation?.kind.startsWith("interview.control.") ? operation : null);
  const controlFailure = controlOperation
    && ["failed", "interrupted"].includes(controlOperation.status)
    ? controlOperation
    : null;
  const controlActive = Boolean(controlOperationId)
    && !controlOperationError
    && (!monitoredControl || ["queued", "running"].includes(monitoredControl.status));
  const answerOperationActive = Boolean(operationId)
    && !operationError
    && (!operation || ["queued", "running"].includes(operation.status));
  const controlBlocked = controlSubmitting || controlActive || Boolean(pendingControl)
    || Boolean(interview?.stop_requested)
    || controlFailure?.error?.retryable === true;

  const executeControl = async (command: ControlCommand) => {
    if (!interview || controlSubmittingRef.current || submittingRef.current) return;
    controlSubmittingRef.current = true;
    setControlSubmitting(true);
    setPendingControl(command);
    saveRecoverableCommand(command.kind, interview.id, command);
    setControlError(null);
    try {
      const accepted = command.kind === "interview-control"
        ? await api.controlInterview(interview.id, command.input.expected_revision, command.input.action, command.idempotencyKey)
        : await api.retryOperation(command.input.operation_id, command.input.expected_revision, command.idempotencyKey);
      saveOperationId("interview-control", interview.id, accepted.operation_id);
      setControlOperationId(accepted.operation_id);
      if (operation?.kind.startsWith("interview.control.")) {
        if (loadOperationId("interview", interview.id) === operation.id) clearOperationId("interview", interview.id);
        setOperationId((current) => current === operation.id ? null : current);
      }
      clearRecoverableCommand(command.kind, interview.id);
      setPendingControl(null);
      setConfirmAction(null);
      await reload();
    } catch (nextError) {
      setControlError(nextError);
      if (nextError instanceof ApiError && !requestRetryReason(nextError)) {
        clearRecoverableCommand(command.kind, interview.id);
        setPendingControl(null);
        setConfirmAction(null);
        if (nextError.code === "REVISION_CONFLICT" || nextError.code === "OPERATION_IN_PROGRESS") {
          await reload().catch(setControlError);
        }
      }
    } finally {
      controlSubmittingRef.current = false;
      setControlSubmitting(false);
    }
  };

  const submitControl = () => {
    if (!interview || !confirmAction || pendingControl) return;
    if (confirmAction === "skip" && (!interview.current_question || interview.active_operation_id || answerOperationActive)) return;
    void executeControl({
      kind: "interview-control", idempotencyKey: newCommandKey(confirmAction),
      input: { expected_revision: interview.revision, action: confirmAction },
    });
  };

  const retryControl = () => {
    if (!interview || !controlOperation) return;
    void executeControl({
      kind: "interview-control-retry", idempotencyKey: newCommandKey("control-retry"),
      input: { expected_revision: interview.revision, operation_id: controlOperation.id },
    });
  };

  const submitAnswer = async (answerText: string) => {
    const question = interview?.current_question;
    if (!interview || !question || submittingRef.current || controlSubmittingRef.current || controlBlocked || answerOperationActive) return;
    const command: PendingSubmission = pendingSubmission?.questionId === question.id
      && pendingSubmission.answerText === answerText
      ? pendingSubmission
      : {
          questionId: question.id,
          expectedRevision: interview.revision,
          clientTurnId: newCommandKey("turn"),
          idempotencyKey: newCommandKey("answer"),
          answerText,
          retryReason: null,
        };
    setPendingSubmission(command);
    setDraftStorageAvailable(saveAnswerDraft(interview.profile_id, interview.id, question.id, {
      text: command.answerText, pending: command,
    }));
    setSubmitting(true);
    submittingRef.current = true;
    setError(null);
    let answerAccepted = false;
    try {
      const accepted = await api.submitAnswer(
        interview.id,
        {
          expected_revision: command.expectedRevision,
          question_id: command.questionId,
          client_turn_id: command.clientTurnId,
          answer_text: command.answerText,
        },
        command.idempotencyKey,
      );
      answerAccepted = true;
      const current = interviewRef.current;
      if (current && (current.id !== interview.id || current.status !== "active"
        || current.stop_requested || current.current_question?.id !== command.questionId
        || current.current_question.accepted_answer)) return;
      const cleared = resolvePendingAnswerDraft(interview.profile_id, interview.id, command, null);
      if (cleared === null) return;
      saveOperationId("interview", interview.id, accepted.operation_id);
      if (!mounted.current) return;
      setDraftStorageAvailable(cleared);
      setOperationId(accepted.operation_id);
      setPendingSubmission(null);
      applyInterview(await api.getInterview(interview.id));
    } catch (nextError) {
      if (answerAccepted) {
        if (mounted.current) setError(nextError);
        return;
      }
      if (!ownsPendingAnswerDraft(interview.id, command)) return;
      const current = interviewRef.current;
      if (current && (current.id !== interview.id || current.status !== "active"
        || current.stop_requested || current.current_question?.id !== command.questionId
        || current.current_question.accepted_answer)) return;
      const retryReason = nextError instanceof ApiError ? requestRetryReason(nextError) : "network";
      const retry: PendingSubmission | null = retryReason ? { ...command, retryReason } : null;
      const saved = resolvePendingAnswerDraft(interview.profile_id, interview.id, command, {
        text: command.answerText, pending: retry,
      });
      if (saved === null || !mounted.current) return;
      setError(nextError);
      setPendingSubmission(retry);
      setDraftStorageAvailable(saved);
      if (nextError instanceof ApiError
        && (nextError.code === "REVISION_CONFLICT" || nextError.code === "OPERATION_IN_PROGRESS")) {
        await reload().catch((reloadError) => { if (mounted.current) setError(reloadError); });
      }
    } finally {
      submittingRef.current = false;
      if (mounted.current) setSubmitting(false);
    }
  };

  const retryAnalysis = async () => {
    if (!interview || submittingRef.current || controlSubmittingRef.current || controlBlocked || answerOperationActive) return;
    // 链尾恢复键以服务端视图为权威；operation/sessionStorage 只是兜底。
    const failedOperationId = interview.current_question?.accepted_answer?.retry_operation_id
      ?? operation?.id ?? loadOperationId("interview", interview.id);
    if (!failedOperationId) return;
    setSubmitting(true);
    submittingRef.current = true;
    setError(null);
    try {
      const accepted = await api.retryOperation(
        failedOperationId,
        interview.revision,
        newCommandKey("retry"),
      );
      saveOperationId("interview", interview.id, accepted.operation_id);
      setOperationId(accepted.operation_id);
      applyInterview(await api.getInterview(interview.id));
    } catch (nextError) {
      setError(nextError);
      if (nextError instanceof ApiError && nextError.code === "REVISION_CONFLICT") {
        await reload().catch(setError);
      }
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  if (!interview) {
    return (
      <main className="page-container narrow-page">
        <ErrorNotice error={error} onReload={() => void reload()} />
        {!error ? <p className="loading-row">正在读取面试状态</p> : null}
      </main>
    );
  }

  const question = interview.current_question;
  const total = interview.root_plan.slots.length;
  const acceptedAnswer = question?.accepted_answer ?? null;
  const isFinishing = !question && interview.status === "finishing";
  const isCompleted = !question && interview.status === "completed";
  // 计划就绪前的“无当前题”是还没开始，不是问完；进度条必须区分这两种真相。
  const interviewStarted = ["active", "finishing", "finish_failed", "completed"].includes(interview.status);
  // 与 Report/ResumeDraft 同构：重试 affordance 必须等服务端确认该操作
  // 可重试（error.retryable）才出现；恢复键跨浏览器后，预算耗尽的失败
  // 回答不能亮出只会吃 409 的假按钮。
  const canRetryAnalysis = acceptedAnswer?.evaluation_status === "failed"
    && operation?.error?.retryable === true
    && !operation.kind.startsWith("interview.control.")
    && !controlBlocked && !answerOperationActive;
  // 有服务端恢复键但预算已尽：文案必须说“预算用完”，不是“没有编号”。
  const retryBudgetExhausted = acceptedAnswer?.evaluation_status === "failed"
    && Boolean(acceptedAnswer.retry_operation_id)
    && operation?.error?.retryable === false;
  const canSkip = interview.status === "active" && Boolean(question) && !interview.active_operation_id
    && !submitting && !pendingSubmission && !controlBlocked && !answerOperationActive;
  const canEnd = ["active", "finishing", "finish_failed"].includes(interview.status)
    && !submitting && !pendingSubmission && !controlBlocked;
  const controlFailed = controlFailure;

  return (
    <main className="page-container interview-page">
      <header className="interview-header">
        <div className="interview-header__title">
          <p className="eyebrow">模拟面试</p>
          <h1>{interviewRoleText(interview)}</h1>
          {/* 本场冻结包摘要；不从“当前列表默认项”倒推。 */}
          <p className="interview-pack-line">
            {interview.knowledge_pack?.binding === "frozen"
              ? `岗位知识包：${interview.knowledge_pack.name} v${interview.knowledge_pack.version}（本场固定使用）`
              : interview.knowledge_pack?.binding === "frozen_unavailable"
                ? "岗位知识包：本场使用的知识包当前不可用，请重新生成计划。"
                : "岗位知识包：这场面试没有记录当时使用的版本，题目与报告保持原样。"}
          </p>
          {interview.knowledge_pack.binding === "frozen" ? (
            <details className="compact-details">
              <summary>能力规则版本</summary>
              <p>{interview.knowledge_pack.profile_version ?? "未提供"}</p>
              <p className="technical-value">规则摘要：{interview.knowledge_pack.profile_digest ?? "未提供"}</p>
            </details>
          ) : null}
        </div>
        <InterviewProgress total={total} question={question} started={interviewStarted} />
      </header>
      <ErrorNotice error={error ?? operationError} onReload={() => void reload()} />
      <ErrorNotice error={controlError ?? controlOperationError} onReload={() => void reload()} />
      {!draftStorageAvailable ? <Alert type="warn" title="浏览器草稿暂存不可用">暂存读写失败，刷新后草稿可能无法恢复；如需移除旧副本，请清除本站的浏览器数据。</Alert> : null}
      {interviewStarted && !isCompleted ? (
        <section className="interview-controls" aria-label="面试进程控制">
          <details className="interview-secondary-menu">
            <summary>跳过本题或提前结束</summary>
            <div className="interview-control-actions">
              <Button disabled={!serviceReady || !canSkip} onClick={() => setConfirmAction("skip")}>跳过本题</Button>
              <Button disabled={!serviceReady || !canEnd} onClick={() => setConfirmAction("end")}>提前结束面试</Button>
            </div>
          </details>
          {confirmAction ? (
            <Alert type="warn" title={confirmAction === "end" ? "确认提前结束面试？" : "确认跳过当前题？"}>
              {confirmAction === "end"
                ? "结束后不再出题，输入框里还没提交的回答不会保存。正在分析的回答会等分析完成后再生成报告；没问到的题记为“未考察”，不算零分。已经发出的模型请求可能无法立刻停止。"
                : question?.kind === "main"
                  ? "输入框里还没提交的回答不会保存。本题记为“已跳过”，不算零分，接着进入下一道主问题；跳过最后一题会直接生成报告。"
                  : "输入框里还没提交的回答不会保存。跳过这道追问后进入下一道主问题，本题已有的回答会保留。"}
              <div className="interview-control-confirm">
                <Button type="primary" loading={controlSubmitting} disabled={!serviceReady || (confirmAction === "skip" ? !canSkip : !canEnd)} onClick={submitControl}>
                  {confirmAction === "end" ? "确认结束，生成报告" : "确认跳过本题"}
                </Button>
                <Button disabled={controlSubmitting || Boolean(pendingControl)} onClick={() => setConfirmAction(null)}>返回作答</Button>
              </div>
            </Alert>
          ) : null}
          {pendingControl ? (
            <Alert type="warn" title="上次操作未确认完成">
              刚才的“跳过 / 结束”没有收到结果。点重试会沿用原操作，不会重复跳题或重复结束。
              <Button disabled={!serviceReady || controlSubmitting || submitting} loading={controlSubmitting} onClick={() => void executeControl(pendingControl)}>重试上次操作</Button>
            </Alert>
          ) : null}
          {controlFailed && !pendingControl ? (
            <Alert type="danger" title="跳过 / 结束操作失败">
              <p>{controlFailed.error?.message ?? "操作没有完成；已保存的回答仍然保留。"}</p>
              {controlFailed.error?.retryable === true ? (
                <>
                  <p>重试只恢复这次操作，不会重新提交你的回答。</p>
                  <Button disabled={!serviceReady || controlSubmitting || submitting || controlActive} onClick={retryControl}>重试{controlFailed.kind.endsWith(".end") ? "结束面试" : "跳过本题"}</Button>
                </>
              ) : (
                <>
                  <p>{controlFailed.kind.endsWith(".skip")
                    ? "这次跳过无法重试，你可以继续回答当前题。"
                    : "这次结束无法重试。作答记录都已保留，请检查服务后重新打开本场面试。"}</p>
                  {controlFailed.kind.endsWith(".end") ? (
                    <Button type="secondary" onClick={() => navigate(startPath(interview.profile_id))}>返回资料页</Button>
                  ) : null}
                </>
              )}
            </Alert>
          ) : null}
          {interview.stop_requested ? <p className="muted">结束请求已收到，不再接收新的回答；正在等当前处理完成并整理报告。</p> : null}
          <OperationStatus operation={controlOperation} label={controlOperation?.kind.endsWith(".skip") ? "跳过本题" : "结束面试"} />
        </section>
      ) : null}
      {interview.status === "ready" ? (
        <Alert type="warn" title="面试尚未开始">
          请回到“面试准备”页面点“开始模拟面试”；直接打开这个链接不会生成第一题。
        </Alert>
      ) : null}
      {interview.status === "prepare_failed" ? (
        <Alert type="danger" title="面试准备失败">
          本场面试计划没有生成成功，暂时无法开始。请回到“面试准备”重新生成计划。
        </Alert>
      ) : null}
      {interview.status === "finish_failed" ? (
        <Alert type="danger" title="报告整理失败">
          提问已经结束，但报告没有保存成功。作答记录都还在，可以用上方的“重试结束面试”继续生成报告，不会重新提交回答。
        </Alert>
      ) : null}
      {isFinishing ? (
        <section className="completion-card interview-completion" aria-live="polite">
          <span className="completion-card__spinner" aria-hidden="true"><Spinner /></span>
          <h2>提问已结束，报告整理中</h2>
          <p>正在汇总本场评分结果，报告生成后会自动显示。</p>
        </section>
      ) : null}
      {isCompleted ? (
        <section className="completion-card interview-completion">
          <span className="completion-mark" aria-hidden="true"><Icon name="check" strokeWidth={2.4} /></span>
          <h2>本场提问已完成，报告已经形成</h2>
          <p>复盘页按题列出原回答、评分依据和可补充的真实细节；未回答或跳过的题不会被算作零分。</p>
          {interview.report_id ? (
            <Button type="primary" size="large" onClick={() => navigate(reportPath(interview.id))}>
              查看面试报告
            </Button>
          ) : null}
        </section>
      ) : null}

      {question ? (
        <div className="interview-stage">
          <div className="interview-question-column">
            <PreviousDecisionNote interview={interview} question={question} />
            <QuestionCard question={question} />
            <details className="interview-basis-details" key={question.id} open={question.kind !== "main" || undefined}>
              <summary>{question.kind === "main" ? "为什么问这一题" : question.kind === "probe" ? "为什么继续追问" : "为什么需要澄清"}</summary>
              {question.kind === "main" ? (
                <EvidencePanel interview={interview} question={question} />
              ) : (
                <DecisionPanel interview={interview} question={question} />
              )}
            </details>
          </div>
          <div className="interview-answer-column">
            <AnswerComposer
              profileId={interview.profile_id}
              interviewId={interview.id}
              question={question}
              acceptedAnswer={acceptedAnswer}
              submitting={submitting}
              serviceReady={serviceReady && !controlBlocked && !answerOperationActive}
              pendingRetryText={pendingSubmission?.questionId === question.id ? pendingSubmission.answerText : null}
              retryReason={pendingSubmission?.questionId === question.id ? pendingSubmission.retryReason : null}
              canRetryAnalysis={canRetryAnalysis}
              retryBudgetExhausted={retryBudgetExhausted}
              onSubmit={submitAnswer}
              onResetRetry={() => {
                const pending = pendingSubmission;
                if (pending?.questionId === question.id) {
                  const saved = resolvePendingAnswerDraft(interview.profile_id, interview.id, pending, {
                    text: pending.answerText, pending: null,
                  });
                  if (saved !== null) setDraftStorageAvailable(saved);
                }
                setPendingSubmission(null);
              }}
              onRetryAnalysis={retryAnalysis}
            />
            {operation && ["queued", "running"].includes(operation.status)
              && !operation.kind.startsWith("interview.control.")
              ? <OperationStatus operation={operation} label="回答分析" />
              : null}
          </div>
        </div>
      ) : null}
    </main>
  );
}
