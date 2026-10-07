import { Tag } from "@any-design/anyui/react";
import type { InterviewView, QuestionView } from "../../api";
import {
  competencyDisplayName,
  frozenCompetencyLabels,
  materialStatusText,
  requirementsFor,
  requirementTierText,
  requirementTitle,
} from "../../presentation";

export function EvidencePanel({
  interview,
  question,
}: {
  interview: InterviewView;
  question: QuestionView;
}) {
  const slot = interview.root_plan.slots[question.order_index];
  const requirementIds = question.basis.jd_requirement_ids ?? slot?.jd_requirement_ids ?? [];
  const requirements = requirementsFor(interview.jd_requirements, requirementIds);
  const direction = requirementTitle(interview.jd_requirements, requirementIds);
  const status = question.basis.current_verification_status ?? slot?.current_verification_status;
  const competency = question.basis.competency_id ?? slot?.competency;
  const competencyLabel = question.basis.competency_label
    ?? (competency ? competencyDisplayName(competency, frozenCompetencyLabels(interview.knowledge_pack)) : null);
  // 说明随出题依据变化：只有“材料未体现”时才需要强调“没写到不代表不会”。
  const basisNote = question.basis.basis_type === "resume"
    ? "简历里有相关经历，这道题用来核对细节和你本人负责的部分。"
    : question.basis.basis_type === "gap"
      ? "简历里没有写到相关内容。没写到不代表不会，请用你的实际经历来说明。"
      : "这道题依据岗位要求出题，用来核对相关能力。";

  return (
    <aside className="context-panel" aria-labelledby="evidence-context-title">
      <h2 id="evidence-context-title" className="visually-hidden">为什么问这一题</h2>
      <dl className="context-list">
        {competencyLabel ? <div><dt>考察能力</dt><dd>{competencyLabel}</dd></div> : null}
        <div><dt>要求类型</dt><dd>{requirementTierText(requirements[0]?.tier)}</dd></div>
        <div>
          <dt>简历情况</dt>
          <dd><Tag className={`status-tag--${status === "supported" ? "success" : status === "contradicted" ? "danger" : status === "unknown" ? "warn" : "primary"}`}>{materialStatusText(status)}</Tag></dd>
        </div>
        <div><dt>对应要求</dt><dd>{direction}</dd></div>
      </dl>
      <p className="context-note">{basisNote}评价只依据你在本轮给出的回答。</p>
    </aside>
  );
}
