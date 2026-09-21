import { Alert, Button, Tag } from "@any-design/anyui/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, newCommandKey, requestRetryReason, type InterviewView, type OperationView } from "../api";
import { ErrorNotice } from "../components/common/ErrorNotice";
import { OperationStatus } from "../components/common/OperationStatus";
import { AnswerComposer } from "../components/interview/AnswerComposer";
import { DecisionPanel } from "../components/interview/DecisionPanel";
import { EvidencePanel } from "../components/interview/EvidencePanel";
import { InterviewProgress } from "../components/interview/InterviewProgress";
import { QuestionCard } from "../components/interview/QuestionCard";
import { useOperationMonitor } from "../hooks/useOperationMonitor";
import { interviewRoleText, interviewStatusText } from "../presentation";
import { reportPath } from "../routing";
import {
  clearOperationId, loadOperationId, saveOperationId,
  clearRecoverableCommand, loadRecoverableCommand, saveRecoverableCommand,
  type RecoverableCommand,
} from "../storage";

type ControlCommand = Extract<RecoverableCommand, { kind: "interview-control" | "interview-control-retry" }>;

function restoreControl(interviewId: string): ControlCommand | null {
  const retry = loadRecoverableCommand("interview-control-retry", interviewId);
  if (retry?.kind === "interview-control-retry") return retry;
  const control = loadRecoverableCommand("interview-control", interviewId);
  return control?.kind === "interview-control" ? control : null;
}

type PendingSubmission = {
  questionId: string;
  expectedRevision: number;
  clientTurnId: string;
  idempotencyKey: string;
  answerText: string;
  retryReason: "network" | "capacity" | "service" | null;
};

export function InterviewPage({
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
  const submittingRef = useRef(false);
  const [controlOperationId, setControlOperationId] = useState<string | null>(() => loadOperationId("interview-control", interviewId));
  const [pendingControl, setPendingControl] = useState<ControlCommand | null>(() => restoreControl(interviewId));
  const [controlSubmitting, setControlSubmitting] = useState(false);
  const [controlError, setControlError] = useState<unknown>(null);
  const [confirmAction, setConfirmAction] = useState<"skip" | "end" | null>(null);
  const controlSubmittingRef = useRef(false);

  const applyInterview = useCallback((next: InterviewView) => {
    setInterview((current) => current?.id === next.id && current.revision > next.revision ? current : next);
    setPendingSubmission((current) => current && (
      next.current_question?.id !== current.questionId
      || next.current_question?.accepted_answer?.client_turn_id === current.clientTurnId
    ) ? null : current);
    const controlId = loadOperationId("interview-control", next.id);
    // 失败回答的链尾恢复键优先于 localStorage（api.md §6）：跨浏览器、清缓存
    // 后仍能恢复“重试分析”，不丢用户的已保存回答入口。
    const recoverableOperation =
      next.current_question?.accepted_answer?.retry_operation_id
      ?? next.active_operation_id
      ?? loadOperationId("interview", next.id);
    if (recoverableOperation && recoverableOperation !== controlId) {
      saveOperationId("interview", next.id, recoverableOperation);
      setOperationId(recoverableOperation);
    }
  }, []);

  const reload = useCallback(async () => {
    applyInterview(await api.getInterview(interviewId));
  }, [applyInterview, interviewId]);

  useEffect(() => {
    const controller = new AbortController();
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

  const operationSettled = useCallback(async (settled: OperationView) => {
    try {
      if (settled.status === "succeeded") {
        if (loadOperationId("interview", interviewId) === settled.id) clearOperationId("interview", interviewId);
        setOperationId((current) => current === settled.id ? null : current);
      }
      const next = await api.getInterview(interviewId);
      setInterview((current) => current && current.revision > next.revision ? current : next);
      if (settled.kind.startsWith("interview.control.") && settled.status === "succeeded" && next.status === "completed" && next.report_id) {
        navigate(reportPath(next.id));
      }
    } catch (nextError) {
      setError(nextError);
    }
  }, [interviewId, navigate]);

  const { operation, error: operationError } = useOperationMonitor(operationId, operationSettled);

  const controlSettled = useCallback(async (settled: OperationView) => {
    try {
      const next = await api.getInterview(interviewId);
      setInterview((current) => current && current.revision > next.revision ? current : next);
      if (settled.status === "succeeded") {
        if (loadOperationId("interview-control", interviewId) === settled.id) clearOperationId("interview-control", interviewId);
        setControlOperationId((current) => current === settled.id ? null : current);
        if (next.status === "completed" && next.report_id) navigate(reportPath(next.id));
      }
    } catch (nextError) {
      setControlError(nextError);
    }
  }, [interviewId, navigate]);
  const { operation: monitoredControl, error: controlOperationError } = useOperationMonitor(controlOperationId, controlSettled);
  const controlOperation = monitoredControl ?? (operation?.kind.startsWith("interview.control.") ? operation : null);
  const controlActive = Boolean(controlOperationId) && (!monitoredControl || ["queued", "running"].includes(monitoredControl.status));
  const answerOperationActive = Boolean(operationId) && (!operation || ["queued", "running"].includes(operation.status));
  const controlBlocked = controlSubmitting || controlActive || Boolean(pendingControl)
    || Boolean(interview?.stop_requested)
    || Boolean(controlOperation && ["failed", "interrupted"].includes(controlOperation.status));

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
    setSubmitting(true);
    submittingRef.current = true;
    setError(null);
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
      saveOperationId("interview", interview.id, accepted.operation_id);
      setOperationId(accepted.operation_id);
      setPendingSubmission(null);
      applyInterview(await api.getInterview(interview.id));
    } catch (nextError) {
      setError(nextError);
      if (nextError instanceof ApiError && nextError.code === "REVISION_CONFLICT") {
        setPendingSubmission(null);
        await reload().catch(setError);
      } else if (!(nextError instanceof ApiError)) {
        setPendingSubmission({ ...command, retryReason: "network" });
      } else {
        const retryReason = requestRetryReason(nextError);
        setPendingSubmission(retryReason ? { ...command, retryReason } : null);
      }
    } finally {
      submittingRef.current = false;
      setSubmitting(false);
    }
  };

  const retryAnalysis = async () => {
    if (!interview || submittingRef.current || controlSubmittingRef.current || controlBlocked || answerOperationActive) return;
    // 链尾恢复键以服务端视图为权威；operation/localStorage 只是兜底。
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
  const failedLifecycle = ["prepare_failed", "finish_failed"].includes(interview.status);
  const lifecycleText = interview.status === "active"
    ? acceptedAnswer ? "回答已保存" : "等待作答"
    : interviewStatusText[interview.status];
  const lifecycleTone = failedLifecycle
    ? "danger"
    : isFinishing
      ? "warn"
      : isCompleted || acceptedAnswer
        ? "success"
        : "primary";
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
  const controlFailed = controlOperation
    && ["failed", "interrupted"].includes(controlOperation.status)
    && controlOperation.error?.retryable !== false;

  return (
    <main className="page-container interview-page">
      <header className="compact-page-heading interview-heading">
        <div>
          <p className="eyebrow">模拟面试</p>
          <h1>{interviewRoleText(interview)}</h1>
          <InterviewProgress total={total} question={question} started={interviewStarted} />
        </div>
        <Tag className={`status-tag--${lifecycleTone}`}>
          {lifecycleText}
        </Tag>
      </header>
      <ErrorNotice error={error ?? operationError} onReload={() => void reload()} />
      <ErrorNotice error={controlError ?? controlOperationError} onReload={() => void reload()} />
      {interviewStarted && !isCompleted ? (
        <section className="interview-controls" aria-label="面试进程控制">
          <div className="interview-control-actions">
            <Button disabled={!serviceReady || !canSkip} onClick={() => setConfirmAction("skip")}>跳过本题</Button>
            <Button disabled={!serviceReady || !canEnd} onClick={() => setConfirmAction("end")}>提前结束面试</Button>
          </div>
          {confirmAction ? (
            <Alert type="warn" title={confirmAction === "end" ? "确认提前结束面试？" : "确认跳过当前题？"}>
              {confirmAction === "end"
                ? "提交后停止提问，未提交的回答不会保存；正在分析的已保存回答会等待处理安全结束，再生成现有结果报告。未测部分不会按零分计算，报告可能不完整。远端调用不保证立即取消或退费。"
                : question?.kind === "main"
                  ? "未提交的回答不会保存。跳过主问题后进入下一主问题，本题标记为已跳过而非零分；最后一题跳过后将整理报告。"
                  : "未提交的追问回答不会保存。跳过追问后进入下一主问题，保留当前主问题已有回答和观察。"}
              <div className="interview-control-confirm">
                <Button type="primary" loading={controlSubmitting} disabled={!serviceReady || (confirmAction === "skip" ? !canSkip : !canEnd)} onClick={submitControl}>
                  {confirmAction === "end" ? "确认结束并生成现有报告" : "确认跳过本题"}
                </Button>
                <Button disabled={controlSubmitting || Boolean(pendingControl)} onClick={() => setConfirmAction(null)}>继续作答，不提交操作</Button>
              </div>
            </Alert>
          ) : null}
          {pendingControl ? (
            <Alert type="warn" title="控制请求尚未取得明确受理结果">
              原操作、版本与请求标识已保留。请显式重试同一请求，不会重复跳题或生成第二个结束操作。
              <Button disabled={!serviceReady || controlSubmitting || submitting} loading={controlSubmitting} onClick={() => void executeControl(pendingControl)}>使用原请求重试控制操作</Button>
            </Alert>
          ) : null}
          {controlFailed && !pendingControl ? (
            <Alert type="danger" title="面试控制操作失败">
              失败状态与已保存回答保留；重试只恢复原控制操作，不重新提交回答。
              <Button disabled={!serviceReady || controlSubmitting || submitting || controlActive} onClick={retryControl}>重试{controlOperation.kind.endsWith(".end") ? "结束面试" : "跳过本题"}</Button>
            </Alert>
          ) : null}
          {interview.stop_requested ? <p className="muted">结束请求已受理，不再接受新回答。正在等待当前处理完成并整理报告。</p> : null}
          <OperationStatus operation={controlOperation} label={controlOperation?.kind.endsWith(".skip") ? "跳过本题" : "结束面试"} />
        </section>
      ) : null}
      {interview.status === "ready" ? (
        <Alert type="warn" title="面试尚未开始">
          请从“准备面试”页面调用开始接口；本页不会在缺失启动操作时生成第一题。
        </Alert>
      ) : null}
      {interview.status === "prepare_failed" ? (
        <Alert type="danger" title="面试准备失败">
          本场计划没有准备完成；页面不会生成题目或伪装为可开始状态。
        </Alert>
      ) : null}
      {interview.status === "finish_failed" ? (
        <Alert type="danger" title="报告整理失败">
          提问已经结束，但评分报告没有成功落库。请保留当前失败状态并按原操作恢复。
        </Alert>
      ) : null}
      {isFinishing ? (
        <section className="surface-card completion-card">
          <p className="eyebrow">报告整理</p>
          <h2>提问已结束，报告整理中</h2>
          <p>系统正在冻结本场评分结果；形成真实报告前不会显示完成入口。</p>
        </section>
      ) : null}
      {isCompleted ? (
        <section className="surface-card completion-card">
          <p className="eyebrow">面试完成</p>
          <h2>本场报告已经形成</h2>
          <p>可以继续查看逐题评分依据，并按需生成回答优化。</p>
          {interview.report_id ? (
            <Button type="primary" onClick={() => navigate(reportPath(interview.id))}>
              查看面试报告
            </Button>
          ) : null}
        </section>
      ) : null}

      {question ? (
        <div className="interview-grid">
          <div className="interview-main-column">
            <QuestionCard question={question} />
            <AnswerComposer
              question={question}
              acceptedAnswer={acceptedAnswer}
              submitting={submitting}
              serviceReady={serviceReady && !controlBlocked && !answerOperationActive}
              pendingRetryText={pendingSubmission?.retryReason ? pendingSubmission.answerText : null}
              retryReason={pendingSubmission?.retryReason ?? null}
              canRetryAnalysis={canRetryAnalysis}
              retryBudgetExhausted={retryBudgetExhausted}
              onSubmit={submitAnswer}
              onResetRetry={() => setPendingSubmission(null)}
              onRetryAnalysis={retryAnalysis}
            />
            {!operation?.kind.startsWith("interview.control.") ? <OperationStatus operation={operation} label="回答分析" /> : null}
          </div>
          {question.kind === "main" ? (
            <EvidencePanel interview={interview} question={question} />
          ) : (
            <DecisionPanel interview={interview} question={question} />
          )}
        </div>
      ) : null}
    </main>
  );
}
