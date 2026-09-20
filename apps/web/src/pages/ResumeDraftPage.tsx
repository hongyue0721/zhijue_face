import { Alert, Button, Tag } from "@any-design/anyui/react";
import { useCallback, useEffect, useState } from "react";
import { api, newCommandKey, type OperationView, type ResumeDraftView } from "../api";
import { ErrorNotice } from "../components/common/ErrorNotice";
import { OperationStatus } from "../components/common/OperationStatus";
import { useOperationMonitor } from "../hooks/useOperationMonitor";
import { clearOperationId, loadOperationId, saveOperationId } from "../storage";

export function ResumeDraftPage({
  draftId,
  serviceReady,
}: {
  draftId: string;
  serviceReady: boolean;
}) {
  const [draft, setDraft] = useState<ResumeDraftView | null>(null);
  const [operationId, setOperationId] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);

  const applyDraft = useCallback((next: ResumeDraftView) => {
    setDraft(next);
    const recoverable = next.active_operation_id ?? loadOperationId("resume", next.id);
    if (recoverable) setOperationId(recoverable);
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
  const { operation, error: operationError } = useOperationMonitor(operationId, operationSettled);

  const retryGeneration = async () => {
    if (!draft || !operationId || busy) return;
    setBusy(true);
    setError(null);
    try {
      const accepted = await api.retryOperation(
        operationId,
        draft.revision,
        newCommandKey("resume-retry"),
      );
      saveOperationId("resume", draft.id, accepted.operation_id);
      setOperationId(accepted.operation_id);
      applyDraft(await api.getResumeDraft(draft.id));
    } catch (nextError) {
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

  return (
    <main className="page-container resume-page">
      <header className="resume-heading no-print">
        <div>
          <p className="eyebrow">简历草稿</p>
          <h1>基于已确认事实的表达版本</h1>
          <p>正文条目逐项绑定资料快照 Claim；缺失事实和风险不会混入可打印正文。</p>
        </div>
        <Tag>{draft.status}</Tag>
      </header>

      <div className="no-print">
        <ErrorNotice error={error ?? operationError} onReload={() => void reload()} />
        <OperationStatus operation={operation} label="简历生成" />
        {canRetry ? (
          <Button
            type="primary"
            loading={busy}
            disabled={!serviceReady || busy}
            onClick={() => void retryGeneration()}
          >
            重试简历生成
          </Button>
        ) : null}
        {draft.status === "generation_failed" && !canRetry ? (
          <Alert type="danger" title="简历生成未完成">请刷新操作状态后再决定是否重试。</Alert>
        ) : null}
      </div>

      <article
        className={`surface-card resume-document print-document ${
          draft.status === "accepted" ? "print-document--accepted" : ""
        }`}
        aria-labelledby="resume-document-title"
      >
        <header>
          <p className="eyebrow no-print">候选版本</p>
          <h2 id="resume-document-title">个人简历</h2>
          <p className="resume-target no-print">
            目标来源：{draft.target_context.source_name ?? draft.target_context.kind}
          </p>
        </header>
        {draft.sections.length ? draft.sections.map((section) => (
          <section className="resume-section" key={section.section_id}>
            <h3>{section.title}</h3>
            <ul>
              {section.items.map((item) => <li key={item.item_id}>{item.text}</li>)}
            </ul>
          </section>
        )) : (
          <p className="empty-state no-print">生成完成后，服务端会在这里返回可追溯正文。</p>
        )}
      </article>

      {draft.status === "draft" ? (
        <section className="surface-card draft-actions no-print">
          <div>
            <p className="eyebrow">版本确认</p>
            <h2>确认后才能打印</h2>
            <p>确认只冻结这一版草稿，不会改写原始资料、Claim 或面试评分。</p>
          </div>
          <Button type="primary" loading={busy} onClick={() => void acceptDraft()}>
            确认这版草稿
          </Button>
        </section>
      ) : null}

      {draft.status === "accepted" ? (
        <section className="surface-card draft-actions no-print">
          <div>
            <p className="eyebrow">已确认版本</p>
            <h2>可以打印或另存为 PDF</h2>
            <p>打印区域只包含已确认正文，不包含缺失事实、风险提示和审计信息。</p>
          </div>
          <Button type="primary" onClick={() => window.print()}>打印简历</Button>
        </section>
      ) : null}

      <section className="resume-audit no-print" aria-labelledby="resume-audit-title">
        <div className="section-heading">
          <p className="eyebrow">可追溯编辑</p>
          <h2 id="resume-audit-title">来源与改写差异</h2>
        </div>
        <div className="audit-list">
          {draft.changes.map((change) => (
            <article className="surface-card comparison-card" key={change.item_id}>
              <div><h3>来源事实</h3><p>{change.before}</p></div>
              <div><h3>简历表达</h3><p>{change.after}</p></div>
              <p className="change-note">{change.reason}</p>
              <small>Claim：{change.claim_ids.join("、")}</small>
            </article>
          ))}
        </div>
        {draft.source_claims.length ? (
          <details className="source-claim-list">
            <summary>查看已使用的确认事实</summary>
            <ul>
              {draft.source_claims.map((claim) => <li key={claim.id}>{claim.text}</li>)}
            </ul>
          </details>
        ) : null}
      </section>

      {(draft.missing_facts.length || draft.cautions.length) ? (
        <section className="surface-card editorial-notes no-print">
          <p className="eyebrow">不进入正文</p>
          <h2>待补充与注意项</h2>
          {draft.missing_facts.length ? (
            <div><h3>待本人补充</h3><ul>{draft.missing_facts.map((item) => <li key={item.prompt}>{item.prompt}：{item.reason}</li>)}</ul></div>
          ) : null}
          {draft.cautions.length ? (
            <div><h3>注意</h3><ul>{draft.cautions.map((item) => <li key={item}>{item}</li>)}</ul></div>
          ) : null}
        </section>
      ) : null}
    </main>
  );
}
