import { describe, expect, it } from "vitest";
import {
  calculateBulkDecisionUpdate,
  calculateDecisionUpdate,
  decisionFromSliderTarget,
  sliderActionFromDecision,
  targetFromSliderKey,
} from "../src/components/profile/claimDecisions";
import type { ClaimDecision } from "../src/components/profile/claimDecisions";
import { groupClaimsBySection } from "../src/components/profile/claimGroups";
import type { ClaimView } from "../src/api";

describe("claimDecisions pure domain functions", () => {
  it("converts ClaimDecision to SliderAction correctly", () => {
    expect(sliderActionFromDecision(undefined)).toBe("neutral");
    expect(sliderActionFromDecision({ claim_id: "c1", action: "accept" })).toBe("accept");
    expect(sliderActionFromDecision({ claim_id: "c1", action: "reject" })).toBe("reject");
    expect(sliderActionFromDecision({ claim_id: "c1", action: "correct", corrected_text: "txt" })).toBe("neutral");
  });

  it("navigates only the two visible choices without adopting untouched facts", () => {
    expect(sliderActionFromDecision(undefined)).toBe("neutral");
    expect(decisionFromSliderTarget("c1", "neutral")).toBeNull();
    for (const current of ["neutral", "accept", "reject"] as const) {
      for (const key of ["Home", "ArrowLeft", "ArrowUp"] as const) {
        expect(targetFromSliderKey(current, key)).toBe("accept");
      }
      for (const key of ["End", "ArrowRight", "ArrowDown"] as const) {
        expect(targetFromSliderKey(current, key)).toBe("reject");
      }
    }
  });

  it("maps slider target to discrete ClaimDecision without mutating correct semantics", () => {
    expect(decisionFromSliderTarget("c1", "neutral")).toBeNull();
    expect(decisionFromSliderTarget("c1", "accept")).toEqual({ claim_id: "c1", action: "accept" });
    expect(decisionFromSliderTarget("c1", "reject")).toEqual({ claim_id: "c1", action: "reject" });
  });

  it("updates decisions and enforces the 50 item batch limit without dropping state", () => {
    const current: Record<string, ClaimDecision> = {};
    for (let i = 0; i < 50; i++) {
      current[`claim_${i}`] = { claim_id: `claim_${i}`, action: "accept" };
    }

    // Adding 51st claim should fail and return error
    const overLimit = calculateDecisionUpdate(current, "claim_new", { claim_id: "claim_new", action: "accept" }, 50);
    expect(overLimit.error).toContain("最多提交 50 条");
    expect(Object.keys(overLimit.decisions).length).toBe(50);
    expect(overLimit.decisions["claim_new"]).toBeUndefined();

    // Modifying an existing item (e.g. correct or reject) should succeed within 50 limit
    const modifyExisting = calculateDecisionUpdate(
      current,
      "claim_0",
      { claim_id: "claim_0", action: "correct", corrected_text: "修改后内容" },
      50,
    );

    expect(modifyExisting.error).toBeNull();
    expect(modifyExisting.decisions["claim_0"]).toEqual({
      claim_id: "claim_0",
      action: "correct",
      corrected_text: "修改后内容",
    });

    // Removing an item decreases count
    const removeOne = calculateDecisionUpdate(current, "claim_0", null, 50);
    expect(removeOne.error).toBeNull();
    expect(removeOne.decisions["claim_0"]).toBeUndefined();
    expect(Object.keys(removeOne.decisions).length).toBe(49);
  });

  it("rejects a 51st correction if the 50 limit is already reached", () => {
    const current: Record<string, ClaimDecision> = {};
    for (let i = 0; i < 50; i++) {
      current[`claim_${i}`] = { claim_id: `claim_${i}`, action: "accept" };
    }

    // Attempting to correct a new unselected claim_51 should fail
    const correction = calculateDecisionUpdate(
      current,
      "claim_51",
      { claim_id: "claim_51", action: "correct", corrected_text: "新更正内容" },
      50,
    );
    expect(correction.error).toContain("最多提交 50 条");
    expect(correction.decisions["claim_51"]).toBeUndefined();
    expect(Object.keys(correction.decisions).length).toBe(50);
  });
});

describe("bulk group selection", () => {
  const ids = ["c1", "c2", "c3"];

  it("selects a whole group explicitly without overriding staged corrections", () => {
    const current: Record<string, ClaimDecision> = {
      c2: { claim_id: "c2", action: "correct", corrected_text: "本人更正" },
    };
    const accepted = calculateBulkDecisionUpdate(current, ids, "accept", 50);
    expect(accepted.error).toBeNull();
    expect(accepted.decisions).toEqual({
      c1: { claim_id: "c1", action: "accept" },
      c2: { claim_id: "c2", action: "correct", corrected_text: "本人更正" },
      c3: { claim_id: "c3", action: "accept" },
    });

    const cleared = calculateBulkDecisionUpdate(accepted.decisions, ids, null, 50);
    // 清除本组只撤销采用/不采用；用户写过正文的更正仍需单独撤销。
    expect(cleared.decisions).toEqual({
      c2: { claim_id: "c2", action: "correct", corrected_text: "本人更正" },
    });
  });

  it("applies nothing when the group would exceed the batch limit", () => {
    const current: Record<string, ClaimDecision> = {};
    for (let i = 0; i < 49; i++) current[`other_${i}`] = { claim_id: `other_${i}`, action: "accept" };
    const result = calculateBulkDecisionUpdate(current, ids, "reject", 50);
    expect(result.error).toContain("超过每次 50 条的提交上限");
    expect(result.decisions).toBe(current);
  });
});

describe("claim section grouping", () => {
  const claim = (id: string, section?: string): ClaimView => ({
    id, text: id, status: "proposed", source_block_ids: [], supersedes_id: null,
    source_quotes: section === undefined ? [] : [{ section, exact_quote: id }],
  });

  it("groups by first appearance and keeps server order inside each group", () => {
    const groups = groupClaimsBySection([
      claim("basic-1", "basic"),
      claim("project-1", "project"),
      claim("basic-2", "basic"),
      claim("unknown", "hobby"),
      claim("missing"),
      claim("project-2", "project"),
    ]);
    expect(groups.map((group) => [group.label, group.claims.map((item) => item.id)])).toEqual([
      ["基本信息", ["basic-1", "basic-2"]],
      ["项目与实践", ["project-1", "project-2"]],
      // 未知或缺失段落不按文字猜测，统一归入“其他信息”。
      ["其他信息", ["unknown", "missing"]],
    ]);
  });
});
