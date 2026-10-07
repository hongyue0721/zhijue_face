import { useState } from "react";
import { Button } from "./ui";
import { setTemporaryDraftsEnabled, temporaryDraftsEnabled } from "../../temporaryDrafts";

/**
 * 浏览器暂存是低频的可选项，默认收起，只在摘要里写明当前状态；
 * 恢复了草稿或存储不可用时自动展开，让用户看见需要知道的事实。
 */
export function TemporaryDraftNotice({ restored, storageAvailable, disabled, onStorageChange, onClear }: {
  restored: boolean;
  storageAvailable: boolean;
  disabled: boolean;
  onStorageChange: (available: boolean) => void;
  onClear: () => void;
}) {
  const [enabled, setEnabled] = useState(temporaryDraftsEnabled);
  const state = !storageAvailable ? "不可用" : enabled ? "已开启" : "未开启";
  return (
    <details className="temporary-draft-notice" open={restored || !storageAvailable || undefined}>
      <summary>
        刷新恢复（浏览器暂存）
        <span className={`temporary-draft-state ${enabled && storageAvailable ? "is-on" : ""} ${storageAvailable ? "" : "is-unavailable"}`}>
          {state}
        </span>
      </summary>
      <div className="temporary-draft-body">
        <label className="temporary-draft-choice">
          <input type="checkbox" checked={enabled} disabled={disabled} onChange={(event) => {
            const next = event.currentTarget.checked;
            setEnabled(next);
            onStorageChange(setTemporaryDraftsEnabled(next));
          }} />
          在当前标签页暂存还没提交的岗位和回答，刷新后可以恢复
        </label>
        <p className="field-hint" role="status">
          {!storageAvailable
            ? "浏览器临时存储不可用，刷新后文字可能丢失；如需彻底移除旧副本，请清除本站的浏览器数据。"
            : enabled
              ? `${restored ? "已恢复本标签页暂存的文字。" : "已开启本标签页临时保存。"}不跨设备同步；浏览器恢复标签页时可能一并恢复，共用电脑请用完后点“清除当前草稿”。`
              : "未开启：在本应用里切换页面不会丢字，但刷新页面可能丢失。开启后只保存在当前标签页，不写入长期存储。"}
        </p>
        <Button type="text" size="small" disabled={disabled} onClick={onClear}>清除当前草稿</Button>
      </div>
    </details>
  );
}
