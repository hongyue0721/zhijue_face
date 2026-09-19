import type {
  CoverageEntryView,
  InterviewView,
  JDRequirementView,
  JDSourceView,
  OperationStatus,
  PolicyAction,
} from "./api";

export const operationStatusText: Record<OperationStatus, string> = {
  queued: "已进入队列",
  running: "正在处理",
  succeeded: "处理完成",
  failed: "处理失败",
  interrupted: "处理被中断",
  canceled: "处理已取消",
};

export const coverageStatusText: Record<CoverageEntryView["status"], string> = {
  supported: "已有支持",
  claimed: "材料自述",
  unverified: "待验证",
  unknown: "材料未体现",
  contradicted: "材料存在冲突",
};

export const actionText: Record<PolicyAction, string> = {
  CLARIFY: "需要澄清",
  PROBE: "继续追问",
  NEXT: "进入下一题",
  END: "结束提问",
};

const intentText: Record<string, string> = {
  detail: "补充实现细节",
  verification: "补充验证方法",
  ownership: "核对个人贡献",
  evidence: "补充可核验证据",
  boundary: "确认能力边界",
  contradiction: "澄清材料冲突",
  clarification: "澄清指代或题意",
};

export function followupIntentText(intent?: string): string {
  if (!intent) return "围绕当前回答继续核对";
  return intentText[intent] ?? "围绕当前回答继续核对";
}

export function jdSourceText(source: JDSourceView): string {
  return source.source_type === "synthetic_demo_jd" ? "演示岗位材料" : "你提供的岗位材料";
}

export function interviewRoleText(interview: InterviewView): string {
  return interview.jd_source.source_type === "synthetic_demo_jd"
    ? "嵌入式软件开发实习生"
    : interview.jd_source.source_name;
}

export function requirementsFor(
  requirements: JDRequirementView[],
  requirementIds: string[],
): JDRequirementView[] {
  const ids = new Set(requirementIds);
  return requirements.filter((requirement) => ids.has(requirement.id));
}

export function requirementTitle(
  requirements: JDRequirementView[],
  requirementIds: string[],
): string {
  return requirementsFor(requirements, requirementIds)[0]?.statement ?? "岗位相关能力验证";
}

export function requirementTierText(tier?: JDRequirementView["tier"]): string {
  switch (tier) {
    case "required":
      return "核心岗位能力";
    case "preferred":
      return "优先能力";
    case "responsibility":
      return "岗位职责关联";
    case "contextual":
      return "岗位场景关联";
    default:
      return "岗位相关能力";
  }
}

export function materialStatusText(status?: CoverageEntryView["status"]): string {
  if (!status) return "材料状态待确认";
  return coverageStatusText[status];
}

export function coverageExplanation(entry: CoverageEntryView): string {
  if (entry.status === "unknown") return "材料未体现不代表不会，本轮将通过提问核对。";
  if (entry.status === "contradicted") return "材料中存在冲突信息，本轮将保留冲突并核对。";
  if (entry.relation === "related_context") return "材料存在相关上下文，尚不能当作直接能力证明。";
  if (entry.evidence_ids.length > 0) return "材料中有相关信息，仍需通过回答验证边界。";
  return entry.note || "本轮将通过回答补充可验证信息。";
}
