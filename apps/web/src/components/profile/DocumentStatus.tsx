import { Alert } from "@any-design/anyui/react";
import type { DocumentView, OperationView } from "../../api";
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
    <section className="document-status material-summary" aria-labelledby="document-status-title">
      <div className="material-summary-row">
        <strong id="document-status-title">{selectedName ?? document?.filename_display ?? "简历 PDF"}</strong>
        <span>{active ? "识别中" : failed ? "识别未完成" : document ? extractLabels[document.extract_status] ?? "解析状态待确认" : "等待上传"}</span>
        {document?.extract_status === "parsed" ? <DocumentBlocksDrawer document={document} /> : null}
      </div>
      {failed ? <Alert type="danger" title="材料处理未完成">{operation.error?.message ?? "文件处理失败，请重新选择 PDF。"}</Alert> : null}
      {document?.extract_status === "requires_text" ? <Alert type="warn" title="这份 PDF 里没有可读文字">请手动填写经历，或上传能复制文字的 PDF。</Alert> : null}
      {document?.warnings.map((warning) => <p className="warning-text" key={warning}>{warning}</p>)}
    </section>
  );
}
