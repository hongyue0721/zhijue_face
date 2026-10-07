import { Tag } from "@any-design/anyui/react";
import type { InterviewSlotView, JDRequirementView } from "../../api";
import { competencyDisplayName, materialStatusText, requirementTitle, type CompetencyLabels } from "../../presentation";

const statusTone: Record<InterviewSlotView["current_verification_status"], string> = {
  supported: "success",
  claimed: "primary",
  unverified: "primary",
  unknown: "warn",
  contradicted: "danger",
};

export function InterviewPlan({
  slots,
  requirements,
  competencyLabels,
  notes = [],
}: {
  slots: InterviewSlotView[];
  requirements: JDRequirementView[];
  competencyLabels: CompetencyLabels;
  /** 服务端 limitations 的用户可读文本，例如同一能力为何出现两次。 */
  notes?: string[];
}) {
  return (
    <section className="interview-plan prepare-section" aria-labelledby="plan-title">
      <div className="section-title">
        <h2 id="plan-title">五个主问题方向</h2>
        <p>具体题目在开始面试后出现</p>
      </div>
      <ol className="slot-list">
        {slots.map((slot, index) => (
          <li key={slot.slot_id}>
            <span className="slot-number" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span>
            <div className="slot-body">
              <strong>{competencyDisplayName(slot.competency, competencyLabels)}</strong>
              <p>{requirementTitle(requirements, slot.jd_requirement_ids)}</p>
            </div>
            <Tag className={`status-tag--${statusTone[slot.current_verification_status]}`}>
              {materialStatusText(slot.current_verification_status)}
            </Tag>
          </li>
        ))}
      </ol>
      {notes.length ? (
        <details className="plan-notes compact-details">
          <summary>计划说明（{notes.length}）</summary>
          <ul>{notes.map((note) => <li key={note}>{note}</li>)}</ul>
        </details>
      ) : null}
    </section>
  );
}
