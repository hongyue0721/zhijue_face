import { describe, expect, it } from "vitest";
import {
  calculateDecisionUpdate,
  decisionFromSliderTarget,
  sliderActionFromDecision,
  targetFromSliderKey,
} from "../src/components/profile/claimDecisions";
import type { ClaimDecision } from "../src/components/profile/claimDecisions";

describe("claimDecisions pure domain functions", () => {
  it("converts ClaimDecision to SliderAction correctly", () => {
    expect(sliderActionFromDecision(undefined)).toBe("neutral");
    expect(sliderActionFromDecision({ claim_id: "c1", action: "accept" })).toBe("accept");
    expect(sliderActionFromDecision({ claim_id: "c1", action: "reject" })).toBe("reject");
    expect(sliderActionFromDecision({ claim_id: "c1", action: "correct", corrected_text: "txt" })).toBe("neutral");
  });

  it("calculates key navigation transitions across discrete options", () => {
    // From accept (rightmost)
    expect(targetFromSliderKey("accept", "ArrowLeft")).toBe("neutral");
    expect(targetFromSliderKey("accept", "ArrowRight")).toBe("accept");

    // From neutral (middle)
    expect(targetFromSliderKey("neutral", "ArrowLeft")).toBe("reject");
    expect(targetFromSliderKey("neutral", "ArrowRight")).toBe("accept");

    // From reject (leftmost)
    expect(targetFromSliderKey("reject", "ArrowLeft")).toBe("reject");
    expect(targetFromSliderKey("reject", "ArrowRight")).toBe("neutral");
    expect(targetFromSliderKey("accept", "ArrowUp")).toBe("neutral");
    expect(targetFromSliderKey("reject", "ArrowDown")).toBe("neutral");
    expect(targetFromSliderKey("neutral", "Home")).toBe("reject");
    expect(targetFromSliderKey("neutral", "End")).toBe("accept");
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
