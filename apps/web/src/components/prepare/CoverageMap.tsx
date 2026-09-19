import { Tag } from "@any-design/anyui/react";
import type { CoverageEntryView, JDRequirementView } from "../../api";
import {
  coverageExplanation,
  coverageStatusText,
  requirementTitle,
} from "../../presentation";

export function CoverageMap({
  entries,
  requirements,
}: {
  entries: CoverageEntryView[];
  requirements: JDRequirementView[];
}) {
  return (
    <section className="plan-column" aria-labelledby="coverage-title">
      <div className="section-heading compact">
        <p className="eyebrow">Coverage Map</p>
        <h2 id="coverage-title">岗位能力覆盖</h2>
        <p>状态来自确认资料与岗位要求的结构化映射，不等于最终能力结论。</p>
      </div>
      <div className="coverage-list">
        {entries.map((entry) => (
          <article className="coverage-row" key={entry.competency_id}>
            <div>
              <strong>{requirementTitle(requirements, entry.requirement_ids)}</strong>
              <p>{coverageExplanation(entry)}</p>
            </div>
            <Tag className={`status-tag--${entry.status === "supported" ? "success" : entry.status === "contradicted" ? "danger" : entry.status === "unknown" ? "warn" : "primary"}`}>
              {coverageStatusText[entry.status]}
            </Tag>
          </article>
        ))}
      </div>
    </section>
  );
}
