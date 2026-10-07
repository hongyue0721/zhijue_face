import type { QuestionView } from "../../api";

export function InterviewProgress({
  total,
  question,
  started,
}: {
  total: number;
  question: QuestionView | null;
  started: boolean;
}) {
  // “没有当前题”有两种真相：还没开始，或已全部问完。混为一谈会把
  // ready 态面试渲染成“本场提问完成 5/5”，与页面其他状态自相矛盾。
  const finished = !question && started;
  const current = question ? Math.min(question.order_index + 1, total) : finished ? total : 0;
  const label = !question
    ? finished ? `本场提问完成 · ${total} / ${total}` : `尚未开始 · 0 / ${total}`
    : question.kind === "main"
      ? `第 ${current} / ${total} 题`
      : question.kind === "probe"
        ? `追问 · 第 ${current} / ${total} 题`
        : `澄清 · 第 ${current} / ${total} 题`;
  return (
    <div className="interview-progress">
      <div className="progress-copy"><strong>{label}</strong></div>
      <ol className="progress-steps" aria-label={label}>
        {Array.from({ length: total }, (_, index) => {
          const number = index + 1;
          const state = finished || number < current ? "complete" : number === current ? "active" : undefined;
          return <li key={number} className={state} aria-hidden="true">{number}</li>;
        })}
      </ol>
    </div>
  );
}
