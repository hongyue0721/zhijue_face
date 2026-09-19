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
    <section className="facts-section" aria-labelledby="facts-title">
      <div className="section-heading">
        <p className="eyebrow">需要你的确认</p>
        <h2 id="facts-title">我们识别到这些候选事实</h2>
        <p>只有你明确确认的内容才会进入资料快照；不采用不会被当成能力不足。</p>
      </div>
      <div className="claim-list">
        {claims.map((claim) => (
          <article key={claim.id} className="claim-card">
            <Tag>{sourceLabel(claim)}</Tag>
            <p>{claim.text}</p>
            {claim.source_quotes[0]?.exact_quote ? (
              <blockquote>{claim.source_quotes[0].exact_quote}</blockquote>
            ) : null}
            <div className="button-row">
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
          </article>
        ))}
      </div>
    </section>
  );
}
