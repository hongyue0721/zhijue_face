import { useState, type ReactNode } from "react";
import type { ImprovedAnswerView, ReportView } from "../../api";

type Segment = ImprovedAnswerView["segments"][number];

/** 在原回答里标出某段引用的逐字原话；找不到就原样显示，不猜测位置。 */
function markQuotes(text: string, quotes: string[]): ReactNode {
  const ranges = quotes
    .map((quote) => ({ start: text.indexOf(quote), length: quote.length }))
    .filter((range) => range.start >= 0 && range.length > 0)
    .sort((a, b) => a.start - b.start);
  if (!ranges.length) return text;
  const parts: ReactNode[] = [];
  let cursor = 0;
  ranges.forEach((range, index) => {
    if (range.start < cursor) return;
    parts.push(text.slice(cursor, range.start));
    parts.push(<mark key={index}>{text.slice(range.start, range.start + range.length)}</mark>);
    cursor = range.start + range.length;
  });
  parts.push(text.slice(cursor));
  return parts;
}

/**
 * 原回答与优化后对照。优化后的正文按服务端校验过的分段展示：点击一段，
 * 同时高亮它引用的原话，并列出它引用的已确认经历。分段与正文不一致时
 * （不应发生）退回整段展示，不在前端拼接或猜测出处。
 */
export function ImprovementComparison({
  improvement,
  sourceClaims,
  copyAction,
}: {
  improvement: ImprovedAnswerView;
  sourceClaims: ReportView["source_claims"];
  copyAction: ReactNode;
}) {
  const [active, setActive] = useState<number | null>(null);
  const segments = improvement.segments ?? [];
  const segmented = segments.length > 0
    && segments.map((segment) => segment.text).join("") === improvement.rewritten_answer;
  const activeSegment: Segment | null = segmented && active !== null ? segments[active] ?? null : null;
  const activeQuotes = (answerId: string) => activeSegment?.source_refs.flatMap((ref) =>
    ref.type === "answer_quote" && ref.answer_id === answerId ? [ref.exact_quote] : []) ?? [];
  const claimText = new Map(sourceClaims.map((claim) => [claim.id, claim.text]));
  const activeClaims = activeSegment?.source_refs.flatMap((ref) =>
    ref.type === "claim" ? [{ id: ref.claim_id, text: claimText.get(ref.claim_id) }] : []) ?? [];

  return (
    <>
      <div className="answer-comparison answer-reading-comparison">
        <div>
          <h3>原回答</h3>
          {improvement.original_answers.map((answer) => (
            <p key={answer.answer_id}>{markQuotes(answer.raw_text, activeQuotes(answer.answer_id))}</p>
          ))}
        </div>
        <div>
          <h3>优化后{segmented ? <span className="segment-hint">点一段，看它的出处</span> : null}</h3>
          {segmented ? (
            <p className="improved-segments">
              {segments.map((segment, index) => (
                <button
                  key={index}
                  type="button"
                  className={`improved-segment ${index === active ? "is-active" : ""}`}
                  aria-pressed={index === active}
                  onClick={() => setActive(index === active ? null : index)}
                >
                  {segment.text}
                </button>
              ))}
            </p>
          ) : (
            <p>{improvement.rewritten_answer}</p>
          )}
          {copyAction}
        </div>
      </div>
      {activeSegment ? (
        <section className="segment-sources" aria-live="polite" aria-label="这一段的出处">
          <h3>这一段的出处</h3>
          {activeSegment.source_refs.some((ref) => ref.type === "answer_quote") ? (
            <p className="segment-source-kind">你的原话（已在左侧标出）</p>
          ) : null}
          {activeClaims.length ? (
            <>
              <p className="segment-source-kind">你确认过的经历</p>
              {activeClaims.map((claim) => (
                <blockquote key={claim.id}>{claim.text ?? "这条经历的原文暂未返回，请刷新后再看。"}</blockquote>
              ))}
            </>
          ) : null}
        </section>
      ) : null}
    </>
  );
}
