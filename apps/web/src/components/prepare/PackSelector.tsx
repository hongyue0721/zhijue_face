import type { KnowledgePackList } from "../../api";
import { Alert } from "../common/ui";
import { Icon } from "../common/icons";

/**
 * 新面试的岗位知识包选择。只记录“下一次创建”的意图：
 * 已创建的面试永远使用受理时冻结的包，服务器提交时再次确认可用性。
 */
export function PackSelector({
  packs,
  packsError,
  selectedPackId,
  disabled,
  onSelect,
  onManage,
}: {
  packs: KnowledgePackList | null;
  packsError: unknown;
  selectedPackId: string | null;
  disabled: boolean;
  onSelect: (releaseId: string | null) => void;
  onManage: () => void;
}) {
  const defaultPack = packs?.items.find((item) => item.pack_release_id === packs.default_pack_release_id);
  const selectedPack = selectedPackId
    ? packs?.items.find((item) => item.pack_release_id === selectedPackId)
    : defaultPack;
  const defaultName = defaultPack?.name ?? (packsError ? "读取失败" : packs ? "暂无可用默认包" : "读取中…");
  return (
    <section className="pack-selector" aria-label="岗位知识包选择">
      <span className="pack-selector__icon" aria-hidden="true"><Icon name="book" /></span>
      <label className="pack-selector__field">
        <span className="pack-selector__label">本场岗位知识包</span>
        <select
          value={selectedPackId ?? ""}
          disabled={disabled}
          onChange={(event) => onSelect(event.target.value || null)}
        >
          <option value="">默认：{defaultName}</option>
          {(packs?.items ?? [])
            .filter((item) => item.selectable)
            .map((item) => (
              <option key={item.pack_release_id} value={item.pack_release_id}>
                {item.name} v{item.version}
              </option>
            ))}
        </select>
      </label>
      {selectedPack ? (
        <details className="compact-details">
          <summary>查看所选包的能力与规则</summary>
          <p>能力规则版本：{selectedPack.profile_version || "未提供"}</p>
          <p>规则审核：{selectedPack.rules_reviewed ? "负责人已审核当前规则" : "尚无当前规则的负责人审核事实"}</p>
          <p className="technical-value">规则摘要：{selectedPack.profile_digest || "未提供"}</p>
          <ul>
            {selectedPack.capabilities.map((capability) => (
              <li key={capability.competency_id}>{capability.label || capability.competency_id}</li>
            ))}
          </ul>
        </details>
      ) : null}
      <p className="pack-selector__hint">
        岗位能力与评分规则由所选包决定，填写 JD 不会另造评分规则；生成计划后本场固定使用该版本。
        <button type="button" className="text-action" onClick={onManage}>管理岗位知识包</button>
      </p>
      {packsError ? (
        <Alert type="warn" title="岗位知识包列表读取失败">
          暂时无法确认哪些知识包可选；仍可以用默认知识包生成，提交时服务器会再次校验。
        </Alert>
      ) : null}
    </section>
  );
}
