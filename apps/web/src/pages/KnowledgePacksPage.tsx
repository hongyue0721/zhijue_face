import { Tag } from "@any-design/anyui/react";
import { Alert, Button } from "../components/common/ui";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  ApiError,
  api,
  newCommandKey,
  type KnowledgePackDetail,
  type KnowledgePackItem,
  type KnowledgePackList,
  type OperationView,
} from "../api";
import { ErrorNotice } from "../components/common/ErrorNotice";
import { KnowledgePackImportDialog } from "../components/packs/KnowledgePackImportDialog";
import { OperationStatus } from "../components/common/OperationStatus";
import { useOperationMonitor } from "../hooks/useOperationMonitor";
import { BackLink, PageHeading, PageNav } from "../components/layout/PageNav";
import { knowledgePacksPath } from "../routing";
import {
  dateTimeText,
  reviewDecisionText,
  reviewerRoleText,
  validationCheckText,
  validationStatusText,
} from "../presentation";
import {
  clearOperationId,
  loadOperationId,
  saveOperationId,
  savePackSelection,
} from "../storage";

// 状态三色分离（U6）：格式通过 / 负责人审核 / 可用于新面试互不推导。
function reviewTag(item: KnowledgePackItem) {
  if (item.review_status === "approved") return <Tag className="status-tag--success">审核通过</Tag>;
  if (item.review_status === "rejected") return <Tag className="status-tag--danger">审核未通过</Tag>;
  return <Tag>技术审核待完成</Tag>;
}

function selectableTag(item: KnowledgePackItem) {
  return item.selectable
    ? <Tag className="status-tag--primary">可用于新面试</Tag>
    : <Tag>暂不可用于新面试</Tag>;
}

function formatStateTag(item: KnowledgePackItem) {
  return item.validation_status === "passed"
    ? <Tag className="status-tag--success">格式通过</Tag>
    : <Tag className="status-tag--warn">格式未通过</Tag>;
}

function PackScopeSummary({ item }: { item: KnowledgePackItem }) {
  return (
    <div className="pack-scope">
      <p><strong>覆盖范围</strong>{item.scope_summary}</p>
      <p><strong>明确不支持</strong>{item.unsupported_scope}</p>
      <p><strong>能力规则版本</strong>{item.profile_version || "未提供"}</p>
      <p><strong>规则审核</strong>{item.rules_reviewed ? "负责人已审核当前规则" : "尚无当前规则的负责人审核事实"}</p>
      <p className="technical-value">规则摘要：{item.profile_digest || "未提供"}</p>
      <p className="pack-scope-counts">
        已审核题目种子 {item.approved_seed_count}/{item.seed_count} · 登记来源 {item.source_count} 条
      </p>
      <ul className="pack-capability-list" aria-label="能力覆盖（服务端事实）">
        {item.capabilities.map((capability) => (
          <li key={capability.competency_id}>
            <span>{capability.label || capability.competency_id}</span>
            <Tag className={capability.technical_seed_available ? "status-tag--success" : undefined}>
              {capability.technical_seed_available ? "有已审核题目" : "仅表达与证据训练"}
            </Tag>
          </li>
        ))}
      </ul>
    </div>
  );
}

function PackSourceList({ detail }: { detail: KnowledgePackDetail }) {
  return (
    <details className="requirement-details compact-details">
      <summary>查看来源登记（{detail.sources.length}）</summary>
      <ul className="pack-source-list">
        {detail.sources.map((source, index) => {
          const url = typeof source.url === "string" ? source.url : null;
          const safe = url !== null && /^https?:\/\//.test(url);
          return (
            <li key={String(source.source_id ?? index)}>
              <strong>{String(source.title ?? source.source_id ?? "未命名来源")}</strong>
              {source.publisher ? <span> · {String(source.publisher)}</span> : null}
              {safe ? (
                // 用户主动点击才离开；无自动抓取；noopener 防反向控制。
                <a href={url} target="_blank" rel="noopener noreferrer nofollow">
                  打开来源
                </a>
              ) : null}
            </li>
          );
        })}
      </ul>
    </details>
  );
}

function PackValidationSummary({ detail }: { detail: KnowledgePackDetail }) {
  return (
    <details className="requirement-details compact-details">
      <summary>查看校验结果（{detail.validation_checks.length}）</summary>
      <ul className="pack-validation-list">
        {detail.validation_checks.map((check) => (
          <li key={check.check}>
            <Tag className={check.status === "passed" ? "status-tag--success" : check.status === "not_run" ? undefined : "status-tag--warn"}>
              {validationStatusText(check.status)}
            </Tag>
            <span>{validationCheckText(check.check)}：{check.detail}</span>
          </li>
        ))}
      </ul>
      <p className="pack-limitations-note">{detail.limitations_note}</p>
    </details>
  );
}

export function KnowledgePacksPage({
  releaseId,
  returnTo,
  navigate,
}: {
  releaseId: string | null;
  returnTo: string;
  navigate: (path: string, replace?: boolean) => void;
}) {
  const [list, setList] = useState<KnowledgePackList | null>(null);
  const [listError, setListError] = useState<unknown>(null);
  const [listLoading, setListLoading] = useState(true);
  const [detail, setDetail] = useState<KnowledgePackDetail | null>(null);
  const [detailError, setDetailError] = useState<unknown>(null);
  const [pageError, setPageError] = useState<unknown>(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [importOperationId, setImportOperationId] = useState<string | null>(
    () => loadOperationId("packs", "import"),
  );
  const [importResult, setImportResult] = useState<Record<string, unknown> | null>(null);
  const [copied, setCopied] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const detailSeq = useRef(0);
  const submitInFlight = useRef(false);

  const reloadList = useCallback(() => {
    const controller = new AbortController();
    setListLoading(true);
    setListError(null);
    api.listKnowledgePacks(controller.signal)
      .then((next) => {
        if (controller.signal.aborted) return;
        setList(next);
      })
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        setListError(error);
      })
      .finally(() => {
        if (!controller.signal.aborted) setListLoading(false);
      });
    return controller;
  }, []);

  useEffect(() => {
    const controller = reloadList();
    return () => controller.abort();
  }, [reloadList]);

  const selectedId = releaseId ?? list?.default_pack_release_id ?? list?.items[0]?.pack_release_id ?? null;

  // 详情按 ID 取；快速切换时旧响应不得覆盖新选择（U7）。
  useEffect(() => {
    if (!selectedId) {
      setDetail(null);
      return;
    }
    const seq = ++detailSeq.current;
    const controller = new AbortController();
    setDetail(null);
    setDetailError(null);
    api.getKnowledgePack(selectedId, controller.signal)
      .then((next) => {
        if (seq !== detailSeq.current) return;
        setDetail(next);
      })
      .catch((error) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (seq !== detailSeq.current) return;
        setDetailError(error);
      });
    return () => controller.abort();
  }, [selectedId]);

  const importSettled = useCallback((settled: OperationView) => {
    if (settled.status === "succeeded") {
      clearOperationId("packs", "import");
      setImportOperationId(null);
      setImportResult(settled.result);
      setDialogOpen(false);
      reloadList();
    }
  }, [reloadList]);

  const importUnavailable = useCallback((error: unknown) => {
    clearOperationId("packs", "import");
    setImportOperationId(null);
    setPageError(error);
  }, []);

  const { operation: importOperation, error: importMonitorError } = useOperationMonitor(
    importOperationId,
    importSettled,
    importUnavailable,
  );

  const changeImportFile = () => {
    if (submitInFlight.current) return;
    clearOperationId("packs", "import");
    setImportOperationId(null);
    setPageError(null);
    setImportResult(null);
  };

  const submitImport = async (file: File) => {
    if (submitInFlight.current) return;
    submitInFlight.current = true;
    setSubmitting(true);
    setPageError(null);
    setImportResult(null);
    try {
      const accepted = await api.importKnowledgePack(file, newCommandKey("pack-import"));
      saveOperationId("packs", "import", accepted.operation_id);
      setImportOperationId(accepted.operation_id);
    } catch (error) {
      setPageError(error);
    } finally {
      submitInFlight.current = false;
      setSubmitting(false);
    }
  };

  const retryImport = async () => {
    if (!importOperation || submitInFlight.current) return;
    submitInFlight.current = true;
    setPageError(null);
    setSubmitting(true);
    try {
      const accepted = await api.retryOperation(
        importOperation.id,
        importOperation.attempts,
        newCommandKey("pack-import-retry"),
      );
      saveOperationId("packs", "import", accepted.operation_id);
      setImportOperationId(accepted.operation_id);
    } catch (error) {
      setPageError(error);
    } finally {
      submitInFlight.current = false;
      setSubmitting(false);
    }
  };

  const copyIdentifier = async (value: string, label: string) => {
    try {
      await navigator.clipboard.writeText(value);
      setCopied(label);
      window.setTimeout(() => setCopied(null), 2000);
    } catch {
      setCopied("复制失败，请手动选择文本");
      window.setTimeout(() => setCopied(null), 2500);
    }
  };

  const busy = submitting || Boolean(importOperationId && !importOperation && !importMonitorError)
    || importOperation?.status === "queued" || importOperation?.status === "running";
  const connectionLost = listError !== null && !(listError instanceof ApiError);

  return (
    <main className="page-container packs-page">
      <PageNav label="岗位知识页导航">
        <BackLink onClick={() => navigate(returnTo)}>返回上一页</BackLink>
      </PageNav>
      <PageHeading
        eyebrow="岗位知识"
        title="岗位知识包"
        aside={(
          <Button
            type="primary"
            onClick={() => {
              setImportResult(null);
              setDialogOpen(true);
            }}
          >
            导入岗位包
          </Button>
        )}
      >
        <p>
          面试出题使用的结构化岗位知识。选择只影响新创建的面试；已创建的面试始终使用当时选定的知识包。
        </p>
      </PageHeading>
      {importResult ? (
        <Alert type="success" title="导入完成">
          {Boolean(importResult.reused)
            ? "已有内容相同的知识包，直接沿用，没有重复导入。"
            : `已导入 ${String(importResult.pack_id)} v${String(importResult.version)}。`}
          {" "}当前审核状态：{reviewDecisionText(importResult.review_status)}；
          {Boolean(importResult.selectable_for_new_interview)
            ? "可用于新面试。"
            : "尚不可用于新面试（格式通过 ≠ 审核通过）。"}
        </Alert>
      ) : null}
      <ErrorNotice error={pageError ?? importMonitorError} onReload={() => reloadList()} />
      <OperationStatus operation={importOperation} label="导入岗位包" />
      {importOperation?.error?.retryable ? (
        <Button disabled={busy} onClick={() => void retryImport()}>重试导入</Button>
      ) : null}
      {listLoading && !list ? (
        <p className="packs-loading" role="status">正在读取岗位知识包列表…</p>
      ) : null}
      {connectionLost ? (
        <Alert type="danger" title="无法连接服务">
          <p>岗位知识包列表读取失败；这不是“没有包”，请稍后重试连接。</p>
          <Button size="small" onClick={() => reloadList()}>重试连接</Button>
        </Alert>
      ) : null}
      {listError instanceof ApiError ? (
        <ErrorNotice error={listError} onReload={() => reloadList()} />
      ) : null}
      {list && !listLoading && list.items.length === 0 && !listError ? (
        <Alert type="info" title="尚无岗位知识包">
          还没有导入任何岗位包。导入不依赖面试模型是否就绪，可以现在导入。
        </Alert>
      ) : null}
      {list ? (
        <div className="packs-layout">
          <KnowledgePackListPanel
            list={list}
            selectedId={selectedId}
            onSelect={(id) => navigate(knowledgePacksPath(id, returnTo))}
          />
          <section className="pack-detail" aria-label="岗位包详情">
            {detail ? (
              <>
                <header className="pack-detail-header">
                  <div>
                    <h2>{detail.name} v{detail.version}</h2>
                    <p className="pack-detail-meta">
                      <code>{detail.pack_release_id}</code>
                      <Button
                        size="small"
                        type="secondary"
                        onClick={() => void copyIdentifier(detail.pack_release_id, "标识已复制")}
                      >
                        复制标识
                      </Button>
                    </p>
                    <p className="pack-detail-tags">
                      {formatStateTag(detail)} {reviewTag(detail)} {selectableTag(detail)}
                    </p>
                    {copied ? <p className="pack-copied">{copied}</p> : null}
                  </div>
                </header>
                <PackScopeSummary item={detail} />
                {detail.blocked_reasons.length > 0 ? (
                  <Alert type="warn" title="为什么暂不可用">
                    <ul>
                      {detail.blocked_reasons.map((reason) => (
                        <li key={reason.code}>{reason.message}</li>
                      ))}
                    </ul>
                  </Alert>
                ) : null}
                {detail.review_summary ? (
                  <p className="pack-review-note">
                    审核记录：{reviewerRoleText(detail.review_summary.reviewer_role)}{reviewDecisionText(detail.review_summary.decision)}
                    {" · "}{dateTimeText(detail.review_summary.reviewed_at)}
                    （对应内容摘要 {detail.content_digest.slice(0, 23)}…）
                  </p>
                ) : (
                  <p className="pack-review-note">
                    还没有针对当前内容的负责人审核记录；包内自带的“已审核”声明不算数。
                  </p>
                )}
                <p className="pack-digest-line">
                  内容摘要 <code>{detail.content_digest}</code>
                  <Button
                    size="small"
                    type="secondary"
                    onClick={() => void copyIdentifier(detail.content_digest, "摘要已复制")}
                  >
                    复制
                  </Button>
                </p>
                <PackSourceList detail={detail} />
                <PackValidationSummary detail={detail} />
                <div className="pack-detail-actions">
                  <Button
                    type="primary"
                    disabled={!detail.selectable}
                    onClick={() => {
                      savePackSelection(detail.pack_release_id);
                      setCopied("已选定：下次新建面试将使用这个知识包");
                      window.setTimeout(() => setCopied(null), 2500);
                    }}
                  >
                    用于新面试
                  </Button>
                  {!detail.selectable ? (
                    <small>需负责人审核通过后才能用于新面试；提交时服务器还会再确认一次。</small>
                  ) : null}
                </div>
              </>
            ) : detailError ? (
              <ErrorNotice error={detailError} onReload={() => {
                if (selectedId) {
                  const seq = detailSeq.current;
                  void api.getKnowledgePack(selectedId).then((next) => {
                    if (seq === detailSeq.current) setDetail(next);
                  }).catch(() => undefined);
                }
              }} />
            ) : (
              <p className="packs-loading">选择左侧岗位知识包查看详情。</p>
            )}
          </section>
        </div>
      ) : null}
      <KnowledgePackImportDialog
        isOpen={dialogOpen}
        limits={list?.import_limits ?? null}
        onFileChange={changeImportFile}
        busy={busy}
        submitting={submitting}
        operationError={importOperation?.error ?? null}
        retryable={Boolean(importOperation?.error?.retryable)}
        onClose={() => setDialogOpen(false)}
        onSubmit={(file) => void submitImport(file)}
        onRetry={() => void retryImport()}
      />
    </main>
  );
}

function KnowledgePackListPanel({
  list,
  selectedId,
  onSelect,
}: {
  list: KnowledgePackList;
  selectedId: string | null;
  onSelect: (releaseId: string) => void;
}) {
  return (
    <ul className="pack-list" aria-label="岗位知识包列表">
      {list.items.map((item) => (
        <li key={item.pack_release_id}>
          <button
            type="button"
            className={`pack-list-item${item.pack_release_id === selectedId ? " selected" : ""}`}
            onClick={() => onSelect(item.pack_release_id)}
          >
            <span className="pack-list-name">
              {item.name} <small>v{item.version}</small>
              {item.pack_release_id === list.default_pack_release_id ? (
                <Tag>默认岗位包</Tag>
              ) : null}
            </span>
            <span className="pack-list-tags">
              {formatStateTag(item)} {reviewTag(item)}
              <Tag className={item.rules_reviewed ? "status-tag--success" : "status-tag--warn"}>
                {item.rules_reviewed ? "规则已审核" : "规则待审核"}
              </Tag>
            </span>
            <small>
              题目种子 {item.approved_seed_count}/{item.seed_count} · 来源 {item.source_count}
            </small>
          </button>
        </li>
      ))}
    </ul>
  );
}
