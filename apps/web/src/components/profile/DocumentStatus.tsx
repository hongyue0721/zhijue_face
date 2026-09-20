import { Alert, Tag } from "@any-design/anyui/react";
import type { DocumentView, OperationView } from "../../api";
import { operationStatusText } from "../../presentation";
import { DocumentBlocksDrawer } from "./DocumentBlocksDrawer";

function extractText(status: DocumentView["extract_status"]): string {
  const labels: Record<string, string> = {
    pending: "等待解析",
    parsed: "文本解析完成",
    requires_text: "未检测到可用文本",
    failed: "文本解析失败",
  };
  return labels[status] ?? status;
}

function indexText(status: DocumentView["index_status"]): string {
  const labels: Record<string, string> = {
    pending: "索引等待资料确认",
    indexing: "正在写入检索索引",
    ready: "索引完成",
    failed: "索引失败",
  };
  return labels[status] ?? status;
}

function documentBadge(document: DocumentView): { text: string; tone: "success" | "warn" | "danger" | "primary" } {
  if (document.extract_status === "failed" || document.index_status === "failed") {
    return { text: "处理未完成", tone: "danger" };
  }
  if (document.extract_status === "requires_text") {
    return { text: "需要补充文字", tone: "warn" };
  }
  if (document.index_status === "ready") return { text: "索引完成", tone: "success" };
  if (document.extract_status === "parsed") return { text: "解析完成", tone: "success" };
  return { text: "等待处理", tone: "primary" };
}

export function DocumentStatus({
  selectedName,
  operation,
  document,
}: {
  selectedName: string | null;
  operation: OperationView | null;
  document: DocumentView | null;
}) {
  if (!selectedName && !operation && !document) return null;
  const operationActive = operation?.status === "queued" || operation?.status === "running";
  const failed = operation && ["failed", "interrupted", "canceled"].includes(operation.status);
  const badge = document ? documentBadge(document) : null;
  const showProcessing = !document || operationActive || Boolean(failed);
  return (
    <section className="surface-card document-status" aria-labelledby="document-status-title">
      <div className="card-heading-row">
        <div>
          <p className="eyebrow">简历材料</p>
          <h2 id="document-status-title">{document?.filename_display ?? selectedName ?? "简历 PDF"}</h2>
        </div>
        {operation ? (
          <Tag className={`status-tag--${operation.status === "succeeded" ? "success" : operationActive ? "primary" : "danger"}`}>
            {operationStatusText[operation.status]}
          </Tag>
        ) : badge ? (
          <Tag className={`status-tag--${badge.tone}`}>{badge.text}</Tag>
        ) : null}
      </div>
      {showProcessing ? (
        <ol className="processing-steps">
          <li className={operation || document ? "complete" : undefined}>
            <span>1</span><div><strong>文件已接收</strong><small>业务后端已受理上传请求</small></div>
          </li>
          <li className={document?.extract_status === "parsed" ? "complete" : failed ? "failed" : operationActive ? "active" : undefined}>
            <span>2</span><div><strong>{document ? extractText(document.extract_status) : "正在提取文本"}</strong><small>正在读取 PDF 文字内容</small></div>
          </li>
          <li className={document?.index_status === "ready" ? "complete" : document?.index_status === "failed" ? "failed" : document?.index_status === "indexing" ? "active" : undefined}>
            <span>3</span><div><strong>{document ? indexText(document.index_status) : "等待索引状态"}</strong><small>正在准备面试检索材料</small></div>
          </li>
        </ol>
      ) : null}
      {operationActive ? <Alert type="info" title="处理中，请勿重复上传">页面会持续更新处理状态。</Alert> : null}
      {failed ? <Alert type="danger" title="资料处理未完成">{operation?.error?.message ?? "操作失败，请根据服务端状态重新选择文件。"}</Alert> : null}
      {document ? (
        <div className="document-meta">
          <span>{document.page_count == null ? "页数未识别" : `${document.page_count} 页`}</span>
          <span>{extractText(document.extract_status)} · {indexText(document.index_status)}</span>
          {document.extract_status === "parsed" ? <DocumentBlocksDrawer document={document} /> : null}
        </div>
      ) : null}
      {document?.warnings.map((warning) => <p className="warning-text" key={warning}>{warning}</p>)}
    </section>
  );
}
