# 文档同步、变更管理与跨会话续接

## 1. 单一真源

| 事实 | 真源 | 衍生项 |
|---|---|---|
| 需求/范围 | docs/01-prd.md 与已接受 ADR | 页面文案、计划书 |
| HTTP 语义/错误/幂等/SSE | 根 api.md | Pydantic DTO、实际 OpenAPI、生成 TS 类型、契约测试 |
| 领域意义 | docs/03-data-model.md | 表结构、迁移、实体 |
| Policy | docs/04-workflow-policy.md | 纯函数、参数、测试 |
| 当前实现进度 | process.md | 交接摘要与迭代说明 |
| 已发生变化 | CHANGELOG.md | 发布日志 |
| 业务上限 | config/demo.yaml | 环境加载、UI 限制、测试数据 |
| 外部规则/SDK 事实 | docs/14-sources-and-rules.md | 计划书中引用 |

实际代码与文档冲突时不是“文档说了算所以忽视线上”，也不是“代码能跑就抛弃规范”。停止当前变更，定位错误一方，更新契约/实现及测试，留痕。

## 2. 每类修改必须联动哪些文件

| 修改 | 必须同步 |
|---|---|
| 新增/修改 API | api.md、DTO/OpenAPI/TS 类型、前端消费端、契约测试、process、CHANGELOG |
| enum/状态迁移 | data-model、workflow-policy、Schema、迁移（如需）、所有 switch、恢复测试 |
| Prompt | Prompt 版本、变更理由、语义回归、process；影响输出结构还要改契约 |
| 题库/Rubric | seed version、来源审核、参考适用性、回归及报告元数据 |
| 模型/SDK 升级 | 环境锁、ADR、Knowledge smoke、结构化输出测试、成本/延迟记录 |
| 上传/OCR | UX 错误分支、配置、提取来源、删除、资源限制测试 |
| 新 P1/功能删除 | PRD、process 依赖、feature_flags、UI 可见性、演示说明、验收表 |
| 部署方式 | runbook、Docker/Compose、密钥/端口、备份恢复、目标 OS 记录 |

## 3. DRAFT → 实施的过程

开工先在 process 领取任务，并把接口/Schema 变更标 DRAFT，说明向后兼容性。实现与测试后改为 IMPLEMENTED/VERIFIED；负责人验收再 ACCEPTED。

DRAFT 接口不能被计划书说成已实现。计划中的 endpoints 在 api.md 有全局 PLANNED 标记；第一批实现后应改为按接口列状态，不继续保留“全部 PLANNED”的过时说明。

## 4. API 文档怎么维护

记录字段名、类型、必填、默认、长度、单位、空值语义、权限、状态条件、错误、幂等和事件。示例必须通过真实 DTO/JSON Schema 验证，不接受“文档里大概写一下”。

OpenAPI 由服务导出，不同时维护手写大文件；生成 TS 类型提交并在 CI 比较 diff。接口实现变化但 OpenAPI/文档未变，CI 或人工检查必须拦截。

SSE 事件独立做契约测试；不能只检验 HTTP 200 而不检查终态、seq、payload 和重连。

## 5. process.md 怎么维护

顶部始终保留：当前里程碑、模式、已验证能力、主要阻塞、下一项唯一任务。任务表列状态、依赖、证据路径、更新时间。旧日志可以归档，不能删除关键失败记录。

本轮没有 API 变化也在任务日志明确“API 无变化”。禁止为了满足同步要求给 api.md 填无意义时间戳，制造改动噪声；记录“已复核无变化”即可。

状态门槛：

`PLANNED` 尚未动工；`IN_PROGRESS` 已有工作；`BLOCKED` 有明确外部/技术阻塞；`IMPLEMENTED` 写完但未充分测；`VERIFIED` 实测通过附证据；`ACCEPTED` 负责人认可。

## 6. 交接最小内容

当前 branch/SHA、未提交改动、已读资料、任务结果、运行命令/返回码、失败样本、API/数据/配置变化、花费、下一步、不能重复的失败路径。

续接 AI 先读文档再看代码验证，不把上一轮“完成了”当作真相。不使用对话记忆替代仓库事实。不知道 API 是否支持就查实际定义。

## 7. 文档检查要求

M0 建立文档检查命令；至少检测本地 Markdown 文件链接、Schema JSON 合法性、示例校验、枚举一致性、需求编号存在、任务依赖引用、敏感信息和 case-only 文件名冲突。

以后每次提交跑文档检查、类型、单测、契约；涉及真实 SDK 或 Prompt 的变更追加 integration_live/语义回归。网络受限无法执行时标 NOT_RUN 并阻止把该项标 VERIFIED。

## 8. 文件命名与迁移

权威文件固定 root `api.md`、`process.md`。从旧项目迁入时，将 `docs/API.md` 的实际有用信息合并并更新；旧文档只留指向 root 的提示，不复制长期维护。跨 Windows/Linux 的大小写重命名使用临时名中转并检查 Git diff。

“规范计划书”和“比赛提交计划书”分开。比赛材料只从已实现证据与明确标注的规划章节生成，不自动把本规范全粘进去假装成果。
