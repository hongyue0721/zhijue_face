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
    <section className="surface-card upload-card" aria-labelledby="upload-title">
      <div className="upload-icon" aria-hidden="true">PDF</div>
      <h2 id="upload-title">上传简历 PDF</h2>
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
        <span className="upload-guidance">拖入文件，或点击选择</span>
        <Button
          type="primary"
          size="large"
          disabled={disabled || busy}
          loading={busy}
          onClick={() => inputRef.current?.click()}
        >
          {busy ? "正在提交" : "选择 PDF 文件"}
        </Button>
      </div>
      <p className="upload-limits">PDF · 最大 10 MiB · 最多 5 页</p>
      {validation ? <p className="field-error" role="alert">{validation}</p> : null}
      <p className="privacy-note">文件只发送到本地业务服务处理；实时模式下，提取出的文字可能发送给已配置的模型服务。正文不会写入网址或浏览器存储。</p>
    </section>
  );
}
