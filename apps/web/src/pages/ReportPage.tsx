import { Alert, Button, Tag } from "@any-design/anyui/react";
import { useCallback, useEffect, useRef, useState } from "react";
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
import { preparePath, resumeDraftPath, startPath } from "../routing";
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
function ImprovedAnswerCopy({ text }: { text: string }) {
  const [copyState, setCopyState] = useState<"idle" | "copying" | "success" | "failure">("idle");
  const [message, setMessage] = useState("");

  const copy = async () => {
    setCopyState("copying");
    setMessage("");
    try {
      if (!navigator.clipboard?.writeText) {
        setCopyState("failure");
        setMessage("当前浏览器无法使用剪贴板，请选中优化后的正文手动复制。");
        return;
      }
      await navigator.clipboard.writeText(text);
      setCopyState("success");
      setMessage("已复制优化后的回答。");
    } catch {
      setCopyState("failure");
      setMessage("复制失败，可能未获剪贴板权限。请重试或选中正文手动复制。");
    }
  };

  return (
    <div className="report-copy-action">
      <Button
        type="secondary"
        size="small"
        disabled={!text.trim() || copyState === "copying"}
        onClick={() => void copy()}
      >
        {copyState === "copying" ? "正在复制" : "复制优化后的回答"}
      </Button>
      <p role="status" aria-live="polite" aria-atomic="true">{message}</p>
    </div>
  );
}


export function ReportPage({
  interviewId,
  serviceReady,
  contentGenerationReady,
  navigate,
}: {
  interviewId: string;
  serviceReady: boolean;
  contentGenerationReady: boolean;
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
  const [narrowReport, setNarrowReport] = useState(
    () => window.matchMedia("(max-width: 820px)").matches,
  );
  const [overviewExpanded, setOverviewExpanded] = useState(false);
  useEffect(() => {
    const media = window.matchMedia("(max-width: 820px)");
    const update = () => setNarrowReport(media.matches);
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const assessmentTabRef = useRef<HTMLButtonElement>(null);
  const improvementTabRef = useRef<HTMLButtonElement>(null);
  const reportRef = useRef<ReportView | null>(null);
  const pageGeneration = useRef(0);

  const applyReport = useCallback((next: ReportView) => {
    if (next.interview_id !== interviewId || (reportRef.current?.id === next.id && reportRef.current.revision > next.revision)) return;
    reportRef.current = next;
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
    // failed 时服务端保留失败链尾操作作为恢复键（api.md §6）：跨浏览器、
    // 清缓存后仍能 GET 该 Operation 并走 /retry，不依赖 localStorage。
    if (next.improvements_status === "failed" && next.active_operation_id) {
      saveOperationId("report", next.id, next.active_operation_id);
      setOperationId(next.active_operation_id);
      return;
    }
    setOperationId(storedOperationId);
  }, [interviewId]);

  const reload = useCallback(async () => {
    const generation = pageGeneration.current;
    const [nextInterview, nextReport] = await Promise.all([
      api.getInterview(interviewId),
      api.getReport(interviewId),
    ]);
    if (generation !== pageGeneration.current) return;
    setInterview(nextInterview);
    applyReport(nextReport);
  }, [applyReport, interviewId]);

  useEffect(() => {
    const controller = new AbortController();
    pageGeneration.current += 1;
    reportRef.current = null;
    setReport(null);
    setInterview(null);
    setOperationId(null);
    setBusy(false);
    setError(null);
    Promise.all([
      api.getInterview(interviewId, controller.signal),
      api.getReport(interviewId, controller.signal),
    ])
      .then(([nextInterview, nextReport]) => {
        if (controller.signal.aborted) return;
        setInterview(nextInterview);
        applyReport(nextReport);
      })
      .catch((nextError) => {
        if (!controller.signal.aborted && !(nextError instanceof DOMException && nextError.name === "AbortError")) {
          setError(nextError);
        }
      });
    return () => {
      pageGeneration.current += 1;
      controller.abort();
    };
  }, [applyReport, interviewId]);

  const operationSettled = useCallback(
    async (_settled: OperationView, signal: AbortSignal) => {
      try {
        const next = await api.getReport(interviewId, signal);
        if (!signal.aborted) applyReport(next);
      } catch (nextError) {
        if (!signal.aborted) setError(nextError);
      }
    },
    [applyReport, interviewId],
  );
  const operationUnavailable = useCallback((nextError: unknown) => {
    if (report) clearOperationId("report", report.id);
    setOperationId(null);
    setError(nextError);
  }, [report]);
  const operationSuccessor = useCallback((nextId: string) => {
    if (!report) return;
    saveOperationId("report", report.id, nextId);
    clearRecoverableCommand("report-retry", report.id);
    clearRecoverableCommand("report-improvements", report.id);
    setPendingImprovements(null);
    setPendingRetry(null);
    setOperationId(nextId);
  }, [report]);
  const { operation, error: operationError } = useOperationMonitor(
    operationId,
    operationSettled,
    operationUnavailable,
    operationSuccessor,
  );

  const generateImprovements = async () => {
    if (!report || busy || !contentGenerationReady) return;
    const generation = pageGeneration.current;
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
      if (generation !== pageGeneration.current) return;
      responseObserved = true;
      clearRecoverableCommand("report-improvements", report.id);
      setPendingImprovements(null);
      saveOperationId("report", report.id, accepted.operation_id);
      setOperationId(accepted.operation_id);
      const next = await api.getReport(interviewId);
      if (generation === pageGeneration.current) applyReport(next);
    } catch (nextError) {
      if (generation !== pageGeneration.current) return;
      if (!responseObserved && !shouldPreserveWriteCommand(nextError)) {
        clearRecoverableCommand("report-improvements", report.id);
        setPendingImprovements(null);
      }
      setError(nextError);
    } finally {
      if (generation === pageGeneration.current) setBusy(false);
    }
  };

  const retryImprovements = async () => {
    if (!report || !operationId || busy || !contentGenerationReady) return;
    const generation = pageGeneration.current;
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
      if (generation !== pageGeneration.current) return;
      responseObserved = true;
      clearRecoverableCommand("report-retry", report.id);
      setPendingRetry(null);
      saveOperationId("report", report.id, accepted.operation_id);
      setOperationId(accepted.operation_id);
      const next = await api.getReport(interviewId);
      if (generation === pageGeneration.current) applyReport(next);
    } catch (nextError) {
      if (generation !== pageGeneration.current) return;
      if (!responseObserved && !shouldPreserveWriteCommand(nextError)) {
        clearRecoverableCommand("report-retry", report.id);
        setPendingRetry(null);
      }
      setError(nextError);
    } finally {
      if (generation === pageGeneration.current) setBusy(false);
    }
  };

  const createResumeDraft = async () => {
    if (!report || !interview || busy || !contentGenerationReady) return;
    const generation = pageGeneration.current;
    setBusy(true);
    setError(null);
    let command = pendingResume;
    let responseObserved = false;
    try {
      if (!command) {
        const profile = await api.getProfile(interview.profile_id);
        if (generation !== pageGeneration.current) return;
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
      if (generation !== pageGeneration.current) return;
      responseObserved = true;
      clearRecoverableCommand("report-resume", report.id);
      setPendingResume(null);
      saveOperationId("resume", accepted.resource_id, accepted.operation_id);
      navigate(resumeDraftPath(accepted.resource_id));
    } catch (nextError) {
      if (generation !== pageGeneration.current) return;
      if (command && !responseObserved && !shouldPreserveWriteCommand(nextError)) {
        clearRecoverableCommand("report-resume", report.id);
        setPendingResume(null);
      }
      setError(nextError);
    } finally {
      if (generation === pageGeneration.current) setBusy(false);
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

  const operationLoading = Boolean(operationId && !operation && !operationError);
  const generationActive = operationLoading || operation?.status === "queued" || operation?.status === "running";
  const canRetry = report.improvements_status === "failed"
    && operation?.id === operationId
    && (operation?.status === "failed" || operation?.status === "interrupted")
    && !operation.next_operation_id
    && Boolean(operation.error?.retryable);
  const failureDetail = report.improvements_status === "failed"
    ? operationLoading
      ? "正在读取这次处理的详细状态。"
      : generationActive
        ? null
        : operation?.error?.retryable === false
          ? "这次生成无法继续重试（次数已用完或需要处理失败原因）。已有报告和原回答不受影响。"
          : operationError
            ? "失败详情暂时无法读取；页面仍会继续查询处理状态，也可手动刷新报告状态。"
            : !operationId
              ? "服务端没有提供可恢复的操作记录；已有报告和原回答不受影响。"
              : null
    : null;
  const selectReportTab = (
    tab: "assessment" | "improvement",
    moveFocus = false,
  ) => {
    setActiveReportTab(tab);
    if (moveFocus) {
      requestAnimationFrame(() =>
        (tab === "assessment" ? assessmentTabRef : improvementTabRef).current?.focus()
      );
    }
  };
  const handleReportTabKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" || event.key === "ArrowLeft"
      ? "assessment"
      : "improvement";
    selectReportTab(next, true);
  };
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
  const scoredAssessments = report.root_assessments.filter(
    (assessment) => assessment.status === "scored" && assessment.score !== null,
  );
  const lowestScored = scoredAssessments.reduce<ReportView["root_assessments"][number] | null>(
    (lowest, assessment) => !lowest || assessment.score! < lowest.score! ? assessment : lowest,
    null,
  );
  const hasScoreDifference = lowestScored !== null && scoredAssessments.some(
    (assessment) => assessment.score !== lowestScored.score,
  );
  const unscoredAssessment = report.root_assessments.find(
    (assessment) => assessment.status !== "scored",
  );
  const missingFactsAssessment = report.root_assessments.find((assessment) =>
    report.improved_answers.some(
      (answer) => answer.root_question_id === assessment.root_question_id && answer.missing_facts.length > 0,
    ),
  );
  const missingFactsAnswer = missingFactsAssessment
    ? report.improved_answers.find((answer) => answer.root_question_id === missingFactsAssessment.root_question_id)
    : null;
  const reviewQuestion = (rootId: string, tab: "assessment" | "improvement") => {
    setSelectedRootId(rootId);
    selectReportTab(tab, true);
  };
  const questionNumber = (rootId: string) =>
    report.root_assessments.findIndex((assessment) => assessment.root_question_id === rootId) + 1;

  return (
    <main className="page-container report-page">
      <nav className="page-backlinks" aria-label="报告返回导航">
        <Button type="secondary" size="small" onClick={() => navigate(startPath(interview.profile_id))}>
          返回资料
        </Button>
        <Button type="secondary" size="small" onClick={() => navigate(preparePath(interview.profile_id))}>
          重新准备面试
        </Button>
      </nav>
      <header className="compact-page-heading report-heading">
        <div>

          <h1>回看这一场，找到下一步</h1>
          <p>
            已回答 {report.coverage.answered_root_count}/{report.coverage.planned_root_count}
            {" · "}可评分 {report.coverage.scored_root_count}/{report.coverage.planned_root_count}
          </p>
        </div>
        <div className="score-summary" aria-label="本场总分">
          <strong>{scoreText(report.overall_score, "未形成总分")}</strong>
        </div>
      </header>

      <ErrorNotice error={error ?? operationError} onReload={() => void reload()} />
      {activeReportTab !== "improvement" ? <OperationStatus operation={operation} label="回答优化" /> : null}
      <details className="report-action-overview surface-card" open={!narrowReport || overviewExpanded}
        onToggle={(event) => { if (narrowReport) setOverviewExpanded(event.currentTarget.open); }}>
        <summary id="report-overview-title" tabIndex={narrowReport ? 0 : -1}>下一步，先看这里</summary>
        <p className="report-overview-note">仅根据已有评分、题目状态和回答优化中的待补充项整理，不是新的评价。</p>
        <div className="report-overview-actions">
          <article>
            <h3>{hasScoreDifference ? "先核对较低分题的依据" : "按原题顺序回看"}</h3>
            <p>
              {hasScoreDifference && lowestScored
                ? `第 ${questionNumber(lowestScored.root_question_id)} 题为本场已评分题中的最低分（${scoreText(lowestScored.score, "未评分")}）。先对照原回答与评分依据。`
                : scoredAssessments.length === 0
                  ? "本场暂无可评分题，不能据此判断强弱；可先查看题目状态和原回答。"
                  : scoredAssessments.length === 1
                    ? "本场只有一道已评分题，不能比较题目强弱；可先核对这道题的评分依据。"
                    : "本场已评分题得分相同，不据此区分强弱；可按原题顺序核对评分依据。"}
            </p>
            {lowestScored ? (
              <Button type="secondary" onClick={() => reviewQuestion(lowestScored.root_question_id, "assessment")}>
                查看第 {questionNumber(lowestScored.root_question_id)} 题评分依据
              </Button>
            ) : null}
          </article>
          {unscoredAssessment ? (
            <article>
              <h3>查看未评分原因</h3>
              <p>第 {questionNumber(unscoredAssessment.root_question_id)} 题：{rootAssessmentStatusText[unscoredAssessment.status]}。未评分不等于零分。</p>
              <Button type="secondary" onClick={() => reviewQuestion(unscoredAssessment.root_question_id, "assessment")}>
                查看第 {questionNumber(unscoredAssessment.root_question_id)} 题状态与回答
              </Button>
            </article>
          ) : null}
          {missingFactsAssessment && missingFactsAnswer ? (
            <article>
              <h3>补充真实细节，再练一次</h3>
              <p>第 {questionNumber(missingFactsAssessment.root_question_id)} 题有 {missingFactsAnswer.missing_facts.length} 项待本人补充：{missingFactsAnswer.missing_facts[0].prompt}</p>
              <Button type="secondary" onClick={() => reviewQuestion(missingFactsAssessment.root_question_id, "improvement")}>
                查看第 {questionNumber(missingFactsAssessment.root_question_id)} 题待补充项
              </Button>
            </article>
          ) : null}
        </div>
      </details>

      <section className="report-workspace" aria-label="逐题报告">
        <aside className="question-rail report-question-navigation" aria-label="题目导航">
          <label className="report-question-chooser">
            逐题查看
            <select value={selectedAssessment?.root_question_id ?? ""}
              onChange={(event) => setSelectedRootId(event.target.value)}>
              {report.root_assessments.map((assessment, index) => (
                <option key={assessment.root_question_id} value={assessment.root_question_id}>
                  问题 {index + 1} · {assessment.score === null
                    ? rootAssessmentStatusText[assessment.status]
                    : scoreText(assessment.score, "本题未评分")} · {assessment.question_text}
                </option>
              ))}
            </select>
          </label>
          <div className="question-rail-heading">
            <span>逐题查看</span>
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
                <span className="question-rail-title" title={assessment.question_text}>
                  {assessment.question_text}
                </span>
                <span className="question-rail-score">
                  {assessment.score === null
                    ? rootAssessmentStatusText[assessment.status]
                    : scoreText(assessment.score, "本题未评分")}
                </span>
              </button>
            ))}
          </div>
        </aside>

        <section className="report-detail report-reading-pane">
          {selectedAssessment ? (
            <section className="report-question-context" aria-label="原题与回答">
              <p className="eyebrow">第 {selectedIndex + 1} 题</p>
              <h2>{selectedAssessment.question_text}</h2>
              {activeReportTab === "assessment" ? <details className="report-original-answers" open key={selectedAssessment.root_question_id}>
                <summary>你的原回答（{selectedAssessment.answers.length} 次）</summary>
                {selectedAssessment.answers.length ? selectedAssessment.answers.map((answer) => (
                  <article key={answer.answer_id}>
                    {answer.question_kind !== "main" ? (
                      <h3>{answer.question_kind === "probe" ? "追问" : "澄清"}：{answer.question_text}</h3>
                    ) : null}
                    <p>{answer.raw_text}</p>
                  </article>
                )) : <p>本题没有提交回答，未回答不代表不会。</p>}
              </details> : null}
            </section>
          ) : null}
          <div
            className="segmented-tabs"
            role="tablist"
            aria-label="报告内容"
            onKeyDown={handleReportTabKeyDown}
          >
            <button
              ref={assessmentTabRef}
              id="report-tab-assessment"
              type="button"
              role="tab"
              aria-selected={activeReportTab === "assessment"}
              aria-controls="report-panel-assessment"
              tabIndex={activeReportTab === "assessment" ? 0 : -1}
              onClick={() => selectReportTab("assessment")}
            >
              评分依据
            </button>
            <button
              ref={improvementTabRef}
              id="report-tab-improvement"
              type="button"
              role="tab"
              aria-selected={activeReportTab === "improvement"}
              aria-controls="report-panel-improvement"
              tabIndex={activeReportTab === "improvement" ? 0 : -1}
              onClick={() => selectReportTab("improvement")}
            >
              回答优化
            </button>
          </div>

          {activeReportTab === "assessment" && selectedAssessment ? (
            <div
              id="report-panel-assessment"
              className="report-tab-panel"
              role="tabpanel"
              aria-labelledby="report-tab-assessment"
              tabIndex={0}
            >
              <div className="report-detail-heading">
                <div>
                  <h2>评分依据</h2>
                  <span className="assessment-state">{rootAssessmentStatusText[selectedAssessment.status]}</span>
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
                    {criterion.explanations.length ? (
                      <ul className="criterion-explanations">
                        {criterion.explanations.map((text, index) => (
                          <li key={`${criterion.criterion_id}-explanation-${index}`}>{text}</li>
                        ))}
                      </ul>
                    ) : null}
                    {(criterion.answer_quotes.length || criterion.knowledge_refs.length) ? (
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
            <div
              id="report-panel-improvement"
              className="report-tab-panel"
              role="tabpanel"
              aria-labelledby="report-tab-improvement"
              tabIndex={0}
            >
              <div className="report-detail-heading">
                <div>
                  <h2>{selectedImprovement ? "让表达更清楚" : "整理本场回答"}</h2>
                </div>
                <Tag>{improvementsStatusText[generationActive ? "generating" : report.improvements_status]}</Tag>
              </div>
              <OperationStatus operation={operation} label="回答优化" />
              {serviceReady && !contentGenerationReady && report.improvements_status !== "ready" ? (
                <p role="status">当前服务未配置内容生成，暂不能生成或重试回答优化；已有评分和报告仍可查看。</p>
              ) : null}
              {!generationActive && report.improvements_status !== "ready" && (report.improvements_status === "not_requested" || pendingImprovements) ? (
                <Button
                  type="primary"
                  loading={busy}
                  disabled={!contentGenerationReady || busy}
                  onClick={() => void generateImprovements()}
                >
                  {pendingImprovements ? "继续未完成的生成" : "生成本场回答优化"}
                </Button>
              ) : null}
              {canRetry ? (
                <Button
                  type="primary"
                  loading={busy}
                  disabled={!contentGenerationReady || busy}
                  onClick={() => void retryImprovements()}
                >
                  {pendingRetry ? "继续未完成的生成" : "重试回答优化"}
                </Button>
              ) : null}
              {failureDetail && !canRetry ? (
                <Alert type={operationLoading ? "info" : "danger"} title={operationLoading ? "正在恢复回答优化状态" : "回答优化未完成"}>
                  {failureDetail}
                </Alert>
              ) : null}
              {selectedImprovement ? (
                <div className="selected-improvement">
                  <div className="answer-comparison answer-reading-comparison">
                    <div>
                      <h3>原回答</h3>
                      {selectedImprovement.original_answers.map((answer) => (
                        <p key={answer.answer_id}>{answer.raw_text}</p>
                      ))}
                    </div>
                    <div>
                      <h3>优化后</h3>
                      <p>{selectedImprovement.rewritten_answer}</p>
                      <ImprovedAnswerCopy key={selectedImprovement.root_question_id} text={selectedImprovement.rewritten_answer} />
                    </div>
                  </div>
                  {selectedImprovement.changes.length ? (
                    <p className="change-note">{selectedImprovement.changes.join("；")}</p>
                  ) : null}
                  {(selectedImprovement.missing_facts.length
                    || selectedImprovement.cautions.length) ? (
                    <details className="compact-details" open key={selectedImprovement.root_question_id}>
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
                <p className="empty-state">这道题没有找到可以改写的回答内容。</p>
              ) : null}
            </div>
          ) : null}
        </section>
      </section>

      <section className="report-next-step report-footer">
        <div className="report-limitations">
          {limitations.length ? (
            <details className="compact-details">
              <summary>报告说明（{limitations.length}）</summary>
              <ul>{limitations.map((item) => <li key={item}>{item}</li>)}</ul>
            </details>
          ) : null}
          {/* 本场包摘要来自 Interview 冻结字段，不受“当前默认包”影响。 */}
          <p className="interview-pack-line">
            {interview.knowledge_pack?.binding === "frozen"
              ? `岗位知识包：${interview.knowledge_pack.name} v${interview.knowledge_pack.version}（本场冻结）`
              : interview.knowledge_pack?.binding === "frozen_unavailable"
                ? "岗位知识包：本场冻结的包当前不可用（内容缺失或损坏）。"
                : "岗位知识包：历史绑定未确定，报告不追认版本。"}
          </p>
        </div>
        {serviceReady && !contentGenerationReady ? <p role="status">当前服务未配置内容生成，暂不能生成简历草稿。</p> : null}
        <Button
          type="secondary"
          loading={busy}
          disabled={!contentGenerationReady || busy}
          onClick={() => void createResumeDraft()}
        >
          {pendingResume ? "继续未完成的简历生成" : "生成简历草稿"}
        </Button>
      </section>
    </main>
  );
}
