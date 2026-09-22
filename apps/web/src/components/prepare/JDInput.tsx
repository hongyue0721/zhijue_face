import { Button, Input, Tag, Textarea } from "@any-design/anyui/react";
import { useMemo, useState } from "react";
import {
  JD_SOURCE_NAME_MAX_LENGTH,
  JD_TEXT_MAX_LENGTH,
  type CreateInterviewOptions,
} from "../../api";
import {
  assembleJdText,
  assignSectionLine,
  removeLineAt,
  splitJdText,
  type JDSections,
} from "../../jdSections";

const ASSIGN_TARGETS: { key: keyof JDSections; label: string }[] = [
  { key: "required", label: "必要项" },
  { key: "preferred", label: "加分项" },
  { key: "responsibilities", label: "岗位职责" },
];

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
  // 未分区原文必须可见、可归类；绝不静默丢弃（编辑旧 JD 时会发生数据丢失）。
  const [unassigned, setUnassigned] = useState<string[]>(initial.unassigned);
  const [validation, setValidation] = useState<string | null>(null);
  const assembled = assembleJdText(sections);
  const showCharacterCount = assembled.length >= JD_TEXT_MAX_LENGTH * 0.8;

  const setSection = (key: keyof JDSections) => (value: string) =>
    setSections((current) => ({ ...current, [key]: value }));

  const assignLine = (line: string, index: number, key: keyof JDSections) => {
    setSections((current) => assignSectionLine(current, key, line));
    setUnassigned((current) => removeLineAt(current, index));
    setValidation(null);
  };

  const generate = () => {
    const name = jobName.trim();
    if (unassigned.length > 0) {
      setValidation(
        `还有 ${unassigned.length} 行岗位原文没有归类。请把每一行归入上方分区，或明确删除不需要的行；不处理就无法生成，系统不会替你丢掉这些内容。`,
      );
      return;
    }
    if (!name || !assembled) {
      setValidation(
        "请填写岗位名称，并在必要项、加分项或岗位职责中至少填入一条。",
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
    <label className={`field-label jd-field-${key}`}>
      <span className="field-label-row">
        <span>{label}</span>

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
    <section className="jd-input continuous-form" aria-labelledby="jd-input-title">
      <h2 id="jd-input-title" className="visually-hidden">目标岗位</h2>
      {unassigned.length > 0 ? (
        <div className="jd-unassigned" role="group" aria-label="未归类的岗位原文">
          <p className="jd-unassigned-heading">
            有 {unassigned.length} 行原文不属于任何分区，需要你逐行安排；这些内容不会被自动归位，也不会被悄悄丢掉。
          </p>
          {unassigned.map((line, index) => (
            <div className="jd-unassigned-row" key={`unassigned-${index}-${line}`}>
              <span className="jd-unassigned-text">{line}</span>
              <span className="jd-unassigned-actions">
                {ASSIGN_TARGETS.map((target) => (
                  <Button
                    key={target.key}
                    size="small"
                    type="secondary"
                    disabled={disabled || busy}
                    onClick={() => assignLine(line, index, target.key)}
                  >
                    归入{target.label}
                  </Button>
                ))}
                <Button
                  size="small"
                  type="secondary"
                  disabled={disabled || busy}
                  onClick={() => setUnassigned((current) => removeLineAt(current, index))}
                >
                  删除该行
                </Button>
              </span>
            </div>
          ))}
          <Tag className="jd-unassigned-count">待处理 {unassigned.length} 行</Tag>
        </div>
      ) : null}
      <div className="jd-form-fields">
        <label className="field-label jd-job-name">
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
        <details className="jd-optional-fields" open={Boolean(initial.preferred || initial.responsibilities) || undefined}>
          <summary>加分项与岗位职责（选填）</summary>
          {sectionField("preferred", "加分项（优先条件）", "例如：有 CAN、DMA 实际调试经历")}
          {sectionField("responsibilities", "岗位职责", "例如：参与嵌入式固件模块开发与联调")}
        </details>
      </div>
      {showCharacterCount ? (
        <span className="character-count" aria-live="polite">
          岗位内容 {assembled.length} / {JD_TEXT_MAX_LENGTH} 字符
        </span>
      ) : null}
      <div className="button-row split-actions">
        <Button type="primary" size="large" loading={busy} disabled={disabled || busy} onClick={generate}>
          {regenerating ? "确认修改并生成新计划" : "根据岗位生成面试计划"}
        </Button>
        {onCancel ? <Button disabled={busy} onClick={onCancel}>取消修改，保留原计划</Button> : null}
      </div>
      {validation ? <p className="field-error" role="alert">{validation}</p> : null}
    </section>
  );
}
