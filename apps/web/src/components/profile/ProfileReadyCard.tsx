import { Button, Tag } from "@any-design/anyui/react";
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
    <section className="surface-card ready-card" aria-labelledby="profile-ready-title">
      <div>
        <Tag className="status-tag--success">Profile Snapshot Ready</Tag>
        <h2 id="profile-ready-title">资料版本已确认</h2>
        <p>已确认 {profile.confirmed_claims.length} 条事实。面试计划只读取这份服务端资料快照。</p>
        <p className="technical-id">服务端资料版本：<code>{profile.latest_snapshot_id}</code></p>
      </div>
      <Button type="primary" size="large" disabled={disabled} onClick={onContinue}>
        下一步：准备面试
      </Button>
    </section>
  );
}
