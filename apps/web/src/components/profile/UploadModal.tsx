import { Alert, Button } from "../common/ui";
import { useRef } from "react";
import { ErrorNotice } from "../common/ErrorNotice";
import { ModalDialog } from "../common/ModalDialog";
import { DocumentUpload } from "./DocumentUpload";

export function UploadModal({
  isOpen,
  disabled,
  busy,
  pending,
  error,
  returnFocusElement,
  onSelect,
  onRetry,
  onClose,
}: {
  isOpen: boolean;
  disabled: boolean;
  busy: boolean;
  pending: boolean;
  error: unknown;
  returnFocusElement?: HTMLElement | null;
  onSelect: (file: File) => void;
  onRetry: () => void;
  onClose: () => void;
}) {
  const selectButtonRef = useRef<HTMLDivElement>(null);

  return (
    <ModalDialog
      isOpen={isOpen}
      busy={busy}
      titleId="upload-modal-title"
      eyebrow="资料导入"
      title="上传简历 PDF"
      returnFocusElement={returnFocusElement}
      initialFocusRef={selectButtonRef}
      onClose={onClose}
      footer={<Button type="secondary" disabled={busy} onClick={onClose}>关闭</Button>}
    >
      <p className="fact-modal-intro-text">
        选择 PDF 后会显示解析进度；关掉窗口不会中断已经开始的处理。
      </p>
      {pending ? (
        <Alert type="warn" title="上次上传没有收到结果">
          <p>文件已保留。点“继续上次上传”会沿用原请求，不会重复上传。</p>
          <Button type="secondary" disabled={busy} onClick={onRetry}>继续上次上传</Button>
        </Alert>
      ) : null}
      <ErrorNotice error={error} />
      <DocumentUpload
        actionRef={selectButtonRef}
        compact
        disabled={disabled}
        busy={busy}
        onSelect={onSelect}
      />
    </ModalDialog>
  );
}
