import { Button } from "@any-design/anyui/react";
import { useState } from "react";
import { setTemporaryDraftsEnabled, temporaryDraftsEnabled } from "../../temporaryDrafts";

export function TemporaryDraftNotice({ restored, storageAvailable, disabled, onStorageChange, onClear }: {
  restored: boolean;
  storageAvailable: boolean;
  disabled: boolean;
  onStorageChange: (available: boolean) => void;
  onClear: () => void;
}) {
  const [enabled, setEnabled] = useState(temporaryDraftsEnabled);
  return (
    <div className="temporary-draft-notice">
      <label className="temporary-draft-choice">
        <input type="checkbox" checked={enabled} disabled={disabled} onChange={(event) => {
          const next = event.currentTarget.checked;
          setEnabled(next);
          onStorageChange(setTemporaryDraftsEnabled(next));
        }} />
        在本标签页临时保存未提交的岗位和回答，便于刷新恢复（可选）
      </label>
      <p className="field-hint" role="status">
        {!storageAvailable
          ? "浏览器临时存储不可用，无法确认保存或清除；当前文字仅在页面内保留。请勿依赖刷新恢复；需要彻底移除旧副本时请清除此站点的浏览器数据。"
          : enabled
            ? `${restored ? "已恢复本标签页暂存的文字。" : "已开启本标签页临时保存。"}不跨设备同步；浏览器恢复标签页时可能一并恢复，请在共用设备上主动清除。`
            : "未开启浏览器暂存：应用内往返保留文字，刷新可能丢失。开启后仅使用本标签页 sessionStorage，不使用长期本地存储。"}
      </p>
      <Button type="text" size="small" disabled={disabled} onClick={onClear}>清除当前草稿</Button>
    </div>
  );
}
