import { Button } from "@any-design/anyui/react";
import { useRef, useState, type DragEvent, type Ref } from "react";

const MAX_PDF_BYTES = 10 * 1024 * 1024;

export function DocumentUpload({
  disabled,
  busy,
  compact = false,
  actionRef,
  onSelect,
}: {
  disabled: boolean;
  busy: boolean;
  compact?: boolean;
  actionRef?: Ref<HTMLDivElement>;
  onSelect: (file: File) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [validation, setValidation] = useState<string | null>(null);

  const accept = (file?: File) => {
    if (!file) return;
    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      setValidation("请选择 PDF 文件。扫描版（图片式）简历可能需要手工填写经历。");
      return;
    }
    if (file.size > MAX_PDF_BYTES) {
      setValidation("文件超过 10 MiB 的大小限制。请压缩后重试。");
      return;
    }
    setValidation(null);
    onSelect(file);
  };

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    if (!disabled && !busy) accept(event.dataTransfer.files[0]);
  };

  return (
    <section
      className={`surface-card upload-card ${compact ? "upload-card--dialog" : ""}`}
      aria-label={compact ? "选择要上传的 PDF 文件" : undefined}
      aria-labelledby={compact ? undefined : "upload-title"}
    >
      {!compact ? (
        <>
          <div className="upload-icon" aria-hidden="true">PDF</div>
          <h2 id="upload-title">上传你的简历</h2>
        </>
      ) : null}
      <div className="drop-zone" onDragOver={(event) => event.preventDefault()} onDrop={handleDrop}>
        <input
          ref={inputRef}
          className="visually-hidden"
          type="file"
          accept="application/pdf,.pdf"
          disabled={disabled || busy}
          onChange={(event) => {
            const file = event.target.files?.[0];
            event.target.value = "";
            accept(file);
          }}
        />

        <Button
          ref={actionRef}
          type="primary"
          size="large"
          disabled={disabled || busy}
          loading={busy}
          onClick={() => inputRef.current?.click()}
        >
          {busy ? "正在提交" : "上传简历"}
        </Button>
      </div>

      {validation ? <p className="field-error" role="alert">{validation}</p> : null}

    </section>
  );
}
