import { useEffect, useRef, useState } from "react";
import { Button, Tag, Textarea } from "@any-design/anyui/react";
import { ModalDialog } from "../common/ModalDialog";

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
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);

  const isOpen = props.isOpen;

  useEffect(() => {
    if (!isOpen) return;
    setError(null);
    setText(props.mode === "correct" ? props.initialText : "");
  }, [isOpen, props.mode, props.mode === "correct" ? props.initialText : null]);

  if (!isOpen) return null;


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

  const isCorrectMode = props.mode === "correct";
  const modalBusy = submitting || (!isCorrectMode && Boolean(props.busy));

  return (
    <ModalDialog
      isOpen={isOpen}
      busy={modalBusy}
      titleId="fact-modal-title"
      eyebrow={isCorrectMode ? "更正这条事实" : "补充经历事实"}
      title={isCorrectMode ? "更正经历事实描述" : "手工记录一条经历或技能"}
      returnFocusElement={props.returnFocusElement}
      initialFocusRef={textareaRef}
      onClose={props.onClose}
      footer={(
        <>
          <Button
            type="secondary"
            disabled={submitting}
            onClick={props.onClose}
          >
            取消
          </Button>
          <Button
            type="primary"
            loading={modalBusy}
            disabled={modalBusy || (!isCorrectMode && props.disabled)}
            onClick={handleSubmit}
          >
            {isCorrectMode ? "保存更正" : "保存为待确认事实"}
          </Button>
        </>
      )}
    >
      {isCorrectMode ? (
        <div className="fact-modal-origin-box">
          <div className="origin-label-row">
            <Tag>材料原文对照</Tag>

          </div>
          <p className="origin-text">{props.originalText}</p>
          {props.sourceQuotes && props.sourceQuotes.some((quote) => quote.exact_quote) ? (
            <details className="fact-modal-source-details">
              <summary>查看出处精准引文</summary>
              <div className="source-quotes-body">
                {props.sourceQuotes.map((quote, index) =>
                  quote.exact_quote ? (
                    <blockquote key={index}>
                      <small>{quote.origin === "user_input" ? "本人更正" : "材料引文"}</small>
                      <span>{quote.exact_quote}</span>
                    </blockquote>
                  ) : null,
                )}
              </div>
            </details>
          ) : null}
        </div>
      ) : null}

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
          disabled={modalBusy || (!isCorrectMode && props.disabled)}
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
    </ModalDialog>
  );
}
