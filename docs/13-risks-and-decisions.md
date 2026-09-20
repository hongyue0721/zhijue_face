# 风险登记与架构决策

## 决策状态

下列 ADR 是持续生效的架构基线；是否已落地及验证以 `process.md` 任务状态和最新 handoff 为准。影响费用、数据外发、开放访问、框架替换或题目合规性的偏离必须提请负责人。

| ADR | 决策 | 理由和后果 | 重开条件 |
|---|---|---|---|
| ADR-001 | 新建 Vite/React SPA，不复制整个旧平台 | 没有 SSR 需求；减少 Next.js API 与 Python 重叠。旧简历展示等组件可选移植 | 发现可直接复用且维护成本更低的完整界面；以实测工时证明 |
| ADR-002 | Python 为唯一业务持久化入口 | SQLite/SQLAlchemy 单一迁移真源；前端不使用 Drizzle | 真实多服务/多租户需求出现，而非为炫技 |
| ADR-003 | 真实 WorkflowAgent + 原生 Knowledge，具体 Lite 路线先验证 | 题目明确指定模块；版本和适配存在不确定性 | M0 失败，有最小复现、资源与合规替代对照 |
| ADR-004 | 一个面试 Agent，四类有界工作流 | 等待用户时不保持长运行图；业务状态可恢复 | 经验证必须使用原生中断恢复且能降低复杂度 |
| ADR-005 | 事实声明与本轮表现分离，不建概率能力模型 | 回答不是履历真实性审计；证据数不等于独立置信度 | 有标注集、校准方法和明确需求之后 |
| ADR-006 | 单岗位、6→24 条审核种子、五主问题 | 优先构成可靠闭环，不建万能题库 | 核心验收通过且增加岗位的资料审核能力充足 |
| ADR-007 | OCR 和长期记忆 P1 | Memory 为题面可选；扫描导入有明确降级路径 | P0 已通过并仍有稳定性/材料缓冲 |
| ADR-008 | 本地、合成资料、显式 live/fixture/replay | 不把演示便利变成真实性与隐私风险 | 负责人批准公网使用并完成认证/数据治理 |
| ADR-009 | SSE 先输出经校验的语义事件，不直接流模型 token | 避免未校验幻觉流到用户；恢复语义清楚 | 后期实现草稿显示、撤回/提交协议且有测试 |
| ADR-010 | 评分规则固定、缺证据可拒绝评分 | 降低模型自评漂移；覆盖不足不得捏造分数 | 有独立数据证明其他规则更合适 |

## 风险登记

| 编号 | 风险 | 级别 | 先行处理 | 失败后的诚实边界 |
|---|---|---|---|---|
| K01 | 校内报名已截止、上传项不明 | 阻塞 | 负责人当日确认通知及系统字段 | 不承诺可参赛；技术验证可单独进行 |
| K02 | 国产 OS 组别适配口径不明 | 阻塞 | 向校企联系人确认环境和材料形式 | Linux 开发成功不能当作特定国产系统验证 |
| K03 | SDK 发布版和 develop 文档导入不一致 | 高 | 固定 0.1.18 候选，实际导入与 smoke 后锁版本 | 不凭记忆编 API；必要时调整 ADR |
| K04 | Milvus Lite 与框架 Indexer/Store 部分不兼容 | 高（锁定组合已缓解） | 兼容 commit 已完成 FLAT/default 全生命周期 live；保持来源/hash/回归守卫 | 正式发布切换前不删除失败记录，不偷偷换成自建假 Knowledge |
| K05 | 模型格式不稳、延迟或限流 | 高 | 一个模型、严格契约、总重试预算、超时 | 保留回答，输出可恢复错误，不造默认 80 分 |
| K06 | 小题库错误或场景不适用 | 高 | 技术来源锁版本，审核替代答案及假设 | 未审核题不进 live，不以匹配关键词判错 |
| K07 | 资料抽取/截图 OCR 误读 | 高 | 文本优先、原文并排、人工确认、扫描降级 | 记录解析限制，不把错误永久写入记忆 |
| K08 | 不够懂领域而错误评价学生 | 高 | 无技术依据不判错；专家复核高风险题 | 只评价有依据的表达和推理，显示未验证 |
| K09 | 有效回答少，报一个很精确总分 | 高 | 覆盖门槛、null、分母披露、根题去重 | 没有总分也生成有用的逐题反馈 |
| K10 | API 重试和断线重复推进/扣费 | 高 | 幂等键、逻辑操作预算、event 恢复、单活跃任务 | 不能保证外部 API 完全不重复计费，要披露 |
| K11 | 前后端/多 AI 修改契约漂移 | 高 | api.md 与 schemas、生成类型、process 同步 | 不用 any/兼容分支掩盖不一致 |
| K12 | 合成演示被说成真实用户成效 | 高 | synthetic 标志、版本、录制模式分开 | 不作真实招聘效果或准确率宣称 |
| K13 | 敏感资料/API Key 泄露 | 高 | 默认假资料、服务端配置、日志脱敏、删除测试 | 未批准不接真实简历、不公网部署 |
| K14 | 一个开发者范围失控 | 高 | P0 阶段门、24 种子目标可裁剪、无 P1 抢跑 | 保留真正主链，缩小范围并如实报告 |
| K15 | 题目实际揭榜数量影响后续评审 | 外部 | 通过官方校企对接了解，不用第三方队伍数推断 | 不承诺评奖和晋级 |
| K22 | openJiuwen 0.1.18 无法处理 pymilvus delete 的 list 返回 | 已缓解 / 上游待发布 | 锁定基于 v0.1.18 + PR #1344 的 commit，回归与两次 live 已通过 | 不能宣称正式 0.1.18 wheel 已修；官方发布后切回并重跑 |

## K02 的具体处理

产业赛道方案描述国产操作系统软件组基于鸿蒙、麒麟、统信等国产操作系统，题目也归在该组。[S01][S02] 这不是自动要求你做鸿蒙手机 App，更不是“装 Linux 就满足”。负责人应问清：浏览器型应用是否接受；后端运行在哪个系统；是否需要视频、截图、设备或容器运行证明。

开发默认 Linux 可继续；提交前按答复选择一个现实可获取的目标环境，记录宿主系统/CPU 架构、容器基础镜像、SDK依赖、版本和主链测试。不能仅有浏览器在目标系统打开远端站点，就声称后端已原生适配。

## 关于候选替代方案

若 Lite 失败，先找出是版本、索引模式、数据库 API 还是框架调用假设。只在有记录时选：框架原生支持的其他本地后端，或本地 Milvus Standalone。新增容器和内存成本必须说明。自定义官方扩展接口可以研究，但要记录实现范围和来源并取得合规确认；不能通过继承同名类把普通 FTS 检索包装成“原生支持”。

## 关于 P1 记忆

业务表存训练弱项，不能自动宣称使用了 openJiuwen Memory。若 P1 宣传框架 Memory，必须另做该模块的真实写入、读取、删除和跨会话行为测试；若仅自建业务记忆，名称与架构图如实标注。两种方式都不得让一次错误抽取永久降低用户评价。

## 需要负责人批准的触发条件

新增付费 OCR/模型/服务器；发送真实简历给新供应商；开放公网；推送或删除用户仓库；改换指定框架；把单岗位扩为多岗位；把 P1 升为核心；更改事实和评分边界。一般函数划分、组件命名、测试文件安排不必事事打断负责人。


## M0-01 审计补记（2026-09-18）

- K04 历史：最初真实 SimpleKnowledgeBase 已通过解析/入库/检索/重启，但 delete 因 pymilvus list 返回兼容失败。随后 M0-03-DEL 锁定基于 v0.1.18 + PR #1344 的兼容 commit，已完成两次四进程删除及删除后重启验证；正式 0.1.18 wheel 的失败事实仍保留。
- K16：本地 BGE-small 方案已由负责人指定的远程 BAAI/bge-m3 取代；使用 SDK 自带 OpenAIEmbedding，无新增推理依赖。合成文本实测 1024 维。业务回答模型随后以 `deepseek-flash` 完成一次 synthetic live 分析；这解除“完全未运行”，不形成效果、p95 或成本结论。
- K17：0.1.18 官方 WorkflowAgent 依赖 legacy ControllerAgent/WorkflowAgentConfig。保留官方入口、锁版本并记录弃用警告；不假造替代类，不擅自迁移框架。
- K18 历史：规范校验器曾因任务状态假设和第三方扫描范围产生 28/31。范围和状态校验已修正，当前终态为 44/44；历史失败记录保留在 process，不再是现行 blocker。
- 已有 ADR-001—010 不重开；本轮验证范围见 [ADR-011](adr/011-workflow-smoke-scope.md)。外部 O01—O06 仍按 process.md 记录，不因本地技术测试而解除。


## 追加约束后的阻塞（2026-09-18）

| 编号 | 已确认 | 未确认与最小验证 |
|---|---|---|
| K19 / M0-BASE | NCSS 与 GitCode u-j8 题面要求真实 Knowledge/Agent Workflow；当前本地 SDK 为 0.1.18 | 已读页面未列专用 starter，但官方答疑帖子未读到，不能排除补充要求。取得官方模板/答疑/书面说明并核对宿主，未解决前不宣称基座合规或 M0 完成 |
| K20 / Policy 对齐 | ADR-013 已闭合：P0 保持 `CLARIFY / PROBE / NEXT / END`，CHALLENGE 语义用 `PROBE + counterfactual`；M3 程序 Policy 按该契约实现 | 当前无枚举冲突 blocker；以后变更动作集必须先同步 api.md/Schema/事件/测试 |
| K21 / Seed 对齐 | Schema 已显式包含 reference_points/red_flags/follow_up_strategy/review_levels；首批六条 Level 2 已由负责人 passed/approved | 当前首批门禁已解除；批准不外推到新增 Seed 或 24 条目标 |

阶段验收不得由施工 AI 写 ACCEPTED；ADR-011 已改 PROPOSED。详情及证据见本轮交接。


### K19 / K03 / K17 续核（2026-09-18）

- K19 仍 BLOCKED：定位到官方答疑只读接口，但匿名访问返回 HTTP 418；没有读取到正文，没有绕过拦截。GitHub 组织及三个仓库的公开目录核验没有补齐此事实缺口。需官方材料解阻，不用反复搜索的空结果替代确认。
- K03/K17 增加证据：当前 7 个 SDK 入口相关文件与锁定 wheel 一致，真实调用继续通过；官方仓库 commit 与发布 wheel 存在 2 个文件差异，通用 notebook 存在旧导入路径。风险为版本/文档不一致，不是本地冒充 SDK；保留当前锁，禁止照抄未支持参数。
- 没有因此重开架构、升级依赖或接受阶段；M0-BASE/Knowledge/模型门槛仍分别保留。

## M0-03 删除兼容阻塞与解除（2026-09-18—2026-09-19）

- 初始已确认：真实 `delete_documents` 进入官方 `MilvusIndexer.delete_index`；pymilvus 在成功删除且返回 primary keys 时给出 list，正式 openJiuwen 0.1.18 对非 dict 执行 `int(result)`，产生 TypeError 并返回 false。
- 上游事实：官方 PR #1344 描述并修复同一问题；截至 2026-09-19 仍为 Open，不能当成已发布版本能力。[S21]
- 已实施：基于官方 v0.1.18，仅应用 PR #1344 的两个提交，形成公开兼容 commit `72c4985111b835530ec616f70dd67117eb2e015c`；项目 pyproject/uv.lock 锁到该 commit。没有自定义 Knowledge、monkeypatch 或 site-packages 手改。[S23]
- 已验证：修复前回归失败、修复后回归通过，上游目标测试 21 passed；补丁 worktree 与项目锁定安装各完成一次四进程 full lifecycle，删除后重启均为 0 命中。
- 状态变化：项目锁定组合的 M0-03 为 VERIFIED；正式 0.1.18 wheel 缺陷仍保留为上游已知风险。API 无变化，未自行标记 ACCEPTED。

剩余风险与退出条件：

1. 当前首次依赖同步需要访问公开 Git fork，部署难度较 PyPI wheel 略高；锁定 commit 可防分支漂移，但仓库可用性仍是外部依赖。
2. 兼容 commit 的 GitHub commit verification 字段为 false；本项目通过官方 tag 基线、精确两文件 diff、源码 hash、单测和两次 live 做了独立完整性验证，不能把它描述为官方签名发布物。
3. 官方发布包含同等修复后，必须切回官方 release/wheel，删除临时 fork 来源，并重跑 M0-02/M0-03 与锁来源审计。
4. 上述解除只覆盖 Knowledge 基础设施，不代表 Evidence/JD/Seed/业务 API 已实现。


## M3-01 live 后的模型风险更新（2026-09-19）

- K05 仍为高风险，但“业务模型完全未运行”已解除：`deepseek-flash` 在生产适配器和真实 openJiuwen Workflow 上完成一次 synthetic 回答分析。第一轮真实输出因 `finding` 类型错误被 Schema 拒绝，证明严格服务端校验必要；补全 Prompt 结构约束后第二轮通过。
- K13 新增并闭合一条日志边界：openJiuwen 会记录组件异常，详细 JSON Schema 错误可能携带模型生成的回答派生文本。SemanticValidation 现只向 SDK 抛固定错误；纯领域校验仍保留详细诊断，回归断言私密 marker 不进入异常或捕获日志。
- 未解除项：单样本不代表模型质量、p95、真实 429/超时恢复或费用；成功 usage 为 1156/2544/3700，首轮失败 usage 和两次费用均 NOT_MEASURED/null。后续批量或 M4 付费 live 前仍需负责人明确持续费用上限。

## M4-01 评分与报告风险更新（2026-09-19）

- K22：评分器是确定性聚合器，不是新的事实发现器。它只消费已通过语义校验的 Observation 和冻结 Rubric；若上游 Observation 错，确定性本身不能保证评价正确。supported/contradicted 冲突必须保留 disputed/null，不能靠最后写入覆盖。
- K23：Report/Assessment 唯一约束、短事务和 retry 防止重复业务结果，但单进程 `BackgroundTasks` 不提供持久队列或 exactly-once 上游调用。重启时 queued/running 都必须转 interrupted；不能把丢失 callable 的 queued 假装成会自动恢复。
- K24：M4 烟测使用 ScriptedAnalyzer fixture，证明真实 FastAPI/openJiuwen Workflow/SQLite/评分/报告闭环，不证明真实模型五题效果。Report UI、浏览器完整报告、真实模型 429/timeout 与整场成本均 NOT_RUN。
- K25：默认 shell 为 Node v26.8.1，直接执行会因 package 要求 `>=24 <25` 产生 engine warning；最终已显式使用仓库 `toolchain/node24/bin` 的 Node 24.21.0 / pnpm 10.34.5 完成 11 项测试与 production build。后续命令仍必须显式选择锁定工具链，不能依赖默认 PATH。
- O04 持续费用上限仍未给出。M4-01 使用 0 次付费模型/embedding 网络调用；M4-02 或批量 live 若要继续调用外部模型，仍需先得到明确总预算，未知费用保持 null。

## M4-02 受约束生成与新页面风险更新（2026-09-19）

- K26：生成式文案即使绑定真实来源，也可能在连接词或语义组合中产生误导。当前服务端用 JSON Schema、允许 ID、逐字引文、Claim allowlist、数字和责任升级守卫作为可审计下限；这不等于语义真实性已经由程序完全证明，用户确认简历版本仍是硬门槛。
- K27：ResumeDraft 以 `(profile_snapshot_id,target_hash)` 唯一，避免同一事实快照/目标产生并行真相；但新快照代表新的事实版本，旧草稿不会自动升级。页面必须显示其绑定来源，不把旧草稿静默套到新资料。
- K28：内容生成仍使用单进程 `BackgroundTasks`。失败和重启通过持久化资源、parent-linked Operation 和 interrupted 状态恢复，但不承诺自动重放或 exactly-once 上游调用；模型调用成功而提交前崩溃仍可能在人工 retry 时再次计费。
- K29：M4-02 浏览器 fixture 已证明 Report/Resume API、Operation、确认和打印媒体连接，未证明生产 Content Generator 的语言质量、延迟、429/timeout 或费用。两个新页面也只完成功能基线，视觉 Product Polish 与独立验收仍 NOT_RUN。
- O04 持续费用上限仍未给出。M4-02 没有外部模型或 embedding 网络调用；生产内容生成 live 或批量验证前必须先得到明确总预算，未知 usage/cost 保持 null。

## M4-02 生产内容模型 live 后的风险更新（2026-09-20）

- K29 的“生产 Content Generator 完全未运行”已解除：`deepseek-flash` 对 synthetic coaching/resume 各一项通过生产适配器、真实 openJiuwen Workflow 和原有语义校验。仍未解除语言质量泛化、批量稳定性、p95、真实 429/timeout、价格和真实材料风险。
- K30：`response_format=json_object` 不是 JSON Schema 下发。首轮模型返回合法 JSON，却使用字段别名并遗漏多个必填字段；服务端正确拒绝。Prompt 现显式列出精确结构，transport 回归检查实际 system message。Schema/领域校验仍是最终门槛，不能因单次 Prompt 成功而删除。
- O04 的费用授权阻塞已解除：负责人明确自有 Key 可无限授权；程序每 operation 三次总尝试硬上限和 smoke 的每任务一次 HTTP 仍保留。provider 未返回费用，cost 继续为 null，不用“无限授权”推算价格。
- 私密配置曾被错误读取到会话工具输出；负责人知情后选择继续当前 Key。本轮 Key 未进入 Git、runtime 证据或文档，但泄露风险不会因继续使用而消失，仍应轮换；任何新 Key 不得进入聊天。

## M4-02 上传候选事实缺口修复（2026-09-20）

- K31：此前 document.import 只解析 Document/SourceBlock，没有执行 Claim 提取，导致真实 PDF 显示“解析完成”但待确认事实为零。修复后 live 路径必须经真实 P-EXTRACT Workflow 选择 `text == exact_quote` 的单块逐字候选，并在同一事务写 Document、SourceBlock、proposed Claim 与 Profile revision；任何校验失败都不留半成品。
- K32：扫描 PDF 的 `requires_text` 不运行 P-EXTRACT；这仍是 P0 明示降级，不是 OCR。模型返回空候选时必须保留可见 warning，不能用本地演示事实补齐。
- K33：一次 synthetic 两页 PDF 已在浏览器看到 4 条待确认事实，调用 usage 为 461/658/1119，cost=null，端到端 Operation 用时约 2.86 秒。该证据只证明上传链路与来源约束，不证明真实简历召回率、语言泛化、p95 或价格。
