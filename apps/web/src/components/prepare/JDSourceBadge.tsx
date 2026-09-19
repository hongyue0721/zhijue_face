import { Tag } from "@any-design/anyui/react";
import type { JDSourceView } from "../../api";
import { jdSourceText } from "../../presentation";

export function JDSourceBadge({ source }: { source: JDSourceView }) {
  const tone = source.source_type === "synthetic_demo_jd"
    ? "warn"
    : source.source_type === "user_provided"
      ? "primary"
      : "success";
  return <Tag className={`status-tag--${tone}`}>{jdSourceText(source)}</Tag>;
}
