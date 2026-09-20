import { Tag } from "@any-design/anyui/react";
import type { InterviewView, QuestionView } from "../../api";
import {
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
  const basis = question.basis.basis_type === "resume"
    ? "材料中存在相关经历"
    : question.basis.basis_type === "gap"
      ? "材料未体现，等待回答核对"
      : "依据岗位要求进行核对";

  return (
    <aside className="context-panel" aria-labelledby="evidence-context-title">
      <p className="eyebrow">面试依据</p>
      <h2 id="evidence-context-title">为什么问这一题</h2>
      <dl className="context-list">
        <div><dt>岗位关联</dt><dd>{requirementTierText(requirements[0]?.tier)}</dd></div>
        <div>
          <dt>材料状态</dt>
          <dd><Tag className={`status-tag--${status === "supported" ? "success" : status === "contradicted" ? "danger" : status === "unknown" ? "warn" : "primary"}`}>{materialStatusText(status)}</Tag></dd>
        </div>
        <div><dt>验证方向</dt><dd>{direction}</dd></div>
      </dl>
      <p className="context-note">{basis}。未体现不代表不会，系统只记录本轮得到的可验证信息。</p>
    </aside>
  );
}
