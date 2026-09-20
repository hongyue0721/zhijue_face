import { Button } from "@any-design/anyui/react";
import type { ProfileView } from "../../api";

export function ProfileReadyCard({
  profile,
  disabled,
  onContinue,
}: {
  profile: ProfileView;
  disabled: boolean;
  onContinue: () => void;
}) {
  if (!profile.latest_snapshot_id) return null;
  return (
    <section className="surface-card ready-card profile-ready-card" aria-labelledby="profile-ready-title">
      <div>
        <p className="eyebrow">准备完成</p>
        <h2 id="profile-ready-title">✓ 面试资料已确认</h2>
        <p>已确认 {profile.confirmed_claims.length} 条信息，可用于生成本场面试计划。</p>
        <details className="inline-technical-details">
          <summary>查看技术信息</summary>
          <p>服务端资料版本：<code>{profile.latest_snapshot_id}</code></p>
        </details>
      </div>
      <Button type="primary" size="large" disabled={disabled} onClick={onContinue}>
        进入面试准备
      </Button>
    </section>
  );
}
