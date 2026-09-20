import { Button, Tag } from "@any-design/anyui/react";
import type { ClaimView } from "../../api";

function sourceLabel(claim: ClaimView): string {
  const origin = claim.source_quotes[0]?.origin;
  if (origin === "user_input") return "手工补充";
  return origin ? "候选材料" : "来源待确认";
}

export function ClaimConfirmList({
  claims,
  busyClaimId,
  disabled,
  onDecision,
}: {
  claims: ClaimView[];
  busyClaimId: string | null;
  disabled: boolean;
  onDecision: (claimId: string, action: "accept" | "reject") => void;
}) {
  if (claims.length === 0) return null;
  return (
    <section className="surface-card facts-section" aria-labelledby="facts-title">
      <div className="section-heading">
        <p className="eyebrow">资料确认</p>
        <h2 id="facts-title">需要你确认的信息</h2>
        <p>只有你明确确认的内容才会进入资料快照；不采用不会被当成能力不足。</p>
      </div>
      <div className="claim-list">
        {claims.map((claim) => (
          <article key={claim.id} className="claim-card">
            <div className="claim-main-row">
              <div>
                <Tag>{sourceLabel(claim)}</Tag>
                <p>{claim.text}</p>
              </div>
              <div className="button-row claim-actions">
                <Button
                  type="primary"
                  loading={busyClaimId === claim.id}
                  disabled={disabled || busyClaimId !== null}
                  onClick={() => onDecision(claim.id, "accept")}
                >确认</Button>
                <Button
                  type="secondary"
                  disabled={disabled || busyClaimId !== null}
                  onClick={() => onDecision(claim.id, "reject")}
                >不采用</Button>
              </div>
            </div>
            {claim.source_quotes[0]?.exact_quote ? (
              <details className="claim-source-details">
                <summary>查看材料原文</summary>
                <blockquote>{claim.source_quotes[0].exact_quote}</blockquote>
              </details>
            ) : null}
          </article>
        ))}
      </div>
    </section>
  );
}
