import type { InterviewSlotView, JDRequirementView } from "../../api";
import { competencyDisplayName, materialStatusText, requirementTitle } from "../../presentation";

export function InterviewPlan({
  slots,
  requirements,
}: {
  slots: InterviewSlotView[];
  requirements: JDRequirementView[];
}) {
  return (
    <section className="plan-column" aria-labelledby="plan-title">
      <div className="section-heading compact">
        <p className="eyebrow">本场验证计划</p>
        <h2 id="plan-title">五个主问题方向</h2>
        <p>这里只列出验证方向；具体题目会在面试开始时现场生成。</p>
      </div>
      <ol className="slot-list">
        {slots.map((slot, index) => (
          <li key={slot.slot_id}>
            <span className="slot-number">{String(index + 1).padStart(2, "0")}</span>
            <div>
              <strong>{competencyDisplayName(slot.competency, index)}</strong>
              <p>
                {requirementTitle(requirements, slot.jd_requirement_ids)}
                {" · "}{materialStatusText(slot.current_verification_status)}
              </p>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}
