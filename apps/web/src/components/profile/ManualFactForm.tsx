import { Button, Textarea } from "@any-design/anyui/react";
import { useState } from "react";

export function ManualFactForm({
  disabled,
  busy,
  onSubmit,
}: {
  disabled: boolean;
  busy: boolean;
  onSubmit: (text: string) => Promise<boolean>;
}) {
  const [text, setText] = useState("");
  const [validation, setValidation] = useState<string | null>(null);

  const submit = async () => {
    const value = text.trim();
    if (!value) {
      setValidation("请输入一条真实的项目、经历或技能事实。");
      return;
    }
    setValidation(null);
    if (await onSubmit(value)) setText("");
  };

  return (
    <section className="surface-card manual-fact" aria-labelledby="manual-fact-title">
      <div className="manual-fact-header">
        <p className="eyebrow">补充经历</p>
        <h2 id="manual-fact-title">手工录入经历事实</h2>
        <p className="manual-fact-subtext">填写后会先进入“待确认事实”列表，你确认后才会计入面试资料。</p>
      </div>
      <label className="field-label">
        项目或技能事实描述
        <Textarea
          modelValue={text}
          onUpdateModelValue={setText}
          placeholder="例如：在 STM32 平台使用 UART + DMA 接收多传感器数据，并通过逻辑分析仪分析错帧。"
          maxlength={2000}
          rows={4}
          disabled={disabled || busy}
        />
      </label>
      <div className="field-footer">
        <span className="char-counter">{text.length} / 2000</span>
        <Button type="primary" loading={busy} disabled={disabled || busy} onClick={submit}>
          保存为待确认事实
        </Button>
      </div>
      {validation ? <p className="field-error" role="alert">{validation}</p> : null}
    </section>
  );
}
