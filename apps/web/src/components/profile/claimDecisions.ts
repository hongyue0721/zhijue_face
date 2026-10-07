export type ClaimDecision = {
  claim_id: string;
  action: "accept" | "reject" | "correct";
  corrected_text?: string;
};

export const MAX_CLAIM_DECISIONS = 50;

export type SliderAction = "reject" | "neutral" | "accept";

export function sliderActionFromDecision(decision: ClaimDecision | undefined): SliderAction {
  if (decision?.action === "reject") return "reject";
  if (decision?.action === "accept") return "accept";
  return "neutral";
}

export function targetFromSliderKey(
  current: SliderAction,
  key: "ArrowLeft" | "ArrowRight" | "ArrowUp" | "ArrowDown" | "Home" | "End",
): SliderAction {
  if (key === "Home" || key === "ArrowLeft" || key === "ArrowUp") return "accept";
  if (key === "End" || key === "ArrowRight" || key === "ArrowDown") return "reject";
  return current;
}

export function decisionFromSliderTarget(
  claimId: string,
  target: SliderAction,
): ClaimDecision | null {
  if (target === "neutral") return null;
  return { claim_id: claimId, action: target };
}

export function calculateDecisionUpdate(
  current: Record<string, ClaimDecision>,
  claimId: string,
  nextDecision: ClaimDecision | null,
  maxLimit = MAX_CLAIM_DECISIONS,
): { decisions: Record<string, ClaimDecision>; error: string | null } {
  const isNewSelection = nextDecision !== null && !current[claimId];
  const currentCount = Object.keys(current).length;

  if (isNewSelection && currentCount >= maxLimit) {
    return {
      decisions: current,
      error: `每次最多提交 ${maxLimit} 条，请先提交当前选择，再处理其余经历。`,
    };
  }

  const next = { ...current };
  if (nextDecision) {
    next[claimId] = nextDecision;
  } else {
    delete next[claimId];
  }
  return { decisions: next, error: null };
}

export type BulkClaimAction = "accept" | "reject";

/**
 * 用户显式对一组事实批量选择（或清除）采用 / 不采用。
 * - 已暂存的“更正”是用户写过正文的独立动作，批量操作不覆盖、不清除；
 * - 超过单批上限时整组不生效，避免只选中半组造成误解；
 * - 只改变本地选择，提交前不写任何 API。
 */
export function calculateBulkDecisionUpdate(
  current: Record<string, ClaimDecision>,
  claimIds: string[],
  action: BulkClaimAction | null,
  maxLimit = MAX_CLAIM_DECISIONS,
): { decisions: Record<string, ClaimDecision>; error: string | null } {
  const next = { ...current };
  for (const claimId of claimIds) {
    if (current[claimId]?.action === "correct") continue;
    if (action === null) {
      delete next[claimId];
    } else {
      next[claimId] = { claim_id: claimId, action };
    }
  }
  const total = Object.keys(next).length;
  if (total > maxLimit) {
    return {
      decisions: current,
      error: `本组加上已选择的经历共 ${total} 条，超过每次 ${maxLimit} 条的提交上限。请先提交当前选择，再处理本组。`,
    };
  }
  return { decisions: next, error: null };
}
