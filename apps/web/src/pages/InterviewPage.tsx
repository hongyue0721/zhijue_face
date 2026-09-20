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
import { clearOperationId, loadOperationId, saveOperationId } from "../storage";

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

  const applyInterview = useCallback((next: InterviewView) => {
    setInterview(next);
    const recoverableOperation = next.active_operation_id ?? loadOperationId("interview", next.id);
    if (recoverableOperation) setOperationId(recoverableOperation);
  }, []);

  const reload = useCallback(async () => {
    applyInterview(await api.getInterview(interviewId));
  }, [applyInterview, interviewId]);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    api.getInterview(interviewId, controller.signal)
      .then(applyInterview)
      .catch((nextError) => {
        if (!(nextError instanceof DOMException && nextError.name === "AbortError")) setError(nextError);
      });
    return () => controller.abort();
  }, [applyInterview, interviewId]);

  const operationSettled = useCallback(async (settled: OperationView) => {
    submittingRef.current = false;
    setSubmitting(false);
    try {
      if (settled.status === "succeeded") {
        clearOperationId("interview", interviewId);
        setOperationId(null);
      }
      setInterview(await api.getInterview(interviewId));
    } catch (nextError) {
      setError(nextError);
    }
  }, [interviewId]);

  const { operation, error: operationError } = useOperationMonitor(operationId, operationSettled);

  const submitAnswer = async (answerText: string) => {
    const question = interview?.current_question;
    if (!interview || !question || submittingRef.current) return;
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
    if (!interview || submittingRef.current) return;
    const failedOperationId = operation?.id ?? loadOperationId("interview", interview.id);
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
  const canRetryAnalysis = acceptedAnswer?.evaluation_status === "failed"
    && Boolean(operationId ?? loadOperationId("interview", interview.id));

  return (
    <main className="page-container interview-page">
      <div className="interview-heading">
        <div>
          <p className="eyebrow">模拟面试</p>
          <h1>{interviewRoleText(interview)}</h1>
        </div>
        <Tag className={`status-tag--${lifecycleTone}`}>
          {lifecycleText}
        </Tag>
      </div>
      <InterviewProgress total={total} question={question} />
      <ErrorNotice error={error ?? operationError} onReload={() => void reload()} />
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
              serviceReady={serviceReady}
              pendingRetryText={pendingSubmission?.retryReason ? pendingSubmission.answerText : null}
              retryReason={pendingSubmission?.retryReason ?? null}
              canRetryAnalysis={canRetryAnalysis}
              onSubmit={submitAnswer}
              onResetRetry={() => setPendingSubmission(null)}
              onRetryAnalysis={retryAnalysis}
            />
            <OperationStatus operation={operation} label="回答分析" />
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
