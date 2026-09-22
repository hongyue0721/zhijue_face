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
        {operation ? <Tag>{operationStatusText[operation.status]}</Tag> : document ? <Tag>{extractLabels[document.extract_status] ?? "解析状态待确认"}</Tag> : <Tag>等待上传</Tag>}
      </div>
      {active ? <p role="status">正在读取简历内容并整理出候选经历条目，完成后请逐条核对。</p> : null}
      {failed ? <Alert type="danger" title="材料处理未完成">{operation.error?.message ?? "文件处理失败。"}系统无法找回已上传的文件，请重新选择 PDF 上传。</Alert> : null}
      {document?.extract_status === "requires_text" ? <Alert type="warn" title="这份 PDF 里没有可读文字">扫描版（图片式）简历暂不支持自动识别。请直接填写经历，或重新上传能复制文字的 PDF。</Alert> : null}
      {document ? (
        <div className="document-meta">
          <span>{document.page_count == null ? "页数未识别" : `${document.page_count} 页`}</span>
          <span>{extractLabels[document.extract_status] ?? "解析状态待确认"}</span>
          {document.extract_status === "parsed" ? <DocumentBlocksDrawer document={document} /> : null}
        </div>
      ) : null}
      {document?.warnings.map((warning) => <p className="warning-text" key={warning}>{warning}</p>)}
    </section>
  );
}
