import { Button, Input, Textarea } from "@any-design/anyui/react";
import { useMemo, useState } from "react";
import {
  JD_SOURCE_NAME_MAX_LENGTH,
  JD_TEXT_MAX_LENGTH,
  type CreateInterviewOptions,
} from "../../api";
import {
  assembleJdText,
  splitJdText,
  type JDSections,
} from "../../jdSections";

export function JDInput({
  disabled,
  busy,
  onGenerate,
  initialOptions,
  regenerating = false,
  onCancel,
}: {
  disabled: boolean;
  busy: boolean;
  onGenerate: (options: CreateInterviewOptions) => void;
  initialOptions?: CreateInterviewOptions;
  regenerating?: boolean;
  onCancel?: () => void;
}) {
  const initial = useMemo(
    () => splitJdText(initialOptions?.jd_text ?? ""),
    [initialOptions?.jd_text],
  );
  const [jobName, setJobName] = useState(initialOptions?.jd_source_name ?? "");
  const [sections, setSections] = useState<JDSections>({
    required: initial.required,
    preferred: initial.preferred,
    responsibilities: initial.responsibilities,
  });
  const [validation, setValidation] = useState<string | null>(null);
  const assembled = assembleJdText(sections);

  const setSection = (key: keyof JDSections) => (value: string) =>
    setSections((current) => ({ ...current, [key]: value }));

  const generate = () => {
    const name = jobName.trim();
    if (!name || !assembled) {
      setValidation(
        "请填写岗位名称，并在必要项、加分项或岗位职责中至少填入一条；欠缺输入不会被自动补成真实岗位。",
      );
      return;
    }
    if (name.length > JD_SOURCE_NAME_MAX_LENGTH || assembled.length > JD_TEXT_MAX_LENGTH) {
      setValidation(
        `岗位名称不得超过 ${JD_SOURCE_NAME_MAX_LENGTH} 字符，岗位内容合计不得超过 ${JD_TEXT_MAX_LENGTH} 字符。`,
      );
      return;
    }
    setValidation(null);
    onGenerate({ jd_text: assembled, jd_source_name: name });
  };

  const sectionField = (
    key: keyof JDSections,
    label: string,
    placeholder: string,
  ) => (
    <label className="field-label">
      <span className="field-label-row">
        <span>{label}</span>
        <span className="field-hint">一行一条</span>
      </span>
      <Textarea
        modelValue={sections[key]}
        onUpdateModelValue={setSection(key)}
        placeholder={placeholder}
        rows={5}
        maxlength={JD_TEXT_MAX_LENGTH}
        disabled={disabled || busy}
      />
    </label>
  );

  return (
    <section className="surface-card jd-input" aria-labelledby="jd-input-title">
      <div className="section-heading compact">
        <p className="eyebrow">岗位输入</p>
        <h2 id="jd-input-title">填写岗位信息</h2>
        <p>{regenerating
          ? "修改只影响新计划和新面试，旧会话的岗位与资料快照保持不变。确认生成前不会发送请求。"
          : "岗位要求与候选资料分别入库；系统不会从简历猜测 JD。"}</p>
        <p className="field-hint">按分区逐行填写原岗位要求即可，分区标记由系统拼装；不要把加分项写成必备要求。</p>
        {initial.unassigned.length > 0 ? (
          <p className="field-hint" role="status">
            原文有 {initial.unassigned.length} 行不属于任何分区，未被自动归位；如需保留请手动加入下方分区。
          </p>
        ) : null}
      </div>
      <label className="field-label">
        岗位名称
        <Input
          modelValue={jobName}
          onUpdateModelValue={setJobName}
          placeholder="例如：嵌入式软件开发实习生"
          maxlength={JD_SOURCE_NAME_MAX_LENGTH}
          disabled={disabled || busy}
        />
      </label>
      {sectionField(
        "required",
        "必要项（必备要求）",
        "例如：熟悉 C 语言指针、结构体与位操作",
      )}
      {sectionField(
        "preferred",
        "加分项（优先条件）",
        "例如：有 CAN、DMA 实际调试经历",
      )}
      {sectionField(
        "responsibilities",
        "岗位职责",
        "例如：参与嵌入式固件模块开发与联调",
      )}
      <span className="character-count" aria-live="polite">
        拼装后 {assembled.length} / {JD_TEXT_MAX_LENGTH} 字符
      </span>
      <div className="button-row split-actions">
        <Button type="primary" size="large" loading={busy} disabled={disabled || busy} onClick={generate}>
          {regenerating ? "确认修改并生成新计划" : "根据岗位生成面试计划"}
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
          {regenerating ? "确认改用演示岗位生成新计划" : "使用演示岗位配置"}
        </Button>
        {onCancel ? <Button disabled={busy} onClick={onCancel}>取消修改，保留原计划</Button> : null}
      </div>
      {validation ? <p className="field-error" role="alert">{validation}</p> : null}
    </section>
  );
}
