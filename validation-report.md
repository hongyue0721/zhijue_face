# 文档包静态校验记录

校验性质：规范资产检查，不是业务软件验收。

结果：**44/44 项通过；0 项失败。**

实际命令：`python tools/validate_spec.py`

环境：Python 3.11.16；jsonschema 4.26.0；PyYAML 6.0.3。

这是文档校验环境，不是要求应用改用此 Python 版本。业务环境仍按 M0 核验 Python 3.11。

| 检查 | 结果 | 说明 |
|---|---|---|
| 关键文件存在 | PASS | 11 项存在 |
| UTF-8 与 LF | PASS | 156 文件检查通过 |
| Markdown 本地链接 | PASS | 24 条路径存在 |
| 来源编号 | PASS | 引用 14 种；登记 30 种；未登记 [] |
| 需求和测试编号 | PASS | 需求 19，测试 34；未知 [] |
| 任务依赖无悬空/环 | PASS | 18 个任务，无环 |
| 任务状态与证据一致 | PASS | 18 个任务状态合法且完成项均带产物说明 |
| Schema: claim.schema.json | PASS | Draft 2020-12 结构合法 |
| Schema: interview-slot.schema.json | PASS | Draft 2020-12 结构合法 |
| Schema: observation.schema.json | PASS | Draft 2020-12 结构合法 |
| Schema: operation-event.schema.json | PASS | Draft 2020-12 结构合法 |
| Schema: policy-decision.schema.json | PASS | Draft 2020-12 结构合法 |
| Schema: seed.schema.json | PASS | Draft 2020-12 结构合法 |
| 示例: seed_project_ownership.json | PASS | 结构通过；不是业务实测结果 |
| 示例: seed_measurement_scope.json | PASS | 结构通过；不是业务实测结果 |
| 示例: seed_rtos_shared_resource.json | PASS | 结构通过；不是业务实测结果 |
| 示例: claim.json | PASS | 结构通过；不是业务实测结果 |
| 示例: observation-supported.json | PASS | 结构通过；不是业务实测结果 |
| 示例: observation-unknown.json | PASS | 结构通过；不是业务实测结果 |
| 示例: policy-decision.json | PASS | 结构通过；不是业务实测结果 |
| 示例: operation-event.json | PASS | 结构通过；不是业务实测结果 |
| 示例: interview-slots-no-resume.json | PASS | 结构通过；不是业务实测结果 |
| 负例：未知项不能有等级 | PASS | not_assessable + level=3 必须拒绝 |
| 负例：禁止新增伪置信度 | PASS | 闭合对象拒绝未声明 confidence |
| 负例：策略动作有界 | PASS | P0 没有 CHALLENGE 动作 |
| 负例：未记录审核不能批准 | PASS | approved 不允许 null review_record_id |
| 负例：技术参考要点必须带来源 | PASS | technical 参考要点没有 reference_ids 时必须拒绝（模型知识不能充当技术结论） |
| 负例：red flag 不能自动扣分 | PASS | requires_followup 恒为 true，结构上禁止 red flag→扣分映射 |
| 负例：两级审核未完成不能批准 | PASS | Level 2 未通过时不允许 approved |
| 负例：technical_review 必须有 Level 1 结果 | PASS | technical_review 只表示 Level 1 已通过，不能空着 |
| 负例：追问上限不得超 P0 约束 | PASS | P0 每个根问题最多一次补充（docs/04 §8） |
| 种子引用可追溯 | PASS | 6 条种子的 reference_id 均映射到已登记来源 |
| 主演示外设种子平台来源闭合 | PASS | UART/DMA 与 SPI/I2C 技术要点均覆盖 F4/G4/H7 已登记来源 |
| 负例：unknown 槽位不得附证据 | PASS | 材料未体现的槽位必须 evidence 为空，避免把缺失写成有依据 |
| 负例：计划不得绑定未批准种子 | PASS | M2-02 阶段 seed_id 必须为 null（AGENTS §11.5） |
| 负例：计划不得含题目文本 | PASS | 五题计划只声明验证目标，题目由已批准种子库实例化 |
| 五题计划结构 | PASS | 5 个槽位 / 5 个能力维度 |
| 负例：事件 payload 同步动作枚举 | PASS | 拒绝未知事件动作 |
| Claim 原文定位 | PASS | 精确子串存在；语义支持另审 |
| Observation 原文定位 | PASS | 回答引用精确子串存在；不是技术真实性验证 |
| Demo 上限一致 | PASS | 5 主问题/1 补充/6→24 种子/10MiB/3 尝试/0.60 覆盖/3 根问题 |
| P1 默认未开启 | PASS | OCR、跨场记忆、Web、公网均关闭 |
| 本轮示例不冒充审核题库 | PASS | 三个题目种子均 draft |
| 密钥模板不含真实凭据 | PASS | API_KEY/EMBEDDING_API_KEY 留空，TLS 校验开启，无前端密钥变量与显式密钥值；不是完整安全扫描 |

## 本次没有执行

没有安装或运行 openJiuwen/Knowledge/Milvus 的业务组合；没有跑前后端 build、数据库迁移、浏览器 E2E 或真实模型；没有审核种子技术答案；没有部署国产操作系统；没有修改或推送用户仓库。

通过这些检查只证明文件路径、编号、Schema、示例和若干配置约束相互一致，不证明没有设计缺陷，也不证明 Demo 已经完成。人工设计复核和真实集成测试仍是后续里程碑。

校验器只扫描人写的规范资产：依赖树（node_modules/.venv）、vendored Node runtime（toolchain/node24）与运行期产物（runtime/）不参与，避免依赖自带文档造成假失败。

任务板检查已从规划期的“全部 PLANNED”基线改为施工期不变量：状态必须在枚举内，且 VERIFIED/ACCEPTED 必须带产物说明；不为通过校验把已完成任务退回 PLANNED。

本报告每次运行覆盖重写。业务验收状态以 process.md 与 docs/handoffs/ 为准，本报告不构成业务验收。
