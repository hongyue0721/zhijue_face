import type {
  CoverageEntryView,
  InterviewPackSummary,
  InterviewView,
  JDRequirementView,
  JDSourceView,
  OperationStatus,
  PolicyAction,
  ReportCriterionResult,
  ResumeDraftView,
  RootAssessmentStatus,
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

export const interviewStatusText: Record<InterviewView["status"], string> = {
  preparing: "正在生成计划",
  prepare_failed: "计划生成失败",
  ready: "可以开始面试",
  active: "面试进行中",
  finishing: "提问已结束，报告整理中",
  finish_failed: "报告整理失败",
  completed: "面试已完成",
};

export const rootAssessmentStatusText: Record<RootAssessmentStatus, string> = {
  scored: "已完成评分",
  insufficient: "本次回答信息不足",
  disputed: "本次回答存在冲突",
  skipped: "本题已跳过",
  unmeasured: "本题未形成评价",
};

export const criterionKindText: Record<ReportCriterionResult["kind"], string> = {
  technical: "技术理解",
  expression: "表达完整性",
  evidence_reasoning: "证据与推理",
};

export const criterionFindingText: Record<ReportCriterionResult["finding"], string> = {
  supported: "回答中有依据",
  missing: "回答缺少关键信息",
  contradicted: "回答与参考依据冲突",
  not_assessable: "本轮信息不足，暂不评价",
  disputed: "回答中的证据相互冲突",
};

export const improvementsStatusText: Record<"not_requested" | "generating" | "ready" | "failed", string> = {
  not_requested: "尚未生成回答优化",
  generating: "回答优化生成中",
  ready: "回答优化已生成",
  failed: "回答优化生成失败",
};

export const resumeDraftStatusText: Record<ResumeDraftView["status"], string> = {
  generating: "草稿生成中",
  generation_failed: "草稿生成失败",
  draft: "草稿待确认",
  accepted: "草稿已确认",
};

export const resumeTargetKindText: Record<ResumeDraftView["target_context"]["kind"], string> = {
  interview: "本场面试岗位",
  jd_text: "当前岗位描述",
  generic: "通用岗位版本",
};

export function resumeTargetText(target: ResumeDraftView["target_context"]): string {
  const sourceName = target.source_name?.trim();
  return sourceName && sourceName !== "NO_TARGET"
    ? sourceName
    : resumeTargetKindText[target.kind];
}

export type CompetencyLabels = Readonly<Record<string, string>>;

/** 只读取本场冻结能力；列表中的当前岗位包不能重新解释历史面试。 */
export function frozenCompetencyLabels(pack?: InterviewPackSummary | null): CompetencyLabels {
  return pack?.binding === "frozen"
    ? Object.fromEntries(pack.capabilities.map(({ competency_id, label }) => [competency_id, label]))
    : {};
}

export function reportLimitationText(limitation: unknown, labels: CompetencyLabels): string {
  let text = typeof limitation === "string" ? limitation : "本场报告有一条注意事项";
  for (const [competency, label] of Object.entries(labels)) {
    text = text.replaceAll(competency, label);
  }
  // 服务端结构化理由里的领域词按用户视角改写，事实内容不变。
  return text
    .replaceAll("根题", "主问题")
    .replaceAll("JD 可用能力维度", "岗位可考察的能力方向")
    .replaceAll("槽位", "出题名额")
    .replaceAll("非按简历篇幅选择", "与简历长短无关");
}

const runModeText: Record<string, string> = {
  live: "实时模式",
  fixture: "演示数据",
  replay: "回放数据",
};

const dataModeText: Record<string, string> = {
  synthetic: "合成数据",
  user_confirmed: "用户确认资料",
};

/** live/fixture/replay 与数据模式必须对用户明示（负责人约束），明示的是中文事实，不是内部枚举值。 */
export function runtimeModeText(runMode: string, dataMode: string): string {
  const run = runModeText[runMode] ?? "未知运行模式";
  const data = dataModeText[dataMode] ?? "数据来源待确认";
  return `${run} · ${data}`;
}

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
  counterfactual: "条件变化下的调整",
  pushback: "回应反例或限制条件",
  reflection: "复盘与经验总结",
};

export function followupIntentText(intent?: string): string {
  if (!intent) return "围绕当前回答继续核对";
  return intentText[intent] ?? "围绕当前回答继续核对";
}

export function competencyDisplayName(competency: string, labels: CompetencyLabels): string {
  return Object.hasOwn(labels, competency) ? labels[competency] : competency;
}

/** 评分项名称；同一题出现多个同类评分项时才追加序号，避免序号被误读成分数。 */
export function criterionDisplayName(
  kind: ReportCriterionResult["kind"],
  ordinal: number | null,
): string {
  return ordinal === null ? criterionKindText[kind] : `${criterionKindText[kind]}（${ordinal}）`;
}

/** api.md §报告：可评分 criterion 的 level 取值 0—3。 */
export const CRITERION_MAX_LEVEL = 3;

export function criterionLevelText(level: ReportCriterionResult["level"]): string {
  return level === null ? "未形成等级" : `等级 ${level} / ${CRITERION_MAX_LEVEL}`;
}

const reviewDecisionTextMap: Record<string, string> = {
  approved: "审核通过",
  rejected: "审核未通过",
  unreviewed: "待技术审核",
};

/** 岗位知识包审核结论的中文；未登记的取值如实显示为待确认，不猜测。 */
export function reviewDecisionText(decision: unknown): string {
  return typeof decision === "string" && decision in reviewDecisionTextMap
    ? reviewDecisionTextMap[decision]
    : "审核结论待确认";
}

export function reviewerRoleText(role: unknown): string {
  return role === "owner" ? "负责人" : "审核人";
}

const validationStatusTextMap: Record<string, string> = {
  passed: "通过",
  failed: "未通过",
  not_run: "未执行",
};

export function validationStatusText(status: string): string {
  return validationStatusTextMap[status] ?? status;
}

const validationCheckTextMap: Record<string, string> = {
  structure: "文件结构",
  manifest: "包清单",
  competencies: "能力配置",
  seeds_schema: "题目种子格式",
  sources: "来源登记",
  content_digest: "内容摘要",
  review: "负责人审核",
};

/** 校验项名称；未登记的检查项保留原名，不自造含义。 */
export function validationCheckText(check: string): string {
  return validationCheckTextMap[check] ?? check;
}

/** ISO 时间按本地时区显示到分钟；无法解析时原样返回。 */
export function dateTimeText(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  const pad = (part: number) => String(part).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

export function scoreText(score: number | null, nullText: string): string {
  return score === null ? nullText : `${score} 分`;
}

export function jdSourceText(source: JDSourceView): string {
  switch (source.source_type) {
    case "synthetic_demo_jd":
      return "演示岗位配置";
    case "user_provided":
      return "用户提供岗位描述";
    case "official_posting":
      return "官方公开岗位";
    case "real_jd_derived":
      return "公开岗位衍生材料";
  }
}

export function interviewRoleText(interview: InterviewView): string {
  return interview.jd_source.source_type === "synthetic_demo_jd"
    ? interview.knowledge_pack.name ?? interview.jd_source.source_name
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
