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
  if (key === "Home") return "reject";
  if (key === "End") return "accept";
  if (key === "ArrowLeft" || key === "ArrowUp") {
    if (current === "accept") return "neutral";
    if (current === "neutral") return "reject";
    return "reject";
  }
  if (key === "ArrowRight" || key === "ArrowDown") {
    if (current === "reject") return "neutral";
    if (current === "neutral") return "accept";
    return "accept";
  }
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
      error: `每次最多提交 ${maxLimit} 条，请先提交当前选择，再处理其余事实。`,
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
