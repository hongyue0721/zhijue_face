import { Tag } from "@any-design/anyui/react";
import { Icon } from "../common/icons";
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
      <h2 id="decision-title" className="visually-hidden">{reasonTitle}</h2>
      {decision ? (
        <dl className="context-list decision-list">
          <div>
            <dt>系统决定</dt>
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
      <p className="context-note">以上是系统的判断依据，不含模型的内部推理过程。</p>
    </aside>
  );
}

/**
 * 主问题出现时说明上一题为什么结束（换题 / 结束提问的结构化理由）。
 * 只读取 root_results 的 action 与 reason_summary，不展示模型内部推理。
 */
export function PreviousDecisionNote({
  interview,
  question,
}: {
  interview: InterviewView;
  question: QuestionView;
}) {
  if (question.kind !== "main") return null;
  const previous = [...interview.root_results]
    .reverse()
    .find((result) => result.root_question_id !== question.root_id);
  if (!previous) return null;
  return (
    <p className="decision-note" role="status">
      <Icon name="arrow-right" />
      <span>
        <strong>上一题：{actionText[previous.action]}</strong>
        {previous.reason_summary}
      </span>
    </p>
  );
}
