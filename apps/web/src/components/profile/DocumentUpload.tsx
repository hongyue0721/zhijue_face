import { Button } from "@any-design/anyui/react";
import { useRef, useState, type DragEvent } from "react";

const MAX_PDF_BYTES = 10 * 1024 * 1024;

export function DocumentUpload({
  disabled,
  busy,
  onSelect,
}: {
  disabled: boolean;
  busy: boolean;
  onSelect: (file: File) => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  const [validation, setValidation] = useState<string | null>(null);

  const accept = (file?: File) => {
    if (!file) return;
    if (file.type !== "application/pdf" && !file.name.toLowerCase().endsWith(".pdf")) {
      setValidation("请选择 PDF 文件。扫描版 PDF 可能需要手工补充事实。");
      return;
    }
    if (file.size > MAX_PDF_BYTES) {
      setValidation("文件超过当前 P0 的 10 MB 上传限制。请压缩后重试。");
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
    <section className="surface-card upload-card" aria-labelledby="upload-title">
      <div className="upload-icon" aria-hidden="true">PDF</div>
      <h2 id="upload-title">上传简历 PDF</h2>
      <p>支持文本型 PDF，最大 10 MB。文件仅进入本地业务后端，不会写入 URL。</p>
      <div className="drop-zone" onDragOver={(event) => event.preventDefault()} onDrop={handleDrop}>
        <input
          ref={inputRef}
          className="visually-hidden"
          type="file"
          accept="application/pdf,.pdf"
          disabled={disabled || busy}
          onChange={(event) => accept(event.target.files?.[0])}
        />
        <Button
          type="primary"
          size="large"
          disabled={disabled || busy}
          loading={busy}
          onClick={() => inputRef.current?.click()}
        >
          {busy ? "正在提交" : "选择 PDF 文件"}
        </Button>
        <span>或将文件拖放到这里</span>
      </div>
      {validation ? <p className="field-error" role="alert">{validation}</p> : null}
      <p className="privacy-note">隐私提示：服务端日志不会记录完整简历正文，页面不会把文件路径暴露给浏览器地址栏。</p>
    </section>
  );
}
