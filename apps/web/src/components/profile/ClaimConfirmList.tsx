import { useState, type MouseEvent } from "react";
import { Button, Tag } from "@any-design/anyui/react";
import type { ClaimView } from "../../api";
import { SegmentedSlider } from "./SegmentedSlider";
import { FactModal } from "./FactModal";
import type { ClaimDecision } from "./claimDecisions";


function sourceLabel(claim: ClaimView): string {
  if (claim.source_quotes.some((quote) => quote.origin === "user_input")) {
    return claim.supersedes_id ? "本人更正（非材料原文）" : "本人补充（非材料原文）";
  }
  return claim.source_quotes.length ? "材料提取 · 待核实自述" : "来源待核实";
}

export function ClaimConfirmList({
  claims,
  confirmed,
  decisions,
  onDecision,
}: {
  claims: ClaimView[];
  confirmed: boolean;
  decisions: Record<string, ClaimDecision>;
  onDecision: (claimId: string, decision: ClaimDecision | null) => boolean;
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

  return (
    <section className="surface-card facts-section" aria-labelledby="facts-title">
      <div className="section-heading">
        <div className="facts-heading-text">
          <p className="eyebrow">资料事实核对</p>
          <h2 id="facts-title">{confirmed ? "已确认的信息" : "需要你核对的信息"}</h2>
        </div>
        <p className="facts-subtext">
          {confirmed
            ? "这些是你确认过的本人自述，面试中仍会核实；可以随时再次更正。"
            : "逐条选择采用、不采用或更正。选择会先暂存在页面上，选完后点下方“批量提交”一次性保存。"}
        </p>
      </div>

      {claims.length === 0 ? (
        <p className="claims-empty-state">
          {confirmed
            ? "暂无已确认事实。请核对上方待确认列表，或补充新的经历事实。"
            : "暂无待核对事实。可查阅已确认内容，或补充新的经历事实。"}
        </p>
      ) : (
        <div className="claim-list fact-review-list" role="list">
          {claims.map((claim) => {
            const decision = decisions[claim.id];
            const isCorrected = decision?.action === "correct";

            return (
              <article
                key={claim.id}
                className={`claim-card ${decision ? `claim-card--${decision.action}` : ""}`}
                role="listitem"
              >
                <div className="claim-main-row">
                  <div className="claim-content">
                    <div className="claim-meta-tags">
                      <Tag>{sourceLabel(claim)}</Tag>
                      {isCorrected ? (
                        <Tag className="tag-status-corrected">已暂存更正</Tag>
                      ) : decision?.action === "accept" ? (
                        <Tag className="tag-status-accept">已标记采用</Tag>
                      ) : decision?.action === "reject" ? (
                        <Tag className="tag-status-reject">已标记不采用</Tag>
                      ) : null}
                    </div>
                    <p className="claim-text">{claim.text}</p>
                  </div>

                  <div
                    className="button-row claim-actions"
                    role="group"
                    aria-label="事实处理操作"
                  >
                    {!confirmed && !isCorrected ? (
                      <SegmentedSlider
                        claimId={claim.id}
                        decision={decision}
                        onDecision={(next) => onDecision(claim.id, next)}
                      />
                    ) : null}

                    <Button
                      size="small"
                      type={isCorrected ? "primary" : "secondary"}
                      aria-label={isCorrected ? "重新编辑更正内容" : "更正该条事实描述"}
                      onClick={(event: MouseEvent<HTMLElement>) => {
                        const trigger = event.currentTarget;
                        setReturnFocusElement(
                          trigger.matches("button")
                            ? trigger
                            : trigger.querySelector("button") ?? trigger,
                        );
                        setEditingClaim(claim);
                      }}
                    >
                      {isCorrected ? "重新更正" : "更正"}
                    </Button>

                    {decision ? (
                      <Button
                        size="small"
                        type="secondary"
                        onClick={() => onDecision(claim.id, null)}
                        aria-label="撤销当前对该事实的选择"
                      >
                        {isCorrected ? "撤销更正" : "重置"}
                      </Button>
                    ) : null}
                  </div>
                </div>

                {isCorrected && decision.corrected_text ? (
                  <div className="claim-correction-preview">
                    <span className="preview-label">更正后的事实正文：</span>
                    <p className="preview-content">{decision.corrected_text}</p>
                  </div>
                ) : null}

                {claim.source_quotes.some((quote) => quote.exact_quote) ? (
                  <details className="claim-source-details">
                    <summary>查看出处精准引文</summary>
                    <div className="source-quotes-body">
                      {claim.source_quotes.map((quote, index) =>
                        quote.exact_quote ? (
                          <div key={index} className="source-quote-item">
                            <small>
                              {quote.origin === "user_input"
                                ? "本人补充 / 更正（非材料原文）"
                                : "材料原文"}
                            </small>
                            <blockquote>{quote.exact_quote}</blockquote>
                          </div>
                        ) : null,
                      )}
                    </div>
                  </details>
                ) : null}
              </article>
            );
          })}
        </div>
      )}

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
