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
  return (
    <aside className="context-panel decision-panel" aria-labelledby="decision-title">
      <p className="eyebrow">Decision Summary</p>
      <h2 id="decision-title">为什么继续追问</h2>
      {decision ? (
        <>
          <Tag className="status-tag--warn">{actionText[decision.action]}</Tag>
          <p className="decision-reason">{decision.reason_summary}</p>
          <dl className="context-list">
            <div>
              <dt>本轮意图</dt>
              <dd>{followupIntentText(decision.target?.followup_intent)}</dd>
            </div>
          </dl>
        </>
      ) : (
        <p className="empty-state">服务端尚未返回本题的结构化决策摘要。</p>
      )}
      <p className="context-note">这里只展示服务端可审计字段，不展示模型私有推理过程。</p>
    </aside>
  );
}
