import { Alert, Button } from "@any-design/anyui/react";
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
        选择文本型 PDF 后，页面会显示真实解析状态；关闭窗口不会取消已经提交的后台处理。
      </p>
      {pending ? (
        <Alert type="warn" title="上次上传请求的结果还不确定">
          <p>已保留本次文件和请求标识。请继续原请求，不要重新选择文件创建另一条命令。</p>
          <Button type="secondary" disabled={busy} onClick={onRetry}>重新提交原上传请求</Button>
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
