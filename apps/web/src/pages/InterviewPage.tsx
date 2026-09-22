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
import { reportPath, startPath } from "../routing";
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
  const controlFailed = controlFailure;

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
                ? "结束后不再出题；输入框里还没提交的回答不会保存。正在分析的回答会等处理完成，再基于已有结果生成报告。没问到的题按“未考察”记录，不会算零分，报告可能不完整。已经发出的模型请求不保证能立刻停止。"
                : question?.kind === "main"
                  ? "输入框里还没提交的回答不会保存。跳过本题后会进入下一道主问题；本题记为“已跳过”，不算零分。跳过最后一题就开始整理报告。"
                  : "输入框里还没提交的回答不会保存。跳过追问后回到下一道主问题；本题主问题的已有回答和观察都会保留。"}
              <div className="interview-control-confirm">
                <Button type="primary" loading={controlSubmitting} disabled={!serviceReady || (confirmAction === "skip" ? !canSkip : !canEnd)} onClick={submitControl}>
                  {confirmAction === "end" ? "确认结束并生成现有报告" : "确认跳过本题"}
                </Button>
                <Button disabled={controlSubmitting || Boolean(pendingControl)} onClick={() => setConfirmAction(null)}>继续作答，取消本操作</Button>
              </div>
            </Alert>
          ) : null}
          {pendingControl ? (
            <Alert type="warn" title="上次操作未确认完成">
              这次“跳过 / 结束”操作已保留，点重试会续上原操作，不会重复跳题或生成第二份结束记录。
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
                    ? "这次跳过不能自动重试，你可以继续回答当前题。"
                    : "这次结束不能自动重试；请返回资料页保留当前记录，重新检查服务后再打开本场面试。"}</p>
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
          本场面试计划没有生成成功；页面不会凭空出题，也不会假装可以开始。请回到“面试准备”页面重新生成计划。
        </Alert>
      ) : null}
      {interview.status === "finish_failed" ? (
        <Alert type="danger" title="报告整理失败">
          提问已经结束，但评分报告没有保存成功。你的作答记录都还在，报告可沿上方“结束面试”的重试入口继续生成；重试不会重新提交回答。
        </Alert>
      ) : null}
      {isFinishing ? (
        <section className="surface-card completion-card">
          <p className="eyebrow">报告整理</p>
          <h2>提问已结束，报告整理中</h2>
          <p>正在汇总本场评分结果；报告真正生成前，这里不会提前显示“已完成”。</p>
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
