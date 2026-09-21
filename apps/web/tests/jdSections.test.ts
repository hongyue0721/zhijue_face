import { describe, expect, it } from "vitest";
import { assembleJdText, splitJdText } from "../src/jdSections";

describe("岗位分区序列化", () => {
  it("按固定顺序拼装并丢弃空行与首尾空白", () => {
    const text = assembleJdText({
      responsibilities: "  参与固件联调\n\n  编写测试用例  ",
      preferred: "",
      required: "熟悉 C 语言\n",
    });
    expect(text).toBe(
      "必要项：\n熟悉 C 语言\n\n岗位职责：\n参与固件联调\n编写测试用例",
    );
  });

  it("三个分区全空时返回空串，交给表单校验", () => {
    expect(assembleJdText({ required: " \n ", preferred: "", responsibilities: "" })).toBe("");
  });

  it("拼装结果可无损回填为同一分区结构（编辑路径幂等）", () => {
    const sections = {
      required: "熟悉 C 语言\n了解中断机制",
      preferred: "有 CAN 调试经历",
      responsibilities: "参与模块开发",
    };
    const roundTrip = splitJdText(assembleJdText(sections));
    expect(roundTrip).toEqual({ ...sections, unassigned: [] });
    expect(assembleJdText(roundTrip)).toBe(assembleJdText(sections));
  });

  it("标记之前的行进入 unassigned，不被自动归为必备要求", () => {
    const split = splitJdText("尽职尽责\n必要项：\n熟悉 C 语言");
    expect(split.unassigned).toEqual(["尽职尽责"]);
    expect(split.required).toBe("熟悉 C 语言");
    expect(split.preferred).toBe("");
  });

  it("无标记的旧文本不会被猜测分区", () => {
    const split = splitJdText("我们是一家公司，欢迎加入。");
    expect(split.unassigned).toEqual(["我们是一家公司，欢迎加入。"]);
    expect(split.required).toBe("");
  });
});
