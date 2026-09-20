import { Alert, Button, Tag } from "@any-design/anyui/react";
import { useCallback, useEffect, useState } from "react";
import {
  api,
  newCommandKey,
  shouldPreserveWriteCommand,
  type InterviewView,
  type OperationView,
  type ReportView,
} from "../api";
import { ErrorNotice } from "../components/common/ErrorNotice";
import { OperationStatus } from "../components/common/OperationStatus";
import { useOperationMonitor } from "../hooks/useOperationMonitor";
import {
  criterionDisplayName,
  criterionFindingText,
  criterionLevelText,
  improvementsStatusText,
  reportLimitationText,
  rootAssessmentStatusText,
  scoreText,
} from "../presentation";
import { resumeDraftPath } from "../routing";
import {
  clearOperationId,
  clearRecoverableCommand,
  loadOperationId,
  loadRecoverableCommand,
  saveOperationId,
  saveRecoverableCommand,
  type RecoverableCommand,
} from "../storage";

type ImprovementsCommand = Extract<RecoverableCommand, { kind: "report-improvements" }>;
type ResumeCommand = Extract<RecoverableCommand, { kind: "report-resume" }>;
type ReportRetryCommand = Extract<RecoverableCommand, { kind: "report-retry" }>;


export function ReportPage({
  interviewId,
  serviceReady,
  navigate,
}: {
  interviewId: string;
  serviceReady: boolean;
  navigate: (path: string) => void;
}) {
  const [interview, setInterview] = useState<InterviewView | null>(null);
  const [report, setReport] = useState<ReportView | null>(null);
  const [operationId, setOperationId] = useState<string | null>(null);
  const [pendingImprovements, setPendingImprovements] = useState<ImprovementsCommand | null>(null);
  const [pendingResume, setPendingResume] = useState<ResumeCommand | null>(null);
  const [pendingRetry, setPendingRetry] = useState<ReportRetryCommand | null>(null);
  const [selectedRootId, setSelectedRootId] = useState<string | null>(null);
  const [activeReportTab, setActiveReportTab] = useState<"assessment" | "improvement">(
    "assessment",
  );
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const applyReport = useCallback((next: ReportView) => {
    setReport(next);
    setSelectedRootId((current) => {
      if (current && next.root_assessments.some((item) => item.root_question_id === current)) {
        return current;
      }
      return next.root_assessments[0]?.root_question_id ?? null;
    });
    const storedImprovements = loadRecoverableCommand("report-improvements", next.id);
    const storedResume = loadRecoverableCommand("report-resume", next.id);
    const storedRetry = loadRecoverableCommand("report-retry", next.id);
    setPendingImprovements(
      storedImprovements?.kind === "report-improvements" ? storedImprovements : null,
    );
    setPendingResume(storedResume?.kind === "report-resume" ? storedResume : null);
    setPendingRetry(storedRetry?.kind === "report-retry" ? storedRetry : null);

    const storedOperationId = loadOperationId("report", next.id);
    if (next.improvements_status === "ready") {
      clearOperationId("report", next.id);
      clearRecoverableCommand("report-improvements", next.id);
      clearRecoverableCommand("report-retry", next.id);
      setPendingImprovements(null);
      setPendingRetry(null);
      setOperationId(null);
      return;
    }
    if (next.improvements_status === "generating" && next.active_operation_id) {
      saveOperationId("report", next.id, next.active_operation_id);
      clearRecoverableCommand("report-improvements", next.id);
      clearRecoverableCommand("report-retry", next.id);
      setPendingImprovements(null);
      setPendingRetry(null);
      setOperationId(next.active_operation_id);
      return;
    }
    setOperationId(storedOperationId);
  }, []);

  const reload = useCallback(async () => {
    const [nextInterview, nextReport] = await Promise.all([
      api.getInterview(interviewId),
      api.getReport(interviewId),
    ]);
    setInterview(nextInterview);
    applyReport(nextReport);
  }, [applyReport, interviewId]);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    Promise.all([
      api.getInterview(interviewId, controller.signal),
      api.getReport(interviewId, controller.signal),
    ])
      .then(([nextInterview, nextReport]) => {
        setInterview(nextInterview);
        applyReport(nextReport);
      })
      .catch((nextError) => {
        if (!(nextError instanceof DOMException && nextError.name === "AbortError")) {
          setError(nextError);
        }
      });
    return () => controller.abort();
  }, [applyReport, interviewId]);

  const operationSettled = useCallback(
    async (settled: OperationView) => {
      if (settled.status === "succeeded" && report) {
        clearOperationId("report", report.id);
        setOperationId(null);
      }
      try {
        applyReport(await api.getReport(interviewId));
      } catch (nextError) {
        setError(nextError);
      }
    },
    [applyReport, interviewId, report],
  );
  const { operation, error: operationError } = useOperationMonitor(operationId, operationSettled);

  const generateImprovements = async () => {
    if (!report || busy) return;
    const command: ImprovementsCommand = pendingImprovements ?? {
      kind: "report-improvements",
      idempotencyKey: newCommandKey("coaching"),
      input: { expected_revision: report.revision },
    };
    saveRecoverableCommand("report-improvements", report.id, command);
    setPendingImprovements(command);
    setBusy(true);
    setError(null);
    let responseObserved = false;
    try {
      const accepted = await api.generateReportImprovements(
        interviewId,
        command.input.expected_revision,
        command.idempotencyKey,
      );
      responseObserved = true;
      clearRecoverableCommand("report-improvements", report.id);
      setPendingImprovements(null);
      saveOperationId("report", report.id, accepted.operation_id);
      setOperationId(accepted.operation_id);
      applyReport(await api.getReport(interviewId));
    } catch (nextError) {
      if (!responseObserved && !shouldPreserveWriteCommand(nextError)) {
        clearRecoverableCommand("report-improvements", report.id);
        setPendingImprovements(null);
      }
      setError(nextError);
    } finally {
      setBusy(false);
    }
  };

  const retryImprovements = async () => {
    if (!report || !operationId || busy) return;
    const command: ReportRetryCommand = pendingRetry ?? {
      kind: "report-retry",
      idempotencyKey: newCommandKey("coaching-retry"),
      input: {
        operation_id: operationId,
        expected_revision: report.revision,
      },
    };
    saveRecoverableCommand("report-retry", report.id, command);
    setPendingRetry(command);
    setBusy(true);
    setError(null);
    let responseObserved = false;
    try {
      const accepted = await api.retryOperation(
        command.input.operation_id,
        command.input.expected_revision,
        command.idempotencyKey,
      );
      responseObserved = true;
      clearRecoverableCommand("report-retry", report.id);
      setPendingRetry(null);
      saveOperationId("report", report.id, accepted.operation_id);
      setOperationId(accepted.operation_id);
      applyReport(await api.getReport(interviewId));
    } catch (nextError) {
      if (!responseObserved && !shouldPreserveWriteCommand(nextError)) {
        clearRecoverableCommand("report-retry", report.id);
        setPendingRetry(null);
      }
      setError(nextError);
    } finally {
      setBusy(false);
    }
  };

  const createResumeDraft = async () => {
    if (!report || !interview || busy) return;
    setBusy(true);
    setError(null);
    let command = pendingResume;
    let responseObserved = false;
    try {
      if (!command) {
        const profile = await api.getProfile(interview.profile_id);
        command = {
          kind: "report-resume",
          idempotencyKey: newCommandKey("resume"),
          input: {
            profile_id: interview.profile_id,
            expected_revision: profile.revision,
            profile_snapshot_id: interview.profile_snapshot_id,
            interview_id: interview.id,
          },
        };
        saveRecoverableCommand("report-resume", report.id, command);
        setPendingResume(command);
      }
      const accepted = await api.createResumeDraft(
        command.input.profile_id,
        {
          expected_revision: command.input.expected_revision,
          profile_snapshot_id: command.input.profile_snapshot_id,
          interview_id: command.input.interview_id,
        },
        command.idempotencyKey,
      );
      responseObserved = true;
      clearRecoverableCommand("report-resume", report.id);
      setPendingResume(null);
      saveOperationId("resume", accepted.resource_id, accepted.operation_id);
      navigate(resumeDraftPath(accepted.resource_id));
    } catch (nextError) {
      if (command && !responseObserved && !shouldPreserveWriteCommand(nextError)) {
        clearRecoverableCommand("report-resume", report.id);
        setPendingResume(null);
      }
      setError(nextError);
    } finally {
      setBusy(false);
    }
  };

  if (!report || !interview) {
    return (
      <main className="page-container narrow-page">
        <ErrorNotice error={error} onReload={() => void reload()} />
        {!error ? <p className="loading-row">正在读取评分报告</p> : null}
      </main>
    );
  }

  const canRetry = report.improvements_status === "failed"
    && Boolean(operationId)
    && Boolean(operation?.error?.retryable);
  const selectedIndex = Math.max(
    0,
    report.root_assessments.findIndex((item) => item.root_question_id === selectedRootId),
  );
  const selectedAssessment = report.root_assessments[selectedIndex] ?? null;
  const selectedImprovement = selectedAssessment
    ? report.improved_answers.find(
        (item) => item.root_question_id === selectedAssessment.root_question_id,
      ) ?? null
    : null;
  const limitations = report.limitations.map(reportLimitationText);

  return (
    <main className="page-container report-page">
      <header className="compact-page-heading report-heading">
        <div>
          <p className="eyebrow">面试报告</p>
          <h1>本场表现与事实依据</h1>
          <p>
            已回答 {report.coverage.answered_root_count}/{report.coverage.planned_root_count}
            {" · "}可评分 {report.coverage.scored_root_count}/{report.coverage.planned_root_count}
            {limitations[0] ? ` · ${limitations[0]}` : ""}
          </p>
        </div>
        <div className="score-summary" aria-label="本场总分">
          <strong>{scoreText(report.overall_score, "未形成总分")}</strong>
          <span>{report.completion === "complete" ? "完整场次" : "未完整场次"}</span>
        </div>
      </header>

      <ErrorNotice error={error ?? operationError} onReload={() => void reload()} />
      <OperationStatus operation={operation} label="回答优化" />

      <section className="report-workspace" aria-label="逐题报告">
        <aside className="surface-card question-rail">
          <div className="question-rail-heading">
            <span>逐题查看</span>
            <Tag>{report.coverage.scored_root_count} 题可评分</Tag>
          </div>
          <div className="question-rail-list" role="list">
            {report.root_assessments.map((assessment, index) => (
              <button
                className={`question-rail-item ${
                  assessment.root_question_id === selectedAssessment?.root_question_id
                    ? "active"
                    : ""
                }`}
                key={assessment.root_question_id}
                type="button"
                aria-pressed={
                  assessment.root_question_id === selectedAssessment?.root_question_id
                }
                onClick={() => setSelectedRootId(assessment.root_question_id)}
              >
                <span>问题 {index + 1}</span>
                <small>
                  {assessment.score === null
                    ? rootAssessmentStatusText[assessment.status]
                    : scoreText(assessment.score, "本题未评分")}
                </small>
              </button>
            ))}
          </div>
        </aside>

        <section className="surface-card report-detail">
          <div className="segmented-tabs" role="tablist" aria-label="报告内容">
            <button
              type="button"
              role="tab"
              aria-selected={activeReportTab === "assessment"}
              onClick={() => setActiveReportTab("assessment")}
            >
              评分依据
            </button>
            <button
              type="button"
              role="tab"
              aria-selected={activeReportTab === "improvement"}
              onClick={() => setActiveReportTab("improvement")}
            >
              回答优化
            </button>
          </div>

          {activeReportTab === "assessment" && selectedAssessment ? (
            <div className="report-tab-panel" role="tabpanel">
              <div className="report-detail-heading">
                <div>
                  <p className="eyebrow">问题 {selectedIndex + 1}</p>
                  <h2>{rootAssessmentStatusText[selectedAssessment.status]}</h2>
                </div>
                <div className="assessment-score">
                  <strong>{scoreText(selectedAssessment.score, "未评分")}</strong>
                  <span>覆盖 {Math.round(selectedAssessment.coverage * 100)}%</span>
                </div>
              </div>
              <div className="criterion-list">
                {selectedAssessment.criterion_results.map((criterion, criterionIndex) => (
                  <article className="criterion-result" key={criterion.criterion_id}>
                    <div className="criterion-summary">
                      <strong>{criterionDisplayName(criterion.kind, criterionIndex)}</strong>
                      <span>
                        {criterionFindingText[criterion.finding]}
                        {" · "}{criterionLevelText(criterion.level)}
                      </span>
                    </div>
                    {(criterion.answer_quotes.length
                      || criterion.explanations.length
                      || criterion.knowledge_refs.length) ? (
                      <details className="compact-details">
                        <summary>查看来源与技术详情</summary>
                        {criterion.answer_quotes.length ? (
                          <div>
                            <h3>回答引用</h3>
                            {criterion.answer_quotes.map((quote) => (
                              <blockquote key={`${quote.answer_id}-${quote.exact_quote}`}>
                                {quote.exact_quote}
                              </blockquote>
                            ))}
                          </div>
                        ) : null}
                        {criterion.explanations.length ? (
                          <div>
                            <h3>评价说明</h3>
                            <ul>
                              {criterion.explanations.map((text, index) => (
                                <li key={`${criterion.criterion_id}-explanation-${index}`}>
                                  {text}
                                </li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                        {criterion.knowledge_refs.length ? (
                          <div>
                            <h3>技术资料引用</h3>
                            <ul>
                              {criterion.knowledge_refs.map((reference, index) => (
                                <li key={reference}>资料 {index + 1}：{reference}</li>
                              ))}
                            </ul>
                          </div>
                        ) : null}
                      </details>
                    ) : null}
                  </article>
                ))}
              </div>
            </div>
          ) : null}

          {activeReportTab === "improvement" ? (
            <div className="report-tab-panel" role="tabpanel">
              <div className="report-detail-heading">
                <div>
                  <p className="eyebrow">问题 {selectedIndex + 1}</p>
                  <h2>基于原回答的表达优化</h2>
                </div>
                <Tag>{improvementsStatusText[report.improvements_status]}</Tag>
              </div>
              <p className="panel-intro">
                这是整场报告的一次生成动作；切换问题或页签只读取已返回内容。
              </p>
              {report.improvements_status === "not_requested" || pendingImprovements ? (
                <Button
                  type="primary"
                  loading={busy}
                  disabled={!serviceReady || busy}
                  onClick={() => void generateImprovements()}
                >
                  {pendingImprovements ? "使用原请求重试" : "生成本场回答优化"}
                </Button>
              ) : null}
              {canRetry ? (
                <Button
                  type="primary"
                  loading={busy}
                  disabled={!serviceReady || busy}
                  onClick={() => void retryImprovements()}
                >
                  {pendingRetry ? "使用原重试请求" : "重试回答优化"}
                </Button>
              ) : null}
              {report.improvements_status === "failed" && !canRetry ? (
                <Alert type="danger" title="回答优化未完成">
                  请刷新操作状态后再决定是否重试。
                </Alert>
              ) : null}
              {selectedImprovement ? (
                <div className="selected-improvement">
                  <div className="answer-comparison">
                    <div>
                      <h3>原回答</h3>
                      {selectedImprovement.original_answers.map((answer) => (
                        <p key={answer.answer_id}>{answer.raw_text}</p>
                      ))}
                    </div>
                    <div>
                      <h3>优化后</h3>
                      <p>{selectedImprovement.rewritten_answer}</p>
                    </div>
                  </div>
                  {selectedImprovement.changes.length ? (
                    <p className="change-note">{selectedImprovement.changes.join("；")}</p>
                  ) : null}
                  {(selectedImprovement.missing_facts.length
                    || selectedImprovement.cautions.length) ? (
                    <details className="compact-details">
                      <summary>
                        待补充 {selectedImprovement.missing_facts.length} 项
                        {" · "}注意 {selectedImprovement.cautions.length} 项
                      </summary>
                      {selectedImprovement.missing_facts.length ? (
                        <div>
                          <h3>仍需本人补充</h3>
                          <ul>
                            {selectedImprovement.missing_facts.map((fact) => (
                              <li key={fact.prompt}>{fact.prompt}：{fact.reason}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                      {selectedImprovement.cautions.length ? (
                        <div>
                          <h3>注意</h3>
                          <ul>
                            {selectedImprovement.cautions.map((caution) => (
                              <li key={caution}>{caution}</li>
                            ))}
                          </ul>
                        </div>
                      ) : null}
                    </details>
                  ) : null}
                </div>
              ) : report.improvements_status === "ready" ? (
                <p className="empty-state">本题没有返回可展示的回答优化。</p>
              ) : null}
            </div>
          ) : null}
        </section>
      </section>

      <section className="surface-card report-next-step">
        <div className="report-limitations">
          <strong>{limitations[0] ?? "本场报告未记录额外限制"}</strong>
          {limitations.length > 1 ? (
            <details className="compact-details">
              <summary>查看全部 {limitations.length} 项限制</summary>
              <ul>{limitations.map((item) => <li key={item}>{item}</li>)}</ul>
            </details>
          ) : null}
        </div>
        <Button
          type="primary"
          loading={busy}
          disabled={!serviceReady || busy}
          onClick={() => void createResumeDraft()}
        >
          {pendingResume ? "使用原请求创建草稿" : "生成简历草稿"}
        </Button>
      </section>
    </main>
  );
}
