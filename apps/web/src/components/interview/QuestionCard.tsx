import type { QuestionView } from "../../api";

const kindText: Record<QuestionView["kind"], string> = {
  main: "主问题",
  probe: "追问",
  clarification: "澄清",
};

export function QuestionCard({ question }: { question: QuestionView }) {
  return (
    <section className={`question-card question-card--${question.kind}`} aria-labelledby="current-question">
      <p className="question-kind">{kindText[question.kind]} · 第 {question.order_index + 1} 题</p>
      <h2 id="current-question">{question.wording}</h2>
    </section>
  );
}
