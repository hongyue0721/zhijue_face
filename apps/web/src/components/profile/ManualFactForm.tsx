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
      setValidation("请写下一条可由你确认的项目或技能事实。");
      return;
    }
    setValidation(null);
    if (await onSubmit(value)) setText("");
  };

  return (
    <section className="surface-card manual-fact" aria-labelledby="manual-fact-title">
      <div>
        <p className="eyebrow">补充经历</p>
        <h2 id="manual-fact-title">手工补充一条事实</h2>
        <p>系统不会补造资料；你提交的内容仍需经过确认才能进入资料快照。</p>
      </div>
      <label className="field-label">
        项目或技能事实
        <Textarea
          modelValue={text}
          onUpdateModelValue={setText}
          placeholder="例如：我在项目中使用 UART + DMA 接收数据，并通过日志与逻辑分析仪定位错帧。"
          maxlength={2000}
          rows={5}
          disabled={disabled || busy}
        />
      </label>
      <div className="field-footer">
        <span>{text.length} / 2000</span>
        <Button type="primary" loading={busy} disabled={disabled || busy} onClick={submit}>
          保存为待确认事实
        </Button>
      </div>
      {validation ? <p className="field-error" role="alert">{validation}</p> : null}
    </section>
  );
}
