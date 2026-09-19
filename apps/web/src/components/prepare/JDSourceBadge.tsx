import { Tag } from "@any-design/anyui/react";
import type { JDSourceView } from "../../api";
import { jdSourceText } from "../../presentation";

export function JDSourceBadge({ source }: { source: JDSourceView }) {
  return (
    <Tag className={`status-tag--${source.source_type === "synthetic_demo_jd" ? "warn" : "success"}`}>
      {jdSourceText(source)}
    </Tag>
  );
}
