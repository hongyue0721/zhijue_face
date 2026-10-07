import type { ClaimView } from "../../api";

/** 服务端 source_quotes[].section 的受控取值（api.md / P-EXTRACT 契约）。 */
export const CLAIM_SECTION_LABELS = {
  basic: "基本信息",
  education: "教育经历",
  project: "项目与实践",
  skill: "专业技能",
  award: "获奖与证书",
  other: "其他信息",
} as const;

export type ClaimSection = keyof typeof CLAIM_SECTION_LABELS;

export type ClaimGroup = {
  section: ClaimSection;
  label: string;
  claims: ClaimView[];
};

export function claimSection(claim: ClaimView): ClaimSection {
  const section = claim.source_quotes[0]?.section;
  return section && section in CLAIM_SECTION_LABELS ? (section as ClaimSection) : "other";
}

/**
 * 按材料段落分组展示。组按服务端列表中首次出现的先后排列，组内保持服务端顺序；
 * 未知或缺失的段落归入“其他信息”，不按文字内容猜测归属。
 */
export function groupClaimsBySection(claims: ClaimView[]): ClaimGroup[] {
  const groups = new Map<ClaimSection, ClaimGroup>();
  for (const claim of claims) {
    const section = claimSection(claim);
    const group = groups.get(section);
    if (group) {
      group.claims.push(claim);
    } else {
      groups.set(section, { section, label: CLAIM_SECTION_LABELS[section], claims: [claim] });
    }
  }
  return [...groups.values()];
}
