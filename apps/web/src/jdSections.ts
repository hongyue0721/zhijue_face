/**
 * 岗位分区表单 ↔ 服务端 jd_text 的确定性序列化。
 *
 * 契约不变：`POST /interviews` 仍只收带显式分区标记的 `jd_text`
 * （api.md / docs/08 §分区规则）。分区标记由这里统一拼装，用户不再
 * 手写“必要项：”。切分只认三个规范标记；无法归行的文字进入
 * `unassigned` 并让用户决定，系统不猜分区、不静默升级加分项。
 */

export interface JDSections {
  required: string;
  preferred: string;
  responsibilities: string;
}

export interface SplitJDText extends JDSections {
  /** 出现在任何分区标记之前的行；不会被自动塞进某个分区。 */
  unassigned: string[];
}

const SECTION_DEFS = [
  { key: "required", marker: "必要项" },
  { key: "preferred", marker: "加分项" },
  { key: "responsibilities", marker: "岗位职责" },
] as const;

/** 把三个分区框拼成服务端要求的 jd_text；全空返回空串，由调用方校验。 */
export function assembleJdText(sections: JDSections): string {
  return SECTION_DEFS.map(({ key, marker }) => {
    const lines = sections[key]
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0);
    return lines.length > 0 ? `${marker}：\n${lines.join("\n")}` : null;
  })
    .filter((part): part is string => part !== null)
    .join("\n\n");
}

function isMarkerLine(line: string): (typeof SECTION_DEFS)[number] | null {
  for (const def of SECTION_DEFS) {
    if (line === `${def.marker}：` || line === `${def.marker}:`) return def;
  }
  return null;
}

/** 把已有 jd_text 回填成三个分区框的内容（编辑/重新生成路径）。 */
export function splitJdText(text: string): SplitJDText {
  const buckets: Record<keyof SplitJDText, string[]> = {
    required: [],
    preferred: [],
    responsibilities: [],
    unassigned: [],
  };
  let current: keyof JDSections | null = null;
  for (const rawLine of text.split("\n")) {
    const line = rawLine.trim();
    if (line.length === 0) continue;
    const marker = isMarkerLine(line);
    if (marker) {
      current = marker.key;
      continue;
    }
    (current ? buckets[current] : buckets.unassigned).push(line);
  }
  return {
    required: buckets.required.join("\n"),
    preferred: buckets.preferred.join("\n"),
    responsibilities: buckets.responsibilities.join("\n"),
    unassigned: buckets.unassigned,
  };
}
