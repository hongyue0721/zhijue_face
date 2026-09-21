import { Alert, Tag } from "@any-design/anyui/react";
import type { DocumentView, OperationView } from "../../api";
import { operationStatusText } from "../../presentation";
import { DocumentBlocksDrawer } from "./DocumentBlocksDrawer";

const extractLabels: Record<string, string> = {
  pending: "等待解析",
  parsed: "文本解析完成",
  requires_text: "需要补充文字",
  failed: "文本解析失败",
};

export function DocumentStatus({ selectedName, operation, document }: {
  selectedName: string | null;
  operation: OperationView | null;
  document: DocumentView | null;
}) {
  if (!selectedName && !operation && !document) return null;
  const active = operation?.status === "queued" || operation?.status === "running";
  const failed = operation && ["failed", "interrupted", "canceled"].includes(operation.status);
  return (
    <section className="surface-card document-status material-summary" aria-labelledby="document-status-title">
      <div className="card-heading-row">
        <div>
          <p className="eyebrow">简历材料</p>
          <h2 id="document-status-title">{selectedName ?? document?.filename_display ?? "简历 PDF"}</h2>
        </div>
        {operation ? <Tag>{operationStatusText[operation.status]}</Tag> : document ? <Tag>{extractLabels[document.extract_status] ?? document.extract_status}</Tag> : <Tag>尚未确认受理</Tag>}
      </div>
      {active ? <p role="status">正在提取文本与候选事实；处理完成后请逐条核对。</p> : null}
      {failed ? <Alert type="danger" title="材料处理未完成">{operation.error?.message ?? "文件处理失败。"} 无法重放原上传文件，请重新选择 PDF。</Alert> : null}
      {document?.extract_status === "requires_text" ? <Alert type="warn" title="未检测到可用文本">扫描版 PDF 暂不进行 OCR。请直接填写经历，或重新上传含文字的 PDF。</Alert> : null}
      {document ? (
        <div className="document-meta">
          <span>{document.page_count == null ? "页数未识别" : `${document.page_count} 页`}</span>
          <span>{extractLabels[document.extract_status] ?? document.extract_status}</span>
          {document.extract_status === "parsed" ? <DocumentBlocksDrawer document={document} /> : null}
        </div>
      ) : null}
      {document?.warnings.map((warning) => <p className="warning-text" key={warning}>{warning}</p>)}
    </section>
  );
}
