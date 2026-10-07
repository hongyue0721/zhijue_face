import { useState, type MouseEvent } from "react";
import { Button } from "../common/ui";
import type { ClaimView } from "../../api";
import { SegmentedSlider } from "./SegmentedSlider";
import { FactModal } from "./FactModal";
import type { BulkClaimAction, ClaimDecision } from "./claimDecisions";
import { groupClaimsBySection, type ClaimGroup } from "./claimGroups";

const decisionText: Record<ClaimDecision["action"], string> = {
  accept: "采用",
  reject: "不采用",
  correct: "更正",
};

function sourceLabel(claim: ClaimView): string {
  if (claim.source_quotes.some((quote) => quote.origin === "user_input")) {
    return claim.supersedes_id ? "本人更正（非材料原文）" : "本人补充（非材料原文）";
  }
  return claim.source_quotes.length ? "来自简历原文（本人自述，未经验证）" : "来源待确认";
}

export function ClaimConfirmList({
  claims,
  confirmed,
  decisions,
  onDecision,
  onBulkDecision,
}: {
  claims: ClaimView[];
  confirmed: boolean;
  decisions: Record<string, ClaimDecision>;
  onDecision: (claimId: string, decision: ClaimDecision | null) => boolean;
  onBulkDecision?: (claimIds: string[], action: BulkClaimAction | null) => boolean;
}) {
  const [editingClaim, setEditingClaim] = useState<ClaimView | null>(null);
  const [returnFocusElement, setReturnFocusElement] = useState<HTMLElement | null>(null);

  const handleSaveCorrection = (correctedText: string): boolean => {
    if (!editingClaim) return false;
    return onDecision(editingClaim.id, {
      claim_id: editingClaim.id,
      action: "correct",
      corrected_text: correctedText,
    });
  };

  const openCorrection = (claim: ClaimView, event: MouseEvent<HTMLElement>) => {
    const trigger = event.currentTarget;
    setReturnFocusElement(trigger.matches("button") ? trigger : trigger.querySelector("button") ?? trigger);
    setEditingClaim(claim);
  };

  if (claims.length === 0) {
    return (
      <section className="facts-section" aria-label={confirmed ? "已确认经历" : "经历核对"}>
        <p className="claims-empty-state">
          {confirmed
            ? "还没有已确认的经历。处理完待核对列表后会显示在这里。"
            : "待核对的经历都处理完了。可以查看已确认的经历，或再补充一条。"}
        </p>
      </section>
    );
  }

  return (
    <section className="facts-section" aria-label={confirmed ? "已确认经历" : "经历核对"}>
      {groupClaimsBySection(claims).map((group) => (
        <ClaimGroupSection
          key={group.section}
          group={group}
          confirmed={confirmed}
          decisions={decisions}
          onDecision={onDecision}
          onBulkDecision={onBulkDecision}
          onCorrect={openCorrection}
        />
      ))}

      {editingClaim ? (
        <FactModal
          returnFocusElement={returnFocusElement}
          mode="correct"
          isOpen={true}
          claimId={editingClaim.id}
          originalText={editingClaim.text}
          initialText={decisions[editingClaim.id]?.corrected_text ?? editingClaim.text}
          sourceQuotes={editingClaim.source_quotes}
          onSave={handleSaveCorrection}
          onClose={() => setEditingClaim(null)}
        />
      ) : null}
    </section>
  );
}

function ClaimGroupSection({
  group,
  confirmed,
  decisions,
  onDecision,
  onBulkDecision,
  onCorrect,
}: {
  group: ClaimGroup;
  confirmed: boolean;
  decisions: Record<string, ClaimDecision>;
  onDecision: (claimId: string, decision: ClaimDecision | null) => boolean;
  onBulkDecision?: (claimIds: string[], action: BulkClaimAction | null) => boolean;
  onCorrect: (claim: ClaimView, event: MouseEvent<HTMLElement>) => void;
}) {
  const ids = group.claims.map((claim) => claim.id);
  const selected = ids.filter((id) => decisions[id]).length;
  const clearable = ids.some((id) => decisions[id] && decisions[id].action !== "correct");
  const headingId = `claim-group-${group.section}${confirmed ? "-confirmed" : ""}`;
  return (
    <section className="claim-group" aria-labelledby={headingId}>
      <header className="claim-group__header">
        <h2 id={headingId}>
          {group.label}
          <span className="claim-group__count">
            {group.claims.length} 条{!confirmed && selected ? ` · 已选 ${selected}` : ""}
          </span>
        </h2>
        {!confirmed && onBulkDecision ? (
          <div className="claim-group__actions" role="group" aria-label={`${group.label}批量选择`}>
            <button type="button" className="text-action" onClick={() => onBulkDecision(ids, "accept")}>
              本组全部采用
            </button>
            <button type="button" className="text-action" onClick={() => onBulkDecision(ids, "reject")}>
              全部不采用
            </button>
            {clearable ? (
              <button type="button" className="text-action" onClick={() => onBulkDecision(ids, null)}>
                清除本组选择
              </button>
            ) : null}
          </div>
        ) : null}
      </header>
      <div className="claim-list" role="list">
        {group.claims.map((claim) => (
          <ClaimRow
            key={claim.id}
            claim={claim}
            confirmed={confirmed}
            decision={decisions[claim.id]}
            onDecision={onDecision}
            onCorrect={onCorrect}
          />
        ))}
      </div>
    </section>
  );
}

function ClaimRow({
  claim,
  confirmed,
  decision,
  onDecision,
  onCorrect,
}: {
  claim: ClaimView;
  confirmed: boolean;
  decision: ClaimDecision | undefined;
  onDecision: (claimId: string, decision: ClaimDecision | null) => boolean;
  onCorrect: (claim: ClaimView, event: MouseEvent<HTMLElement>) => void;
}) {
  const isCorrected = decision?.action === "correct";
  const hasSource = claim.source_quotes.some((quote) => quote.exact_quote);
  return (
    <article className={`claim-card ${decision ? `claim-card--${decision.action}` : ""}`} role="listitem">
      <div className="claim-main-row">
        <div className="claim-content">
          <p className="claim-text">{claim.text}</p>
          {isCorrected && decision.corrected_text ? (
            <div className="claim-correction-preview">
              <span className="preview-label">更正后：</span>
              <p className="preview-content">{decision.corrected_text}</p>
            </div>
          ) : null}
          <div className="claim-meta">
            {decision ? (
              <span className={`claim-decision-chip claim-decision-chip--${decision.action}`}>
                待提交：{decisionText[decision.action]}
              </span>
            ) : null}
            {hasSource ? (
              <details className="claim-source-details">
                <summary>查看来源</summary>
                <div className="source-quotes-body">
                  <p>{sourceLabel(claim)}</p>
                  {claim.source_quotes.map((quote, index) =>
                    quote.exact_quote ? (
                      <div key={index} className="source-quote-item">
                        <small>{quote.origin === "user_input" ? "本人补充 / 更正（非简历原文）" : "简历原文"}</small>
                        <blockquote>{quote.exact_quote}</blockquote>
                      </div>
                    ) : null,
                  )}
                </div>
              </details>
            ) : null}
          </div>
        </div>

        <div className="claim-actions" role="group" aria-label="事实处理操作">
          {!confirmed && !isCorrected ? (
            <SegmentedSlider
              claimId={claim.id}
              decision={decision}
              onDecision={(next) => onDecision(claim.id, next)}
            />
          ) : null}
          <Button
            size="small"
            type="text"
            aria-label={isCorrected ? "重新编辑更正内容" : "更正该条事实描述"}
            onClick={(event: MouseEvent<HTMLElement>) => onCorrect(claim, event)}
          >
            {isCorrected ? "重新更正" : "更正"}
          </Button>
          {isCorrected ? (
            <Button
              size="small"
              type="text"
              aria-label="撤销当前对该事实的选择"
              onClick={() => onDecision(claim.id, null)}
            >
              撤销更正
            </Button>
          ) : null}
        </div>
      </div>
    </article>
  );
}
