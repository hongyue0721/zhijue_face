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
        <p className="empty-state">系统还没有给出这道题的分析依据。</p>
      )}
      <p className="context-note">这里展示的是系统做出这一决定的公开依据，不包含模型内部的思考原文。</p>
    </aside>
  );
}
