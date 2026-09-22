import { useEffect, useRef, useState } from "react";
import { Button, Tag, Textarea } from "@any-design/anyui/react";

type FocusTarget = HTMLElement | null;
export type FactModalProps =
  | {
      mode: "correct";
      isOpen: boolean;
      claimId: string;
      originalText: string;
      initialText: string;
      sourceQuotes?: Array<{ exact_quote?: string; origin?: string }>;
      returnFocusElement?: FocusTarget;
      onSave: (correctedText: string) => boolean;
      onClose: () => void;
    }
  | {
      mode: "create";
      isOpen: boolean;
      disabled?: boolean;
      busy?: boolean;
      returnFocusElement?: FocusTarget;
      onSave: (text: string) => Promise<boolean>;
      onClose: () => void;
    };

export function FactModal(props: FactModalProps) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const previousActiveElement = useRef<HTMLElement | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const isOpen = props.isOpen;

  // 当弹窗打开时初始化文本并记录焦点，关闭时将焦点还给触发按钮
  useEffect(() => {
    if (!isOpen) return;
    previousActiveElement.current = document.activeElement as HTMLElement | null;
    setError(null);
    if (props.mode === "correct") {
      setText(props.initialText);
    } else {
      setText("");
    }
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) {
      dialog.showModal();
      textareaRef.current?.focus();
    }
    return () => {
      const target = dialogRef.current;
      if (target?.open) target.close();
      (props.returnFocusElement ?? previousActiveElement.current)?.focus?.();
    };
  }, [isOpen, props.mode, props.mode === "correct" ? props.initialText : null]);

  if (!isOpen) return null;

  const handleBackdropClick = (event: React.MouseEvent<HTMLDialogElement>) => {
    // 点击半透明背景区域关闭
    if (event.target === dialogRef.current && !submitting) {
      props.onClose();
    }
  };

  const handleCancel = (event: React.SyntheticEvent) => {
    event.preventDefault();
    if (!submitting) props.onClose();
  };

  const handleSubmit = async () => {
    const trimmed = text.trim();
    if (!trimmed) {
      setError("请输入有效的事实描述内容。");
      return;
    }
    if (trimmed.length > 2000) {
      setError("内容不可超过 2000 字上限。");
      return;
    }

    setError(null);

    if (props.mode === "correct") {
      const saved = props.onSave(trimmed);
      if (saved) {
        props.onClose();
      } else {
        setError("每次最多提交 50 条选择，请先提交已有选择再进行更正。");
      }
    } else {
      setSubmitting(true);
      try {
        const ok = await props.onSave(trimmed);
        if (ok) {
          setText("");
          props.onClose();
        } else {
          setError("保存没有完成。内容仍保留在这里，请查看页面错误后重试。");
        }
      } catch {
        setError("保存没有完成。内容仍保留在这里，请检查服务后重试。");
      } finally {
        setSubmitting(false);
      }
    }
  };
  const handleKeyDown = (event: React.KeyboardEvent<HTMLDialogElement>) => {
    if (event.key !== "Tab") return;
    const dialog = dialogRef.current;
    if (!dialog) return;
    const focusable = Array.from(
      dialog.querySelectorAll<HTMLElement>(
        "button:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex='-1'])",
      ),
    ).filter((element) => !element.hasAttribute("disabled") && element.getClientRects().length > 0);
    if (focusable.length === 0) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  const isCorrectMode = props.mode === "correct";

  return (
    <dialog
      ref={dialogRef}
      className="fact-modal-dialog"
      onClick={handleBackdropClick}
      onCancel={handleCancel}
      onKeyDown={handleKeyDown}
      aria-labelledby="fact-modal-title"
    >
      <div className="fact-modal-card" onClick={(e) => e.stopPropagation()}>
        <header className="fact-modal-header">
          <div>
            <p className="eyebrow">{isCorrectMode ? "更正这条事实" : "补充经历事实"}</p>
            <h2 id="fact-modal-title">
              {isCorrectMode ? "更正经历事实描述" : "手工记录一条经历或技能"}
            </h2>
          </div>
          <button
            type="button"
            className="fact-modal-close-btn"
            aria-label="关闭对话框"
            disabled={submitting}
            onClick={props.onClose}
          >
            ✕
          </button>
        </header>

        <div className="fact-modal-body">
          {isCorrectMode ? (
            <div className="fact-modal-origin-box">
              <div className="origin-label-row">
                <Tag>材料原文对照</Tag>
                <small>修改后的内容将作为“本人更正”保存</small>
              </div>
              <p className="origin-text">{props.originalText}</p>
              {props.sourceQuotes && props.sourceQuotes.some((q) => q.exact_quote) ? (
                <details className="fact-modal-source-details">
                  <summary>查看出处精准引文</summary>
                  <div className="source-quotes-body">
                    {props.sourceQuotes.map((q, i) =>
                      q.exact_quote ? (
                        <blockquote key={i}>
                          <small>{q.origin === "user_input" ? "本人更正" : "材料引文"}</small>
                          <span>{q.exact_quote}</span>
                        </blockquote>
                      ) : null,
                    )}
                  </div>
                </details>
              ) : null}
            </div>
          ) : (
            <p className="fact-modal-intro-text">
              录入你的真实项目、工具或工程实践事实。提交后进入待确认列表。
            </p>
          )}

          <label className="field-label fact-modal-editor-label">
            {isCorrectMode ? "更正后的事实描述" : "项目或技能事实描述"}
            <Textarea
              ref={textareaRef}
              modelValue={text}
              onUpdateModelValue={setText}
              placeholder={
                isCorrectMode
                  ? "请输入修改后的准确事实描述..."
                  : "例如：在 STM32 平台使用 UART + DMA 接收多传感器数据，并通过逻辑分析仪分析错帧。"
              }
              maxlength={2000}
              rows={isCorrectMode ? 5 : 6}
              disabled={submitting || (!isCorrectMode && props.disabled)}
            />
          </label>

          <div className="fact-modal-meta-row">
            <span className="char-counter">{text.length} / 2000</span>
            {error ? (
              <span className="field-error-inline" role="alert">
                {error}
              </span>
            ) : null}
          </div>
        </div>

        <footer className="fact-modal-footer">
          <Button
            type="secondary"
            disabled={submitting}
            onClick={props.onClose}
          >
            取消
          </Button>
          <Button
            type="primary"
            loading={submitting || (!isCorrectMode && props.busy)}
            disabled={submitting || (!isCorrectMode && props.disabled)}
            onClick={handleSubmit}
          >
            {isCorrectMode ? "保存更正" : "保存为待确认事实"}
          </Button>
        </footer>
      </div>
    </dialog>
  );
}
