import { Alert, Button } from "@any-design/anyui/react";
import { useCallback, useEffect, useState } from "react";
import {
  api,
  newCommandKey,
  shouldPreserveWriteCommand,
  type OperationView,
  type ResumeDraftView,
} from "../api";
import { ErrorNotice } from "../components/common/ErrorNotice";
import { OperationStatus } from "../components/common/OperationStatus";
import { useOperationMonitor } from "../hooks/useOperationMonitor";
import { resumeTargetText } from "../presentation";
import { reportPath, startPath } from "../routing";
import {
  clearOperationId,
  clearRecoverableCommand,
  loadOperationId,
  loadRecoverableCommand,
  saveOperationId,
  saveRecoverableCommand,
  type RecoverableCommand,
} from "../storage";

type ResumeRetryCommand = Extract<RecoverableCommand, { kind: "resume-retry" }>;

export function ResumeDraftPage({
  draftId,
  serviceReady,
  navigate,
}: {
  draftId: string;
  serviceReady: boolean;
  navigate: (path: string) => void;
}) {
  const [draft, setDraft] = useState<ResumeDraftView | null>(null);
  const [operationId, setOperationId] = useState<string | null>(null);
  const [pendingRetry, setPendingRetry] = useState<ResumeRetryCommand | null>(null);
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const applyDraft = useCallback((next: ResumeDraftView) => {
    setDraft(next);
    setSelectedItemId((current) => {
      const items = next.sections.flatMap((section) => section.items);
      if (current && items.some((item) => item.item_id === current)) return current;
      return items[0]?.item_id ?? null;
    });
    const storedRetry = loadRecoverableCommand("resume-retry", next.id);
    setPendingRetry(storedRetry?.kind === "resume-retry" ? storedRetry : null);
    if (next.status === "draft" || next.status === "accepted") {
      clearOperationId("resume", next.id);
      clearRecoverableCommand("resume-retry", next.id);
      setPendingRetry(null);
      setOperationId(null);
      return;
    }
    if (next.status === "generating" && next.active_operation_id) {
      saveOperationId("resume", next.id, next.active_operation_id);
      clearRecoverableCommand("resume-retry", next.id);
      setPendingRetry(null);
      setOperationId(next.active_operation_id);
      return;
    }
    // generation_failed 时服务端保留失败链尾操作作为恢复键（api.md §6）：
    // 跨浏览器、清缓存后仍能 GET 该 Operation 并走 /retry。
    if (next.status === "generation_failed" && next.active_operation_id) {
      saveOperationId("resume", next.id, next.active_operation_id);
      setOperationId(next.active_operation_id);
      return;
    }
    setOperationId(loadOperationId("resume", next.id));
  }, []);

  const reload = useCallback(async () => {
    applyDraft(await api.getResumeDraft(draftId));
  }, [applyDraft, draftId]);

  useEffect(() => {
    const controller = new AbortController();
    setError(null);
    api.getResumeDraft(draftId, controller.signal)
      .then(applyDraft)
      .catch((nextError) => {
        if (!(nextError instanceof DOMException && nextError.name === "AbortError")) {
          setError(nextError);
        }
      });
    return () => controller.abort();
  }, [applyDraft, draftId]);

  const operationSettled = useCallback(
    async (settled: OperationView) => {
      if (settled.status === "succeeded") {
        clearOperationId("resume", draftId);
        setOperationId(null);
      }
      try {
        applyDraft(await api.getResumeDraft(draftId));
      } catch (nextError) {
        setError(nextError);
      }
    },
    [applyDraft, draftId],
  );
  const operationUnavailable = useCallback((nextError: unknown) => {
    clearOperationId("resume", draftId);
    setOperationId(null);
    setError(nextError);
  }, [draftId]);
  const { operation, error: operationError } = useOperationMonitor(
    operationId,
    operationSettled,
    operationUnavailable,
  );

  const retryGeneration = async () => {
    if (!draft || !operationId || busy) return;
    const command: ResumeRetryCommand = pendingRetry ?? {
      kind: "resume-retry",
      idempotencyKey: newCommandKey("resume-retry"),
      input: {
        operation_id: operationId,
        expected_revision: draft.revision,
      },
    };
    saveRecoverableCommand("resume-retry", draft.id, command);
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
      clearRecoverableCommand("resume-retry", draft.id);
      setPendingRetry(null);
      saveOperationId("resume", draft.id, accepted.operation_id);
      setOperationId(accepted.operation_id);
      applyDraft(await api.getResumeDraft(draft.id));
    } catch (nextError) {
      if (!responseObserved && !shouldPreserveWriteCommand(nextError)) {
        clearRecoverableCommand("resume-retry", draft.id);
        setPendingRetry(null);
      }
      setError(nextError);
    } finally {
      setBusy(false);
    }
  };

  const acceptDraft = async () => {
    if (!draft || draft.status !== "draft" || busy) return;
    setBusy(true);
    setError(null);
    try {
      applyDraft(await api.acceptResumeDraft(draft.id, draft.revision));
    } catch (nextError) {
      setError(nextError);
    } finally {
      setBusy(false);
    }
  };

  if (!draft) {
    return (
      <main className="page-container narrow-page">
        <ErrorNotice error={error} onReload={() => void reload()} />
        {!error ? <p className="loading-row">正在读取简历草稿</p> : null}
      </main>
    );
  }

  const canRetry = draft.status === "generation_failed"
    && Boolean(operationId)
    && Boolean(operation?.error?.retryable);
  const operationLoading = Boolean(operationId && !operation && !operationError);
  const failureDetail = draft.status === "generation_failed"
    ? operationLoading
      ? "正在读取这次失败的详细状态。"
      : operation?.error?.retryable === false
        ? "这次生成失败，服务端已确认重试次数用完。已确认的资料不受影响。"
        : operationError
          ? "失败详情暂时无法读取；页面已经停止重复查询，请刷新草稿状态。"
          : !operationId
            ? "服务端没有提供可恢复的操作记录；已确认的资料不受影响。"
            : null
    : null;
  const resumeItems = draft.sections.flatMap((section) => section.items);
  const selectedItem = resumeItems.find((item) => item.item_id === selectedItemId) ?? null;
  const selectedChange = draft.changes.find(
    (change) => change.item_id === selectedItem?.item_id,
  ) ?? null;
  const selectedSourceIds = selectedChange?.claim_ids ?? selectedItem?.claim_ids ?? [];
  const selectedSources = selectedSourceIds.flatMap((sourceId) => {
    const source = draft.source_claims.find((claim) => claim.id === sourceId);
    return source ? [source] : [];
  });
  const targetName = resumeTargetText(draft.target_context);

  return (
    <main className="page-container resume-page">
      <nav className="page-backlinks no-print" aria-label="简历返回导航">
        <Button type="secondary" size="small" onClick={() => navigate(startPath(draft.profile_id))}>
          返回资料核对
        </Button>
        {draft.interview_id ? (
          <Button type="secondary" size="small" onClick={() => navigate(reportPath(draft.interview_id!))}>
            返回面试报告
          </Button>
        ) : null}
      </nav>
      <header className="compact-page-heading resume-heading no-print">
        <div>

          <h1>{draft.status === "accepted" ? "你的简历，已确认" : "把经历整理成简历"}</h1>
          {draft.status === "generating" ? (
            <p>正在整理你已确认的经历。</p>
          ) : draft.status === "generation_failed" ? (
            <p>简历尚未生成，请查看失败原因后重试。</p>
          ) : null}

        </div>
        <div className="heading-actions">
          {canRetry ? (
            <Button
              type="primary"
              loading={busy}
              disabled={!serviceReady || busy}
              onClick={() => void retryGeneration()}
            >
              {pendingRetry ? "继续未完成的重试" : "重试简历生成"}
            </Button>
          ) : null}
          {draft.status === "draft" ? (
            <Button
              type="primary"
              loading={busy}
              disabled={!serviceReady || busy}
              onClick={() => void acceptDraft()}
            >
              确认这版草稿
            </Button>
          ) : null}
          {draft.status === "accepted" ? (
            <Button type="primary" onClick={() => window.print()}>打印简历</Button>
          ) : null}
        </div>
      </header>

      <div className="no-print">
        <ErrorNotice error={error ?? operationError} onReload={() => void reload()} />
        <OperationStatus operation={operation} label="简历生成" />
        {failureDetail && !canRetry ? (
          <Alert type={operationLoading ? "info" : "danger"} title="简历生成未完成">
            {failureDetail}
          </Alert>
        ) : null}
      </div>

      <section className="resume-workspace">
        <article
          className={`resume-document resume-paper print-document ${
            draft.status === "accepted" ? "print-document--accepted" : ""
          }`}
          aria-labelledby="resume-document-title"
        >
          <header>
            <p className="eyebrow no-print">正文预览</p>
            <h2 id="resume-document-title">个人简历</h2>
            <p className="resume-target no-print">目标岗位：{targetName}</p>
          </header>
          {draft.sections.length ? draft.sections.map((section) => (
            <section className="resume-section" key={section.section_id}>
              <h3>{section.title}</h3>
              <ul>
                {section.items.map((item) => (
                  <li key={item.item_id}>
                    <button
                      type="button"
                      className={item.item_id === selectedItem?.item_id ? "active" : ""}
                      aria-pressed={item.item_id === selectedItem?.item_id}
                      onClick={() => setSelectedItemId(item.item_id)}
                    >
                      {item.text}
                    </button>
                  </li>
                ))}
              </ul>
            </section>
          )) : (
            <p className="empty-state no-print">生成完成后，这里会显示简历正文。</p>
          )}
        </article>

        <aside className="resume-audit-panel resume-source-panel no-print" aria-labelledby="resume-audit-title">
          <div className="report-detail-heading">
            <div>
              <h2 id="resume-audit-title">来源核对</h2>
            </div>
            <span className="source-count">{selectedSources.length} 项来源</span>
          </div>
          {selectedItem ? (
            <div className="resume-source-reading">
              <section className="resume-selected-copy">
                <h3>简历表达</h3>
                <p>{selectedItem.text}</p>
              </section>
              <section className="related-sources">
                <h3>已确认的来源</h3>
                {selectedSources.length ? selectedSources.map((source) => (
                  <blockquote key={source.id}>{source.text}</blockquote>
                )) : <p>这条正文的来源暂未返回，请刷新后再核对。</p>}
              </section>
              {selectedChange ? (
                <section className="resume-change-explanation">
                  <h3>改写原因</h3>
                  <p>{selectedChange.reason}</p>
                  <details className="compact-details">
                    <summary>查看改写前后</summary>
                    <h4>原文</h4>
                    <p>{selectedChange.before}</p>
                    <h4>改写后</h4>
                    <p>{selectedChange.after}</p>
                  </details>
                </section>
              ) : null}
            </div>
          ) : (
            <p className="empty-state">正文生成后，可逐条查看引用的资料。</p>
          )}

          {(draft.missing_facts.length || draft.cautions.length) ? (
            <details className="compact-details resume-notes">
              <summary>
                待补充 {draft.missing_facts.length} 项
                {" · "}注意 {draft.cautions.length} 项
              </summary>
              {draft.missing_facts.length ? (
                <div>
                  <h3>待本人补充</h3>
                  <ul>
                    {draft.missing_facts.map((item) => (
                      <li key={item.prompt}>{item.prompt}：{item.reason}</li>
                    ))}
                  </ul>
                </div>
              ) : null}
              {draft.cautions.length ? (
                <div>
                  <h3>注意</h3>
                  <ul>{draft.cautions.map((item) => <li key={item}>{item}</li>)}</ul>
                </div>
              ) : null}
            </details>
          ) : null}
        </aside>
      </section>
    </main>
  );
}
