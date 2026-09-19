import { Tag } from "@any-design/anyui/react";
import type { QuestionView } from "../../api";

const kindLabel: Record<QuestionView["kind"], string> = {
  main: "主问题",
  probe: "补充追问",
  clarification: "澄清问题",
};

export function QuestionCard({ question }: { question: QuestionView }) {
  return (
    <section className="question-card" aria-labelledby="current-question">
      <div className="question-card-heading">
        <Tag className={`status-tag--${question.kind === "main" ? "primary" : "warn"}`}>{kindLabel[question.kind]}</Tag>
        <span>请基于真实经历回答；不确定可以明确说不知道。</span>
      </div>
      <h1 id="current-question">{question.wording}</h1>
    </section>
  );
}
