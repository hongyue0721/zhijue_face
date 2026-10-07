import { useRef, useState, type DragEvent, type Ref } from "react";
import { Button } from "../common/ui";
import { Icon } from "../common/icons";

const MAX_PDF_BYTES = 10 * 1024 * 1024;

const FLOW_STEPS = [
  { title: "上传 PDF", detail: "提取待核对的经历" },
  { title: "核对经历", detail: "逐条采用、更正或不采用" },
  { title: "模拟面试", detail: "按岗位要求问五道主问题" },
];

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
  const [dragging, setDragging] = useState(false);
  const blocked = disabled || busy;

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

  // 整张卡片都接收拖放，拖入时给出可见反馈；处理中不接受新文件。
  const handleDragOver = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    if (!blocked) setDragging(true);
  };
  const handleDragLeave = (event: DragEvent<HTMLElement>) => {
    if (!event.currentTarget.contains(event.relatedTarget as Node | null)) setDragging(false);
  };
  const handleDrop = (event: DragEvent<HTMLElement>) => {
    event.preventDefault();
    setDragging(false);
    if (!blocked) accept(event.dataTransfer.files[0]);
  };

  return (
    <section
      className={`upload-card ${compact ? "upload-card--dialog" : "upload-hero"} ${dragging ? "is-dragging" : ""}`}
      aria-label={compact ? "选择要上传的 PDF 文件" : undefined}
      aria-labelledby={compact ? undefined : "upload-title"}
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {!compact ? (
        <>
          <div className="upload-hero__icon" aria-hidden="true">
            <Icon name="document" />
          </div>
          <h1 id="upload-title">上传你的简历</h1>
          <p className="upload-hero__lede">
            职觉从简历里提取经历，由你逐条核对确认；面试只依据你确认过的内容提问，不替你补造经历。
          </p>
        </>
      ) : null}
      <div className="drop-zone">
        <input
          ref={inputRef}
          className="visually-hidden"
          type="file"
          accept="application/pdf,.pdf"
          disabled={blocked}
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
          disabled={blocked}
          loading={busy}
          onClick={() => inputRef.current?.click()}
        >
          {busy ? "正在提交" : "上传简历"}
        </Button>
        <span className="drop-zone__hint">{dragging ? "松开即可上传" : "或把 PDF 拖到这里"}</span>
      </div>
      {!compact ? (
        <ol className="flow-steps" aria-label="使用流程">
          {FLOW_STEPS.map((step, index) => (
            <li key={step.title}>
              <span className="flow-steps__index" aria-hidden="true">{index + 1}</span>
              <span>
                <strong>{step.title}</strong>
                <small>{step.detail}</small>
              </span>
            </li>
          ))}
        </ol>
      ) : null}
      <p className="upload-limits">
        支持文本型 PDF，每份不超过 {MAX_PDF_BYTES / (1024 * 1024)} MiB、5 页。扫描版（图片式）PDF 暂不支持文字识别，可改用手动填写经历；加密文件请先解除密码保护。
      </p>
      {validation ? <p className="field-error" role="alert">{validation}</p> : null}
    </section>
  );
}
