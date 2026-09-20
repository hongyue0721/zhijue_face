import { Button, Input, Textarea } from "@any-design/anyui/react";
import { useState } from "react";
import type { CreateInterviewOptions } from "../../api";

export function JDInput({
  disabled,
  busy,
  onGenerate,
}: {
  disabled: boolean;
  busy: boolean;
  onGenerate: (options: CreateInterviewOptions) => void;
}) {
  const [jobName, setJobName] = useState("嵌入式软件开发实习生");
  const [jdText, setJdText] = useState("");
  const [validation, setValidation] = useState<string | null>(null);

  const generate = () => {
    const name = jobName.trim();
    const text = jdText.trim();
    if (!name || !text) {
      setValidation("请填写岗位名称与岗位描述正文，或明确选择演示岗位配置。欠缺输入不会被自动补成真实岗位。");
      return;
    }
    setValidation(null);
    onGenerate({ jd_text: text, jd_source_name: name });
  };

  return (
    <section className="surface-card jd-input" aria-labelledby="jd-input-title">
      <div className="section-heading compact">
        <p className="eyebrow">岗位输入</p>
        <h2 id="jd-input-title">粘贴岗位信息</h2>
        <p>岗位要求与候选资料分别入库；系统不会从简历猜测 JD。</p>
      </div>
      <label className="field-label">
        岗位名称
        <Input
          modelValue={jobName}
          onUpdateModelValue={setJobName}
          placeholder="例如：嵌入式软件开发实习生"
          disabled={disabled || busy}
        />
      </label>
      <label className="field-label">
        岗位描述正文
        <Textarea
          modelValue={jdText}
          onUpdateModelValue={setJdText}
          placeholder="粘贴岗位职责、任职要求与优先条件"
          rows={10}
          maxlength={30000}
          disabled={disabled || busy}
        />
      </label>
      <div className="button-row split-actions">
        <Button type="primary" size="large" loading={busy} disabled={disabled || busy} onClick={generate}>
          根据岗位生成面试计划
        </Button>
        <Button
          type="secondary"
          size="large"
          disabled={disabled || busy}
          onClick={() => {
            setValidation(null);
            onGenerate({});
          }}
        >
          使用演示岗位配置
        </Button>
      </div>
      {validation ? <p className="field-error" role="alert">{validation}</p> : null}
    </section>
  );
}
