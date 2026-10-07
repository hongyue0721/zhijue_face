import { Alert, Button } from "../components/common/ui";
import { useCallback, useEffect, useRef, useState } from "react";
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
import { BackLink, PageHeading, PageNav } from "../components/layout/PageNav";
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
  contentGenerationReady,
  navigate,
}: {
  draftId: string;
  serviceReady: boolean;
  contentGenerationReady: boolean;
  navigate: (path: string) => void;
}) {
  const [draft, setDraft] = useState<ResumeDraftView | null>(null);
  const [operationId, setOperationId] = useState<string | null>(null);
  const [pendingRetry, setPendingRetry] = useState<ResumeRetryCommand | null>(null);
  const [selectedItemId, setSelectedItemId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const draftRef = useRef<ResumeDraftView | null>(null);
  const pageGeneration = useRef(0);

  const applyDraft = useCallback((next: ResumeDraftView) => {
    if (next.id !== draftId || (draftRef.current?.id === next.id && draftRef.current.revision > next.revision)) return;
    draftRef.current = next;
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
  }, [draftId]);

  const reload = useCallback(async () => {
    const generation = pageGeneration.current;
    const next = await api.getResumeDraft(draftId);
    if (generation === pageGeneration.current) applyDraft(next);
  }, [applyDraft, draftId]);

  useEffect(() => {
    const controller = new AbortController();
    pageGeneration.current += 1;
    draftRef.current = null;
    setDraft(null);
    setOperationId(null);
    setBusy(false);
    setError(null);
    api.getResumeDraft(draftId, controller.signal)
      .then((next) => {
        if (!controller.signal.aborted) applyDraft(next);
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
  }, [applyDraft, draftId]);

  const operationSettled = useCallback(
    async (_settled: OperationView, signal: AbortSignal) => {
      try {
        const next = await api.getResumeDraft(draftId, signal);
        if (!signal.aborted) applyDraft(next);
      } catch (nextError) {
        if (!signal.aborted) setError(nextError);
      }
    },
    [applyDraft, draftId],
  );
  const operationUnavailable = useCallback((nextError: unknown) => {
    clearOperationId("resume", draftId);
    setOperationId(null);
    setError(nextError);
  }, [draftId]);
  const operationSuccessor = useCallback((nextId: string) => {
    saveOperationId("resume", draftId, nextId);
    clearRecoverableCommand("resume-retry", draftId);
    setPendingRetry(null);
    setOperationId(nextId);
  }, [draftId]);
  const { operation, error: operationError } = useOperationMonitor(
    operationId,
    operationSettled,
    operationUnavailable,
    operationSuccessor,
  );

  const retryGeneration = async () => {
    if (!draft || !operationId || busy || !contentGenerationReady) return;
    const generation = pageGeneration.current;
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
      if (generation !== pageGeneration.current) return;
      responseObserved = true;
      clearRecoverableCommand("resume-retry", draft.id);
      setPendingRetry(null);
      saveOperationId("resume", draft.id, accepted.operation_id);
      setOperationId(accepted.operation_id);
      const next = await api.getResumeDraft(draft.id);
      if (generation === pageGeneration.current) applyDraft(next);
    } catch (nextError) {
      if (generation !== pageGeneration.current) return;
      if (!responseObserved && !shouldPreserveWriteCommand(nextError)) {
        clearRecoverableCommand("resume-retry", draft.id);
        setPendingRetry(null);
      }
      setError(nextError);
    } finally {
      if (generation === pageGeneration.current) setBusy(false);
    }
  };

  const acceptDraft = async () => {
    if (!draft || draft.status !== "draft" || busy) return;
    const generation = pageGeneration.current;
    setBusy(true);
    setError(null);
    try {
      const next = await api.acceptResumeDraft(draft.id, draft.revision);
      if (generation === pageGeneration.current) applyDraft(next);
    } catch (nextError) {
      if (generation === pageGeneration.current) setError(nextError);
    } finally {
      if (generation === pageGeneration.current) setBusy(false);
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

  const operationLoading = Boolean(operationId && !operation && !operationError);
  const generationActive = operationLoading || operation?.status === "queued" || operation?.status === "running";
  const canRetry = draft.status === "generation_failed"
    && operation?.id === operationId
    && (operation?.status === "failed" || operation?.status === "interrupted")
    && !operation.next_operation_id
    && Boolean(operation.error?.retryable);
  const failureDetail = draft.status === "generation_failed"
    ? operationLoading
      ? "正在读取这次处理的详细状态。"
      : generationActive
        ? null
        : operation?.error?.retryable === false
          ? "这次生成无法再重试（次数已用完，或失败原因需要先处理）。已确认的经历不受影响。"
          : operationError
            ? "失败详情暂时无法读取；页面仍会继续查询处理状态，也可手动刷新草稿状态。"
            : !operationId
              ? "没有找到可以恢复的处理记录；已确认的经历不受影响。"
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
      <PageNav label="简历返回导航" className="no-print">
        <BackLink onClick={() => navigate(startPath(draft.profile_id))}>返回资料核对</BackLink>
        {draft.interview_id ? (
          <BackLink onClick={() => navigate(reportPath(draft.interview_id!))}>返回面试报告</BackLink>
        ) : null}
      </PageNav>
      <PageHeading
        className="resume-heading no-print"
        eyebrow="简历整理"
        title={draft.status === "accepted" ? "简历已确认，可以打印" : "把经历整理成简历"}
        aside={(
          <>
            {canRetry ? (
              <Button
                type="primary"
                loading={busy}
                disabled={!contentGenerationReady || busy}
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
          </>
        )}
      >
        {draft.status === "generating" || generationActive ? (
          <p>正在整理你已确认的经历。</p>
        ) : draft.status === "generation_failed" ? (
          <p>本次简历生成未完成，已确认经历仍保留。请查看下方处理结果。</p>
        ) : draft.status === "draft" ? (
          <p>正文每一条都对应你确认过的经历；点选任一条可在右侧核对来源，确认后才能打印。</p>
        ) : draft.status === "accepted" ? (
          <p>打印时只输出简历正文，不包含右侧的来源核对。</p>
        ) : null}
      </PageHeading>
      {serviceReady && !contentGenerationReady && draft.status === "generation_failed" ? (
        <p role="status">当前服务未配置内容生成，暂不能重试简历生成；已有草稿仍可查看和确认。</p>
      ) : null}

      <div className="no-print">
        <ErrorNotice error={error ?? operationError} onReload={() => void reload()} />
        <OperationStatus operation={operation} label="简历生成" />
        {failureDetail && !canRetry ? (
          <Alert type={operationLoading ? "info" : "danger"} title={operationLoading ? "正在恢复简历生成状态" : "简历生成未完成"}>
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
            <p className="empty-state no-print">{draft.status === "generation_failed"
              ? "本次没有生成可核对的简历正文。你可以返回资料核对，或查看已有面试报告。"
              : "生成完成后，这里会显示简历正文。"}</p>
          )}
        </article>

        <aside className="resume-audit-panel resume-source-panel no-print" aria-labelledby="resume-audit-title">
          <div className="report-detail-heading">
            <div>
              <h2 id="resume-audit-title">来源核对</h2>
            </div>
            {selectedItem ? <span className="source-count">{selectedSources.length} 项来源</span> : null}
          </div>
          {selectedItem ? (
            <div className="resume-source-reading">
              <section className="resume-selected-copy">
                <h3>简历中的写法</h3>
                <p>{selectedItem.text}</p>
              </section>
              <section className="related-sources">
                <h3>对应的已确认经历</h3>
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
            <p className="empty-state">{draft.status === "generation_failed"
              ? "尚无生成正文可关联来源；这不表示你的已确认经历为空。"
              : "生成正文后，点选任一条即可查看对应的已确认经历。"}</p>
          )}

          {(draft.missing_facts.length || draft.cautions.length) ? (
            <details className="compact-details resume-notes">
              <summary>
                待补充 {draft.missing_facts.length} 项
                {" · "}注意 {draft.cautions.length} 项
              </summary>
              {draft.missing_facts.length ? (
                <div>
                  <h3>需要你补充</h3>
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
