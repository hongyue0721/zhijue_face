import { Alert, Button } from "@any-design/anyui/react";
import { useRef, useState } from "react";
import { ApiError, type KnowledgePackList } from "../../api";
import { ModalDialog } from "../common/ModalDialog";

// 导入对话框只负责“选文件 → 提交受理”；进度观察由页面复用
// useOperationMonitor（不造第二套轮询管理器），关闭展示不影响后台。
export function KnowledgePackImportDialog({
  isOpen,
  limits,
  busy,
  operationError,
  retryable,
  onClose,
  onSubmit,
  onRetry,
}: {
  isOpen: boolean;
  limits: KnowledgePackList["import_limits"] | null;
  busy: boolean;
  operationError: { code: string; message: string; retryable: boolean } | null;
  retryable: boolean;
  onClose: () => void;
  onSubmit: (file: File) => void;
  onRetry: () => void;
}) {
  const [file, setFile] = useState<File | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const submit = () => {
    if (!file) {
      setNotice("请先选择岗位知识包 ZIP 文件。");
      return;
    }
    setNotice(null);
    onSubmit(file);
  };

  // 格式/安全/版本冲突类错误不允许“重试即可修好”：换文件才是恢复动作。
  const mustReselect =
    operationError !== null &&
    !operationError.retryable &&
    operationError.code !== "RETRY_NOT_ALLOWED";

  return (
    <ModalDialog
      isOpen={isOpen}
      busy={busy}
      titleId="pack-import-title"
      eyebrow="岗位知识包"
      title="导入岗位知识包"
      onClose={onClose}
      footer={
        <>
          <Button disabled={busy} onClick={onClose}>
            关闭
          </Button>
          {operationError && !mustReselect ? (
            <Button type="primary" disabled={busy || !retryable} onClick={onRetry}>
              重试导入
            </Button>
          ) : null}
          <Button
            type="primary"
            disabled={busy || !file || mustReselect}
            onClick={submit}
          >
            {busy ? "提交中…" : "提交导入"}
          </Button>
        </>
      }
    >
      <p>
        包需包含 manifest.json、seeds/、competencies.json 与 sources.json。
        导入成功只代表格式通过；技术审核与“可用于新面试”是独立状态，
        外部上传默认未审核。
      </p>
      {limits ? (
        <p className="pack-import-limits">
          上限：ZIP {Math.floor(limits.max_upload_bytes / 1024 / 1024)} MiB ·
          解压 {Math.floor(limits.max_extracted_total_bytes / 1024 / 1024)} MiB ·
          条目 {limits.max_entries}
        </p>
      ) : null}
      <input
        ref={inputRef}
        type="file"
        accept="application/zip,.zip"
        disabled={busy}
        onChange={(event) => {
          setFile(event.target.files?.[0] ?? null);
          setNotice(null);
        }}
      />
      {file ? (
        <p className="pack-import-file">
          已选择：{file.name}（{Math.ceil(file.size / 1024)} KiB）
        </p>
      ) : null}
      {notice ? <Alert type="warn" title="还不能提交">{notice}</Alert> : null}
      {operationError ? (
        <Alert type="danger" title={`导入失败 · ${operationError.code}`}>
          <p>{operationError.message}</p>
          {mustReselect ? (
            <p>这类错误重试不会改变结果，请修正包内容后重新选择文件。</p>
          ) : null}
        </Alert>
      ) : null}
    </ModalDialog>
  );
}

export function packImportError(error: unknown) {
  return error instanceof ApiError ? error : null;
}
