import { Button, Tag, Textarea } from "@any-design/anyui/react";
import type { ClaimView } from "../../api";

export type ClaimDecision = {
  claim_id: string;
  action: "accept" | "reject" | "correct";
  corrected_text?: string;
};

function sourceLabel(claim: ClaimView): string {
  if (claim.source_quotes.some((quote) => quote.origin === "user_input")) {
    return claim.supersedes_id ? "本人更正（不是材料原文）" : "本人补充（不是材料原文）";
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
  onDecision: (claimId: string, decision: ClaimDecision | null) => void;
}) {
  return (
    <section className="surface-card facts-section" aria-labelledby="facts-title">
      <div className="section-heading">
        <p className="eyebrow">资料事实</p>
        <h2 id="facts-title">{confirmed ? "已确认的信息" : "需要你确认的信息"}</h2>
        <p>{confirmed ? "已确认仍是你的自述，不等于能力已获验证。更正后保留为用户输入来源。" : "逐条选择处理方式；选择和编辑不会立即保存，需点击批量提交。"}</p>
      </div>
      {claims.length === 0 ? (
        <p className="claims-empty-state">{confirmed ? "还没有已确认事实。请确认待确认内容，或填写经历。" : "没有待确认事实。可回看已确认内容；若已全部不采用，请重新填写经历。"}</p>
      ) : (
        <div className="claim-list fact-review-list">
          {claims.map((claim) => {
            const decision = decisions[claim.id];
            // aria-pressed 的切换语义必须真实：再点已选中的动作 = 取消该条选择。
            // “更正”尤其不能重置——用户已输入的更正正文丢失是数据事故。
            const decide = (action: ClaimDecision["action"]) => {
              if (decision?.action === action) {
                onDecision(claim.id, null);
                return;
              }
              onDecision(claim.id, action === "correct"
                ? { claim_id: claim.id, action, corrected_text: claim.text }
                : { claim_id: claim.id, action });
            };
            return (
              <article key={claim.id} className="claim-card">
                <div className="claim-main-row">
                  <div className="claim-content">
                    <Tag>{sourceLabel(claim)}</Tag>
                    <p>{claim.text}</p>
                  </div>
                  <div className="button-row claim-actions" role="group" aria-label="选择事实处理方式">
                    {!confirmed ? (
                      <>
                        <Button type={decision?.action === "accept" ? "primary" : "secondary"} aria-pressed={decision?.action === "accept"} onClick={() => decide("accept")}>采用</Button>
                        <Button type={decision?.action === "reject" ? "primary" : "secondary"} aria-pressed={decision?.action === "reject"} onClick={() => decide("reject")}>不采用</Button>
                      </>
                    ) : null}
                    <Button type={decision?.action === "correct" ? "primary" : "secondary"} aria-pressed={decision?.action === "correct"} onClick={() => decide("correct")}>更正</Button>
                    {decision ? <Button type="secondary" onClick={() => onDecision(claim.id, null)}>{decision.action === "correct" ? "取消编辑" : "取消选择"}</Button> : null}
                  </div>
                </div>
                {decision?.action === "correct" ? (
                  <label className="field-label claim-correction">
                    更正正文（保存为本人更正，不是材料原文）
                    <Textarea modelValue={decision.corrected_text ?? ""} onUpdateModelValue={(text: string) => onDecision(claim.id, { ...decision, corrected_text: text })} rows={4} maxlength={2000} />
                  </label>
                ) : null}
                {claim.source_quotes.some((quote) => quote.exact_quote) ? (
                  <details className="claim-source-details">
                    <summary>查看来源正文</summary>
                    {claim.source_quotes.map((quote, index) => quote.exact_quote ? (
                      <div key={index}>
                        <small>{quote.origin === "user_input" ? "本人补充 / 更正（不是材料原文）" : "材料原文"}</small>
                        <blockquote>{quote.exact_quote}</blockquote>
                      </div>
                    ) : null)}
                  </details>
                ) : null}
              </article>
            );
          })}
        </div>
      )}
    </section>
  );
}
