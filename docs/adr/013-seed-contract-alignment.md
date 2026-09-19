# ADR-013｜Seed 契约对齐与 P0 动作集保持四动作

状态：PROPOSED（负责人未标记 ACCEPTED）  
日期：2026-09-18  
关联：SPEC-ALIGN、M2-01、R04/R05/R06、AGENTS §10 末段与 §11.4/§11.5

## 背景与约束

负责人 2026-09-18 追加约束要求：

1. Policy 第一版保持有限动作集 `CLARIFY / PROBE / CHALLENGE / NEXT / END`，不主动扩张（AGENTS §11.7）。
2. Seed 必须包含 competency、intent、difficulty、archetype、reference points、red flags、follow-up strategy、source/knowledge reference（AGENTS §11.8）。
3. Seed 两级审核：Level 1 检查 schema/source/competency/事实边界/follow-up 与 intent；Level 2 依据可靠技术资料审核 reference points（§11.5）。
4. 未获负责人确认前只能 `draft` 或 `reviewed`，不得自行 `approved`。

现有契约与此存在**两处真实冲突**：

| 冲突 | 现状证据 | 性质 |
|---|---|---|
| A：动作集 | `contracts/policy-decision.schema.json` 的 `action` 枚举只有 `CLARIFY/PROBE/NEXT/END`；`docs/04-workflow-policy.md` §5 明确「P0 只允许这四种，P1 再扩动作需要 ADR」；`tools/validate_spec.py` 有负例断言 "P0 没有 CHALLENGE 动作" | 追加约束要求增加 `CHALLENGE`；现有契约禁止 |
| B：Seed 字段 | `contracts/seed.schema.json` 有 `competency_id/intent/difficulty/archetype/rubric/followup_intents/reference_ids`，**没有** reference points / red flags / follow-up strategy 的显式字段；且 `followup_intents` 只是意图枚举，不能等价冒充 strategy | 追加约束要求的语义无字段承载 |
| C：审核状态 | `review_status` 枚举为 `draft/technical_review/approved/rejected/deprecated`，是**单级**流程；追加约束要求 Level 1 + Level 2 **两级**审核 | 枚举语义与两级流程不对应 |

按 AGENTS §10 末段："本轮不静默扩枚举、不把已有字段强行解释成满足新要求。对齐前不得批准相关业务实现或 Seed。"本 ADR 就是该对齐动作，需要负责人确认后才生效。

## 备选方案

### A：动作集

| 方案 | 优点 | 代价/失败路径 | 依据 |
|---|---|---|---|
| A1 保持四动作，CHALLENGE 作为 PROBE 的子意图 | 不改契约、不动事件 payload 与恢复逻辑、不新增预算语义；与 docs/04 §7 的反事实边界一致 | 与追加约束字面不一致 | docs/04 §5、§7；现有纯函数测试 |
| A2 立即增加 CHALLENGE 动作 | 字面满足追加约束 | 需同步改 policy schema、operation-event payload 枚举、docs/04 优先级表、恢复逻辑与全部策略测试；且 CHALLENGE（质疑用户陈述）与 §2 的"证据冲突保留、不自动扣分"需要额外语义定义，存在把"冲突"误用为"质疑"的风险 | 追加约束 §11.7 |
| A3 契约预留 CHALLENGE 但不启用 | 表面兼容 | 违反"不把特例伪装成通用能力"；枚举存在即会被调用 | — |

### B/C：Seed 字段与两级审核

| 方案 | 优点 | 代价/失败路径 | 依据 |
|---|---|---|---|
| B1 显式新增字段并在 Schema 中承载两级审核 | 语义可校验，审核可追溯，不靠文档约定 | 需改 Schema + 3 个示例 + 校验器负例 | 追加约束 §11.5/§11.8 |
| B2 把 reference_points 塞进 `prerequisites`、red flags 塞进 `out_of_scope` | 不改 Schema | 语义混杂：`prerequisites` 是"答题前提"，`out_of_scope` 是"禁止评价范围"，都不是"参考要点/需核对信号"；属于典型的最小修复与语义降格 | 禁止（AGENTS 核心理念） |
| C1 `review_status` 保留单级枚举，新增独立的两级审核记录字段 | 不改既有枚举语义，避免与 `technical_review` 混用 | 需新增字段与示例 | 追加约束 §11.5 |

## 决定

**采用 A1 + B1 + C1。**

理由：A1 保持 P0 已冻结的四动作契约，把 CHALLENGE 的语义需求映射到既有 `PROBE` + `followup_intents.counterfactual`，与 docs/04 §7 已定义的反事实边界完全一致；B1/C1 用**显式字段**承载新增语义，而不是让已有字段冒充新语义。三条都遵守"不静默改契约、不为通过校验放宽标准"。

具体契约变更（待负责人确认后实施）：

1. `contracts/seed.schema.json` 新增三个属性：
   - `reference_points`：数组，元素为 `{point_id, statement, kind: technical|acceptable_alternative, reference_ids[]}`。**每条 technical 类型必须有非空 `reference_ids`**，否则无法证明不是模型知识（AGENTS §5）。
   - `red_flags`：数组，元素为 `{signal_id, pattern, requires_followup: true, note}`。Schema 层强制 `requires_followup` 恒为 `true`，从结构上阻止"red flag → 自动扣分"（docs/05 §6）。
   - `follow_up_strategy`：对象 `{max_followups, preferred_intents[], stop_conditions[]}`，与 `followup_intents` 并存：前者是策略，后者是允许意图集合。
2. 新增两级审核字段：
   - `review_levels`：对象 `{level1: {status, reviewer_role, checked[], at}, level2: {status, reviewer_role, checked[], at}}`；
   - `review_status` 保留，但其 `approved` 只允许在 `review_levels.level1.status == "passed" && level2.status == "passed"` 时出现（Schema 条件约束）；
   - 新增 `reviewed` 值？**不新增**。`reviewed` 与现有 `technical_review` 会造成两套并行语义，故统一为：`draft → technical_review（=Level 1 通过、Level 2 待做）→ approved（=两级均通过）/ rejected`。此映射写入 docs/05 §8，避免"混用"。
3. `contracts/policy-decision.schema.json`：**不变**。CHALLENGE 的语义由本 ADR 记录为 `PROBE + counterfactual`，并在 docs/04 §5/§7 补一段显式说明，避免后续误以为遗漏。

影响文件：`contracts/seed.schema.json`、`examples/seed_*.json`（3 个）、`examples/validation-map.json`（如需）、`tools/validate_spec.py`（两级审核负例、reference_points 必带来源负例）、`docs/05-knowledge-and-bank.md` §6/§8、`docs/04-workflow-policy.md` §5/§7、`process.md`。

验证门槛：
- 三条既有 seed 示例通过新 Schema；
- 新负例全部被拒：① technical reference_point 无 reference_ids；② `requires_followup: false` 的 red flag；③ `review_status=approved` 而 level2 未 passed；
- 校验器总数上升且全绿；`docs/07` 记录负例。

回退方案：Schema/示例/校验器改动可整体回退（新增字段为可选→改为必填是本次唯一破坏性变更，回退即恢复可选与旧示例）。

何时重开：负责人确认要**真的启用**独立 CHALLENGE 动作（而非 PROBE 子意图）时，按方案 A2 走新 ADR，并同步事件 payload 与策略测试。

负责人确认（若需要）：需要。本 ADR 为 PROPOSED；在获确认前，Seed 一律不得写 `approved`，`review_levels` 只填 Level 1 结果时 `review_status` 最多 `technical_review`。
