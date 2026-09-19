import { Progress } from "@any-design/anyui/react";
import type { QuestionView } from "../../api";

export function InterviewProgress({
  total,
  question,
}: {
  total: number;
  question: QuestionView | null;
}) {
  const current = question ? Math.min(question.order_index + 1, total) : total;
  const label = question?.kind === "main"
    ? `主问题 ${current} / ${total}`
    : question?.kind === "probe"
      ? `补充问题 · 主问题 ${current} / ${total}`
      : question
        ? `澄清问题 · 主问题 ${current} / ${total}`
        : `本场提问完成 · ${total} / ${total}`;
  return (
    <div className="interview-progress">
      <div className="progress-copy"><strong>{label}</strong><span>共 {total} 个主问题</span></div>
      <div className="progress-dots" aria-label={label}>
        {Array.from({ length: total }, (_, index) => (
          <span
            key={index}
            className={index + 1 < current ? "complete" : index + 1 === current ? "active" : undefined}
          />
        ))}
      </div>
      <Progress value={total ? (current / total) * 100 : 0} />
    </div>
  );
}
