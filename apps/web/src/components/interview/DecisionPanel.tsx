import { Tag } from "@any-design/anyui/react";
import type { InterviewView, QuestionView, RootResultView } from "../../api";
import { actionText, followupIntentText } from "../../presentation";

function latestDecision(interview: InterviewView, question: QuestionView): RootResultView | null {
  return [...interview.root_results]
    .reverse()
    .find((result) => result.root_question_id === question.root_id) ?? null;
}

export function DecisionPanel({
  interview,
  question,
}: {
  interview: InterviewView;
  question: QuestionView;
}) {
  const decision = latestDecision(interview, question);
  const isClarification = question.kind === "clarification";
  const reasonTitle = isClarification ? "为什么需要澄清" : "为什么继续追问";
  const directionTitle = isClarification ? "澄清方向" : "追问方向";
  return (
    <aside className="context-panel decision-panel" aria-labelledby="decision-title">
      <p className="eyebrow">本题分析</p>
      <h2 id="decision-title">{reasonTitle}</h2>
      {decision ? (
        <dl className="context-list decision-list">
          <div>
            <dt>当前动作</dt>
            <dd><Tag className="status-tag--warn">{actionText[decision.action]}</Tag></dd>
          </div>
          <div>
            <dt>原因</dt>
            <dd>{decision.reason_summary}</dd>
          </div>
          <div>
            <dt>{directionTitle}</dt>
            <dd>{followupIntentText(decision.target?.followup_intent)}</dd>
          </div>
        </dl>
      ) : (
        <p className="empty-state">服务端尚未返回本题的结构化决策摘要。</p>
      )}
      <p className="context-note">这里只展示服务端可审计字段，不展示模型私有推理过程。</p>
    </aside>
  );
}
