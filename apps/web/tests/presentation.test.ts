import { describe, expect, it } from "vitest";
import {
  competencyDisplayName,
  frozenCompetencyLabels,
  reportLimitationText,
  criterionDisplayName,
  criterionLevelText,
  dateTimeText,
} from "../src/presentation";

describe("report criterion labels", () => {
  it("omits the ordinal unless the same criterion kind repeats", () => {
    const label = criterionDisplayName("technical", null);
    expect(criterionDisplayName("technical", 2)).toBe(`${label}（2）`);
  });

  it("shows the level against the contract maximum and keeps null distinct from zero", () => {
    expect(criterionLevelText(2)).toBe("等级 2 / 3");
    expect(criterionLevelText(0)).toBe("等级 0 / 3");
    expect(criterionLevelText(null)).toBe("未形成等级");
  });
});

describe("timestamp presentation", () => {
  it("formats ISO timestamps to minutes and leaves unparsable values unchanged", () => {
    const local = new Date(2026, 9, 6, 14, 47, 37);
    expect(dateTimeText(local.toISOString())).toBe("2026-10-06 14:47");
    expect(dateTimeText("not-a-date")).toBe("not-a-date");
  });
});

describe("frozen competency labels", () => {
  const pack = {
    binding: "frozen" as const,
    pack_release_id: "kpr_0123456789abcdef",
    profile_version: "2.0.0",
    profile_digest: "sha256:profile",
    capabilities: [
      { competency_id: "python.mutable", label: "服务端定义的可变性能力" },
      { competency_id: "embedded.c.basics", label: "冻结版本自己的能力名称" },
    ],
  };

  it("takes labels from the frozen profile without a role-specific dictionary", () => {
    const labels = frozenCompetencyLabels(pack);
    for (const capability of pack.capabilities) {
      expect(competencyDisplayName(capability.competency_id, labels)).toBe(capability.label);
      expect(reportLimitationText(`检查 ${capability.competency_id}`, labels)).toBe(`检查 ${capability.label}`);
    }
    expect(competencyDisplayName("unregistered.capability", labels)).toBe("unregistered.capability");
    expect(competencyDisplayName("toString", labels)).toBe("toString");
  });

  it("does not guess labels before loading or when historical bindings are unavailable", () => {
    for (const value of [null, undefined, { ...pack, binding: "frozen_unavailable" as const }, { ...pack, binding: "legacy_unresolved" as const }]) {
      const labels = frozenCompetencyLabels(value);
      expect(labels).toEqual({});
      expect(competencyDisplayName("embedded.c.basics", labels)).toBe("embedded.c.basics");
      expect(reportLimitationText("embedded.c.basics", labels)).toBe("embedded.c.basics");
    }
  });
});
