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
import { improvementsStatusText } from "../presentation";
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

function scoreText(score: number | null): string {
  return score === null ? "未形成总分" : `${score} 分`;
}

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
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const applyReport = useCallback((next: ReportView) => {
    setReport(next);
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

  return (
    <main className="page-container report-page">
      <header className="report-heading">
        <div>
          <p className="eyebrow">面试报告</p>
          <h1>本场表现与事实依据</h1>
          <p>评分只汇总本场已观察到的回答；未覆盖项不按零分处理。</p>
        </div>
        <div className="score-summary" aria-label="本场总分">
          <strong>{scoreText(report.overall_score)}</strong>
          <span>{report.completion === "complete" ? "完整场次" : "未完整场次"}</span>
        </div>
      </header>

      <ErrorNotice error={error ?? operationError} onReload={() => void reload()} />
      <OperationStatus operation={operation} label="回答优化" />

      <section className="surface-card report-overview" aria-labelledby="coverage-title">
        <div className="card-heading-row">
          <div>
            <p className="eyebrow">覆盖范围</p>
            <h2 id="coverage-title">评分覆盖</h2>
          </div>
          <Tag>{report.coverage.overall_eligible ? "总分条件满足" : "总分条件不足"}</Tag>
        </div>
        <dl className="metric-grid">
          <div><dt>计划根题</dt><dd>{report.coverage.planned_root_count}</dd></div>
          <div><dt>已回答</dt><dd>{report.coverage.answered_root_count}</dd></div>
          <div><dt>已评分</dt><dd>{report.coverage.scored_root_count}</dd></div>
          <div><dt>未测量</dt><dd>{report.coverage.unmeasured_root_count}</dd></div>
        </dl>
        {report.limitations.length ? (
          <ul className="plain-list limitation-list">
            {report.limitations.map((limitation, index) => (
              <li key={`${String(limitation)}-${index}`}>{String(limitation)}</li>
            ))}
          </ul>
        ) : null}
      </section>

      <section className="report-section" aria-labelledby="assessment-title">
        <div className="section-heading">
          <p className="eyebrow">根题汇总</p>
          <h2 id="assessment-title">逐题观察</h2>
        </div>
        <div className="assessment-list">
          {report.root_assessments.map((assessment, index) => (
            <article className="surface-card assessment-card" key={assessment.root_question_id}>
              <div className="card-heading-row">
                <h3>根题 {index + 1}</h3>
                <Tag>{assessment.score === null ? assessment.status : `${assessment.score} 分`}</Tag>
              </div>
              <p>覆盖率 {Math.round(assessment.coverage * 100)}%</p>
              {assessment.criterion_results.map((criterion) => (
                <div className="criterion-result" key={criterion.criterion_id}>
                  <strong>{criterion.criterion_id}</strong>
                  <span>{criterion.finding} · 等级 {criterion.level ?? "未评"}</span>
                  {criterion.explanations.map((text, explanationIndex) => (
                    <p key={`${criterion.criterion_id}-explanation-${explanationIndex}`}>{text}</p>
                  ))}
                  {criterion.answer_quotes.map((quote) => (
                    <blockquote key={`${quote.answer_id}-${quote.exact_quote}`}>{quote.exact_quote}</blockquote>
                  ))}
                </div>
              ))}
            </article>
          ))}
        </div>
      </section>

      <section className="surface-card coaching-section" aria-labelledby="coaching-title">
        <div className="card-heading-row">
          <div>
            <p className="eyebrow">表达优化</p>
            <h2 id="coaching-title">基于原回答的改写</h2>
          </div>
          <Tag>{improvementsStatusText[report.improvements_status]}</Tag>
        </div>
        <p>改写片段必须绑定本场逐字回答或当前资料快照事实；缺失信息单独列出，不补进正文。</p>
        {report.improvements_status === "not_requested" || pendingImprovements ? (
          <Button
            type="primary"
            loading={busy}
            disabled={!serviceReady || busy}
            onClick={() => void generateImprovements()}
          >
            {pendingImprovements ? "使用原请求重试" : "生成回答优化"}
          </Button>
        ) : null}
        {canRetry ? (
          <Button type="primary" loading={busy} onClick={() => void retryImprovements()}>
            {pendingRetry ? "使用原重试请求" : "重试回答优化"}
          </Button>
        ) : null}
        {report.improvements_status === "failed" && !canRetry ? (
          <Alert type="danger" title="回答优化未完成">请刷新操作状态后再决定是否重试。</Alert>
        ) : null}
        <div className="improvement-list">
          {report.improved_answers.map((item) => (
            <article className="comparison-card" key={item.root_question_id}>
              <div>
                <h3>原回答</h3>
                {item.original_answers.map((answer) => <p key={answer.answer_id}>{answer.raw_text}</p>)}
              </div>
              <div>
                <h3>优化后</h3>
                <p>{item.rewritten_answer}</p>
                {item.changes.length ? <p className="change-note">{item.changes.join("；")}</p> : null}
              </div>
              {item.missing_facts.length ? (
                <div className="editorial-note">
                  <strong>仍需本人补充</strong>
                  <ul>{item.missing_facts.map((fact) => <li key={fact.prompt}>{fact.prompt}：{fact.reason}</li>)}</ul>
                </div>
              ) : null}
              {item.cautions.length ? (
                <div className="editorial-note">
                  <strong>注意</strong>
                  <ul>{item.cautions.map((caution) => <li key={caution}>{caution}</li>)}</ul>
                </div>
              ) : null}
            </article>
          ))}
        </div>
      </section>

      <section className="surface-card report-next-step">
        <div>
          <p className="eyebrow">下一步</p>
          <h2>生成可追溯简历草稿</h2>
          <p>简历正文只使用当前不可变资料快照中的已确认事实，岗位信息只影响排序和措辞。</p>
        </div>
        <Button type="primary" loading={busy} disabled={!serviceReady || busy} onClick={() => void createResumeDraft()}>
          {pendingResume ? "使用原请求创建草稿" : "生成简历草稿"}
        </Button>
      </section>
    </main>
  );
}
