# 数据模型、证据与版本契约

## 1. 三类东西必须分开

**候选人声明**：用户简历、自己写的项目说明、本人回答中的经历。能被记录和讨论，但不是背景调查核验结果。

**技术参考**：经审核的官方手册/文档，限定版本和环境，支持对技术机制的评价。

**面试观测**：这个回答中实际表达了什么、哪些点没表达、与参考是否存在矛盾。这不是对真实世界能力的全局结论。

禁止把三者统称“verified facts”。不设置 `truth_confidence=0.94`。同一主体的多次声明不可自动累计为独立可信证据。

## 2. 标识与版本

所有 ID 都由服务端生成、为不透明带前缀字符串，例如 `profile_...`、`source_...`、`claim_...`、`interview_...`、`question_...`、`operation_...`。客户端不得从 ID 猜含义。

`revision` 为非负整数，用于资源乐观锁；`schema_version` 是契约版本，如 `1.0.0`；两者不是一回事。时间统一 RFC3339 UTC。字节数与字符数分开，MiB＝1,048,576 字节。

每个面试保存不可变快照：profile_revision、JD 原文与解析结果、seed_bank_version、rubric_version、prompt_versions、policy_version、model 配置指纹、SDK 版本、运行模式。

## 3. 核心实体

| 实体 | 必需字段/关系 | 关键不变量 |
|---|---|---|
| Profile | id、workspace_id、display_name、revision、synthetic、status | 状态 active/deleting/deleted；不以姓名做外键 |
| Document | id、profile_id、kind、sha256、mime、size、extract_status、index_status | 原始文件不可覆盖，替换产生新 Document |
| SourceBlock | id、document_id、page_number、block_index、text、text_hash、origin | page 从 1 起；纯文本 page=null；origin text_layer/ocr/user_input |
| Claim | id、profile_id、text、source_block_ids、source_quotes、status、supersedes_id | status proposed/confirmed/disputed/retracted；确认是用户确认叙述，不是现实核验 |
| ProfileSnapshot | id、profile_id、revision、confirmed_claim_ids、display_fields | 一经被面试引用不可修改 |
| ProfileSnapshotActivation | snapshot_id（主键）、status、operation_id、receipt、updated_at | 每代独立 pending/indexing/ready/failed；仅同代完整 Knowledge 回执可置 ready，旧代不能解锁新代 |
| ResumeDraft | id、profile_id、profile_snapshot_id、interview_id、revision、status、sections、source_claim_ids、changes、missing_facts、cautions、target_context、active_operation_id、run_metadata | generating/generation_failed/draft/accepted；正文条目必须逐项引用快照内 confirmed Claim；目标 JD 不能作为候选人事实来源；仅 accepted 版本可打印 |
| Interview | id、profile_snapshot_id、jd_snapshot、revision、status、root_plan、active_operation_id、stop_requested | 一个时间点最多一个活跃变更操作；主计划五题 |
| Question | id、interview_id、root_id、kind、seed_id（经历/证据回退题可 null）、wording、basis、rubric_snapshot | kind main/probe/clarification；根问题权重只算一次；无匹配 approved Seed 时不得绑定无关技术种子 |
| Answer | id、question_id、client_turn_id、accepted_operation_id、raw_text、created_at、assistance、evaluation_status | 原文不可覆盖；一题一份已接受作答；client_turn 与原 operation 可恢复、可幂等重放 |
| Observation | id、answer_id、question_id、root_question_id、criteria、relevance、knowledge_status、clarification_needed、validation_flags | 仅保存通过语义校验的观察；模型原始输出隔离为调试数据 |
| Decision | id、observation_id（控制动作时可 null）、action、reason_code、target、policy_version | 动作由代码决定，不由模型直接决定 |
| Assessment | id、interview_id、root_question_id、criterion_results、score、coverage、status | `(interview_id,root_question_id)` 唯一；score 可以 null；未评不是 0 |
| Report | id、interview_id、revision、completion、overall_score、coverage、root_assessments、improvements_status、active_operation_id、improved_answers、limitations、run_metadata | `interview_id` 唯一；评分完成不隐式调用改写模型；改写失败不改变已冻结分数 |
| Operation | id、kind、resource_id、idempotency_key、input_hash、status、attempts | 状态队列独立于业务状态 |
| OperationEvent | operation_id、seq、event_type、payload、created_at | `(operation_id,seq)` 唯一；只追加 |
| TrainingMemory | profile_id、competency_id、observed_gap、evidence_ids、status | P1；未测试技能不得写成弱项；用户可删除 |

关系：Profile→Document→SourceBlock→Claim；ProfileSnapshot 引用 confirmed Claim；Interview 引用快照；Question→Answer→Observation→Decision/Assessment；Report 汇总根问题而不是每次聊天泡泡。

## 4. 技能表现状态，不做真实性认证

`unassessed`：本轮没测；`insufficient`：问过但表达无法支持判断；`demonstrated`：本轮回答覆盖 Rubric；`needs_practice`：本轮存在有依据的理解/表达缺口；`disputed`：材料或参考冲突，暂不下判断。

证据充分度可写 `none / limited / adequate`，仅用于操作策略，不输出成“能力置信度百分比”。用户说得细致不能证明项目确实发生；技术答对也不能证明个人承担了团队所有工作。

示例：“能说明为何任务间共享总线需要串行化”可以是本轮 demonstrated；“真实独立开发了整套设备”不能因为这一回答就自动成立。

## 5. 来源定位与一致性

1. 提取后的 SourceBlock 为不可变文本，保留原始文件 hash、页码和 block_index。
2. Claim 引用 `source_block_id + exact_quote`。上传材料的 P-EXTRACT 只能选择一个块内的连续逐字片段，Claim text 必须与 exact_quote 完全相同；模型改写、未知块、虚构引文、联系方式和重复候选在 Document/Claim 原子提交前拒绝。对外只返回必要片段。
3. 用户更正产生 `user_input` 新块和 supersedes 关系，不篡改原 PDF 来源。不把人工更正文案标成 OCR 正确识别。
4. 检索 chunk 必须映射回一个或多个 SourceBlock。若分块失去来源映射，不能用于“材料直接证明”提问。
5. 对模型生成的摘要再检查来源的语义支持。禁止用字符串相似度把错误陈述强行重绑到最像的一句，造成伪溯源。
6. 从标准化文本定位到原页时保留规范化版本；不要在文本标准化前后的偏移间混用。P0 使用块 ID 和 exact_quote，避免虚构精准 bbox。

## 6. 评分数据

Observation 中每条 criterion：`criterion_id / kind / weight / level / finding / answer_quotes / knowledge_refs / explanation`。Report 合并同一根题的多轮 Observation 后使用 `explanations[]`，不丢弃冲突两侧依据。

- kind 为 technical/expression/evidence_reasoning。
- level 为 0、1、2、3 或 null；Observation finding 为 supported/missing/contradicted/not_assessable，合并结果还允许 disputed。
- technical 的明确错误评价需要适用的 reviewed 技术参考；无参考则 not_assessable。
- missing 只是本回答未覆盖被明确问到的评价要点；未问到、非适用项用 not_assessable，不混算。
- supported 与 contradicted 同时出现时保留 disputed，根题 score=null；不以最后一句覆盖前一份证据。
- 不允许客户端提交 overall_score，也不允许模型解析失败后默认 75 分。数字只由程序按冻结 Rubric 计算。

分数聚合与 coverage 详见 `docs/06-prompts-and-factuality.md`，Report 网络形状见 `api.md` §6。观察 Schema 见 `contracts/observation.schema.json`。

ReportView 的 `root_assessments[].question_text/answers[]` 只读关联该场持久化 Question/Answer，按题序恢复主答与追问原文；生成优化前即可读取。`InterviewView.jd_text` 从冻结 `jd_snapshot.raw_text` 返回，历史确无原文时为 null，不从 Requirement 拼造。

## 7. 数据库存储规则

业务表使用 SQLite，JSON 字段存储版本化快照；第一版不把每个词建表。使用外键约束、事务、唯一键与索引。关键唯一键：`(interview_id,client_turn_id)`、`question_id`（一题一份 Answer）、`accepted_operation_id`、`(interview_id,root_question_id)`（一根一份 Assessment）、`report.interview_id`（一场一份 Report）、`(profile_snapshot_id,target_hash)`（同一快照与目标只生成一份 ResumeDraft）、`(scope,idempotency_key)`、`(operation_id,seq)`。

应用启动必须在打开业务仓储前执行 Alembic `upgrade head`，不得用 `create_all()` 在运行时补表掩盖版本漂移。连接启用 foreign_keys、busy_timeout 与 WAL。历史 `create_all` 形成且没有 `alembic_version` 的完整初始 Schema 由 base migration 先登记初版，再由后续 revision 幂等补齐列、约束和表；只有部分初始表的未知 Schema 必须拒绝启动，不能猜测迁移。真实库迁移前先做受限备份，并在副本或专项测试中核对行数、FK 与 metadata 零漂移。[S12]

服务端所有列表有明确 order_by，不依赖 SQLite 偶然返回顺序。测试数据与真实数据使用独立目录/数据库。前端 refresh 从服务端快照恢复，不从上一个用户的 React 内存拼凑资料。

## 8. 业务库与知识索引的双存储一致性

SQLite 保存权威资料与引用；索引是可重建副本，二者不能假设跨库原子事务。

入库采用 `pending → indexing → ready/failed`，由独立 `profile_snapshot_activation` 而非 Document 全局状态承担门禁。confirm 在一个事务中受理裁决、revision、快照、activation 和 Operation；后台仅在 generation/source_ids 完整匹配后置 ready。失败 retry 复用同一快照，不重放裁决、不增加资料 revision；父子操作累计最多三次，禁止旧代或兄弟分叉。检索只接受该快照允许的 source IDs。

迁移 `e62a9f8c10bd` 只把具有同代、完整、succeeded 历史激活回执的快照回填 ready，其余 pending；不因历史 Document.ready 或快照存在而猜成功。旧库部署前必须显式迁移。pending 可通过 `/profiles/{id}/activate` 激活；queued/running 中断后 activation 变 failed，由用户显式恢复。计划/start 拒绝空快照与非 ready 代次；通用简历也拒绝空快照。

Profile 删除先 tombstone，使所有新检索/操作提交立刻拒绝；再异步清理原件、索引、会话、报告与记忆。删除未完成 UI 显示 deleting，不说“已经完全删除”。发生部分失败可重试清理；保留最小无内容的操作状态。

## 9. 改写与简历生成的事实边界

回答改写与简历生成都通过真实 openJiuwen Workflow 执行，但模型输出只是候选结果，不能直接持久化。服务端必须检查输出 Schema、引用 ID、逐字回答引文、数字事实和职责归属措辞；任一检查失败则整次 operation 失败，不保存部分结果。

回答改写的每个文本片段至少绑定一条本场 Answer 精确引文或当前 ProfileSnapshot 内 Claim。简历每个正文条目至少绑定一条当前快照内 confirmed Claim。服务端从这些引用反向生成 `source_claim_ids` 和 diff，不接受模型自报的来源汇总。

`missing_facts` 和 `cautions` 是编辑提示，不得拼进正文。JD 仅用于排序和表达目标，绝不能升级为候选人经历。数字与“主导/独立负责”等职责措辞只有在绑定来源出现时才能进入正文；此类机械校验只是可审计下限，不等同于语义真实性认证。

原始 ProfileSnapshot、Answer、Report 分数都不可被生成操作覆盖。失败与重试更新独立状态和 revision；对相同已完成资源返回原 operation，不重复调用模型。

## 10. 原始生成输出

原始 LLM 输出不直接进入业务字段。默认只保存脱敏错误摘要与 hash；为定位问题临时保存原始输出时须限定合成测试数据、独立 debug 目录、保留期限与访问范围。

提示词中输入的材料不是系统命令。任何从文档里提取出来的 URL、工具名称、SQL 或 shell 命令不得自动执行。
