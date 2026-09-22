import type { QuestionView } from "../../api";

export function QuestionCard({ question }: { question: QuestionView }) {
  return (
    <section className="question-card" aria-labelledby="current-question">
      <h2 id="current-question">{question.wording}</h2>
    </section>
  );
}
