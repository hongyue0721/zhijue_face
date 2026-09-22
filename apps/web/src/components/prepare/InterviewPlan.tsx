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
    <section className="plan-column prepare-section" aria-labelledby="plan-title">
      <div className="section-heading compact">
        <h2 id="plan-title">五个主问题方向</h2>

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
