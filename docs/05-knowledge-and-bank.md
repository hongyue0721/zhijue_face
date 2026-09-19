# Knowledge 接入、题库与数据治理

## 1. 数据不是越多越好

本版只服务一个岗位，题库目标 24 条，分六组每组四条。先做其中六条人工审阅后的纵向样例，跑通再扩大。交付包中的种子示例为 DRAFT，只演示字段；没有完成整库构建，更没有做专家验证。

三种数据分库/标签管理：个人材料、岗位要求、技术参考。不得把候选人答案直接加入公共技术知识库。未授权真实简历不得混入固定 Demo 资产。

## 2. 真正的框架接入证据

M0 至少完成：

1. 从锁定环境导入真实 openJiuwen WorkflowAgent 并运行一个最小工作流。
2. 用真实 SimpleKnowledgeBase 入库一份合成简历和一份项目材料。
3. 检索某个项目事实，返回 doc_id/chunk_id/text，并映射到 SourceBlock。
4. 关闭进程重新启动后仍能读取或按清单可重建；两份 profile 内容不串档。
5. 删除一份材料后不能再在该用户有效检索结果出现。
6. 保存版本、执行命令、去敏日志、输入/输出 hash；在 integration_live 中断言确实经过框架调用路径。

官方文档说明 Knowledge 管理解析、分块、建索引和检索，组件可替换；本方案利用它的原生入口，不仅套一层函数名。[S04]

## 3. 建议数据流水线

`原件 → 类型/资源检查 → 按页提取 → SourceBlock → 事实候选 → 人工确认 → ProfileSnapshot → Knowledge 文档 → 分块/嵌入/索引 → 来源一致性检查 → 激活`。

使用 pypdf 提取有文本层 PDF；扫描件不要求重复 OCR 可读页。复杂双栏/表格提取可能错序，因此必须展示确认页；不能仅凭“字符数量足够”认定识别正确。[S09]

初始 chunk 大约 300 中文字符、重叠 40 字符，仅是工程起始参数；尊重 embedding 的 token 上限，超长块继续分割并保留原块映射。姓名/电话/邮箱不需要参与技术向量索引；分开存展示资料。

索引 metadata 必需：profile_id、profile_snapshot_id、source_block_ids、document_hash、knowledge_generation、source_kind。权限与快照筛选不是让模型遵守一句提示词，而是在检索与返回前都校验。

## 4. 检索策略

候选人资料：使用当前目标能力与项目关键词查询 Knowledge，top_k 初始 4；对照 allowlist 确认来源属于当前快照。小简历全部装入上下文并不天然错误，但本题指定 Knowledge，必须实现真实入库与使用。

题目种子：先按 competency、难度、前置条件、review_status=approved、适用技术环境直接筛选，不为 24 条结构化种子增加额外向量检索链。

技术参考：主要使用种子中已经审核的 reference IDs 精确加载；这比每次全网搜索更可控。检索相似度不是事实置信度。

FTS5 可在后续解决明确关键词召回问题，但中文 tokenization 需要验证，不能把默认分词当成开箱即用中文搜索。当前主线不依赖 FTS5，也不要求将所有文本向量化。[S10]

## 5. 24 条种子建设清单（待制作）

| 分组 | 4 个拟考点 | 适用边界 |
|---|---|---|
| C 与内存 | 指针/缓冲区边界；对象生命周期；volatile 的边界；环形缓冲区读写 | 不把平台 int 宽度当普遍常量；明确执行上下文 |
| MCU 与中断 | 中断做什么/不做什么；定时采样；DMA 数据流；中断到主循环交接 | 明确芯片与库；不凭通用概念断言寄存器细节 |
| RTOS | 任务间资源访问；事件通知；任务间数据传递；优先级相关现象 | 裸机项目只能问显式假设；ISR API 需版本资料 |
| 通信与数据 | UART 流式帧解析；SPI 时序/访问排查；I2C 故障定位；协议校验/重传边界 | 给定真实或假设约束，不硬套唯一方案 |
| 调试与验证 | 偶发卡死取证；日志资源限制；性能指标口径；改动后的回归 | 评价证据路径，不要求每人都有商业监控指标 |
| 项目表达 | 个人贡献边界；技术取舍；失败与修正；成果口径与局限 | 不编团队规模、奖项或成果；没有量化也允许诚实描述 |

## 6. 每条种子必须具备

id、version、competency_id、difficulty、archetype、intent、stem、prerequisites、allowed_context、reference_ids、reference_points、red_flags、follow_up_strategy、review_levels、rubric、followup_intents、out_of_scope、source_origin、review_status、review_record_id（ADR-013 对齐后）。

其中三组字段是 ADR-013 新增的**显式承载**，不得用既有字段冒充：

- `reference_points`：`{point_id, statement, kind: technical|acceptable_alternative, reference_ids}`。**technical 类型必须带非空 reference_ids**，Schema 强制；模型自身知识不能作为技术结论依据。
- `red_flags`：`{signal_id, pattern, requires_followup, note}`，`requires_followup` 结构上恒为 `true`——从字段层面阻止"red flag → 自动扣分"。
- `follow_up_strategy`：`{max_followups, preferred_intents, stop_conditions}`；与 `followup_intents` 并存（前者是策略，后者是允许意图集合），不互相替代。P0 `max_followups ≤ 1`。

Rubric 不能只有关键词；至少写明 0—3 等级的可观察表现和允许的替代思路。多个合理实现不应被“没有提 mutex”一刀切判错。遇到未知库，不能既因模型没见过就判不存在，也不能因为用户说过就判正确。

red flags 仅可表示“需要进一步核对的回答信号”，不等于自动扣分、造假或人格评价。本版 Schema 不设置默认 redFlags→deduction 映射。

## 7. 来源与授权登记

每个 reference：source_id、title、publisher、URL/本地文档标识、revision/version、accessed_at、section、content_hash、license_status、redistribution_policy、technical_review_status。

**公开可读不等于可整篇再分发。** 优先自行写题与解释，仅保留必要短引文/定位；来源未知的资料不打包进仓库。模型生成内容也不自动拥有“官方正确”标签。

优先来源示例：FreeRTOS 官方机制说明、对应 STM32 Reference Manual、Linux 官方文档、C 语言权威规范材料。手册型号/章节先查再填；不要让 AI 生成一个看起来像真的链接。

本包没有收集网络题库全文；技术参考清单由 M1 依照种子逐条建设。Hugging Face/GitHub 面试题可用于探索考点，但其中答案要重新审核，不能只看仓库许可证就忽略上游内容来源。

## 8. 题库审核流程

`draft → technical_review → approved / rejected → deprecated`，与两级审核的映射（ADR-013）：

- `draft`＝未审；
- `technical_review`＝**Level 1 已通过**、Level 2 待做（`review_levels.level1.status=passed`）；
- `approved`＝**Level 1 与 Level 2 均 passed** 且有 `review_record_id`，另需负责人确认。

不再另立 `reviewed` 值，避免与 `technical_review` 形成两套并行语义。审核记录写入 `review_levels`（每级含 `status`、`reviewer_role`、`checked`、`at`）。

每条至少做五件事：核对适用环境；核对核心技术结论；给出可接受替代答案；用含糊/充分/冲突回答分别试跑；检查是否添加简历外前提。

无独立专家时可先由负责人对照资料审核并如实标注 reviewer 角色。对自己不懂的关键知识点，不用模型互相赞成代替审核；宁可换成可审计的经历表达题。

## 9. 网络策略与异常

P0 运行时不做任意网页抓取、不接受自动跟随简历 URL。GitHub/项目材料由用户手动上传内容。缺失技术资料时给 not_assessable，并提示应补的版本/资料；不编参考答案。

离线缓存可保证本地材料与技术参考可读，但远程 LLM 不可用时必须显示暂停、重试或明确标注的 replay。不能写“完全离线 AI 面试”除非实际部署了本地生成模型并验证。

## 10. 固定演示与泛化边界

演示数据可提前准备，选题与追问必须真实运转。不能以特定名字/固定回答全文作为分支条件。发布至少使用三份不同 profile 验证；保留一份未参与 Prompt 调试的同岗资料/回答集。

二十四条种子覆盖的范围就是产品支持范围；换一个未支持岗位时，清楚标注仅能做表达训练，不能自动声称拥有同等专业评价能力。

## 11. M0-03 原生 Knowledge 实测状态（2026-09-18）

真实组合为 `openjiuwen 0.1.18 + pymilvus 2.6.7 + milvus-lite 3.2.1 + BAAI/bge-m3`。两个明确 synthetic 的文本 profile 经 SDK 自带 `TxtMdParser`、`CharChunker`、`SimpleKnowledgeBase`、`MilvusIndexer/VectorStore` 完成解析、入库与 dense 检索；返回的 document_id、chunk_id、source_id、source_sha256 与源文本 hash 一致。关闭进程后由另一 PID 重建组件仍可检索，两个 KB 未串档。

删除阶段未通过：`delete_documents` 已让第一个集合 row_count 变为 0，但 `MilvusIndexer.delete_index` 无法处理 pymilvus 为兼容旧行为返回的主键 list，框架报告失败，第二个 profile 未删除，删除后重启检查 `NOT_RUN`。官方 PR #1344 正在修复同一返回值问题，但当前锁定发布版尚未包含。[S21]

因此本节第 2 节门槛只完成 1—4 的读路径和隔离子项，删除门槛仍阻塞；不得使用底层行数变化替代框架成功状态。去敏证据为 `runtime/evidence/m0-03/knowledge-partial-20260918T172000.json`，原始运行目录被 Git 忽略。Demo Resume v1 未发送给 embedding 服务。


## 12. M0-03-DEL 删除兼容解除（2026-09-19）

正式 `openjiuwen==0.1.18` 发布包的失败记录继续保留；本项目没有把底层已删行数冒充框架成功。负责人本轮指示继续后，施工选择了可回退、可验证的临时来源锁：

- 基线：官方 `agent-core` tag `v0.1.18`（commit `1d37ae3007f9df9a8489a7ab271141b03be08f66`）。
- 修复语义：官方 PR #1344 的两个提交，只增加 Milvus Lite `list/tuple → len(result)` 处理及对应测试。
- 项目锁：公开兼容 commit `72c4985111b835530ec616f70dd67117eb2e015c`，相对 v0.1.18 仅 2 个文件、31 行新增。
- 主链仍为真实 `SimpleKnowledgeBase → TxtMdParser → CharChunker → MilvusIndexer/MilvusVectorStore → Milvus Lite`；没有自定义同名 Knowledge、没有 monkeypatch、没有手改 site-packages。

实际验证结果：

1. 未修复 v0.1.18 的 list 回归：1 failed / 1 passed，错误为 `int(list)`。
2. 相同回归在兼容 commit：2 passed。
3. openJiuwen 上游 `test_milvus_indexer.py`：21 passed。
4. 直接从补丁 worktree 运行四进程 live：解析/入库/检索/provenance/重启/两 profile 删除/删除后重启零命中全部通过。
5. `uv sync --frozen` 从锁定 Git commit 重建本项目 openJiuwen 后，清除 `PYTHONPATH` 再跑同一四进程 live，结果再次全部通过；证据 `runtime/evidence/m0-03-del/knowledge-locked-live-20260919T011100Z.json`。

该结论只适用于上述固定组合。正式 0.1.18 wheel 仍未包含修复，官方 PR 截至核验时仍为 Open；官方发布包含修复后，必须切回官方发布源并重跑 M0-02/M0-03。首次安装当前兼容源需要 Git/网络，但不增加运行时服务、云数据库或付费组件。

本阶段输入仍为两个明确 synthetic profile，Demo Resume v1 未发送给 embedding 服务。兼容验证阶段共 18 次成功逻辑 embedding 调用；连同初次部分验证的 7 次，M0-03 累计 25 次。SDK 未返回 usage/token/cost，继续记录为 null；DeepSeek LLM NOT_RUN。

## 13. M2-01 首批六条种子（2026-09-18—2026-09-19）

位置：`data/seeds/*.json`（审核通过后入库，不含私人资料）。加载入口：`zhijue.application.seed_bank.load_seed_bank`。

| seed_id | competency_id | difficulty | archetype | 技术参考要点 | red flags |
|---|---|---|---|---:|---:|
| `seed_embedded_freertos_queue_mechanism` | `embedded.rtos.queue` | medium | mechanism | 3 | 2 |
| `seed_embedded_rtos_task_period` | `embedded.rtos.scheduling` | medium | tradeoff | 3 | 1 |
| `seed_embedded_mutex_vs_semaphore` | `embedded.rtos.synchronization` | medium | tradeoff | 3 | 2 |
| `seed_embedded_uart_dma_debug` | `embedded.peripheral.uart_dma` | medium | debugging | 4 | 2 |
| `seed_embedded_spi_i2c_selection` | `embedded.peripheral.serial_bus` | easy | tradeoff | 3 | 1 |
| `seed_embedded_interrupt_priority` | `embedded.mcu.interrupt` | medium | mechanism | 3 | 1 |

六条覆盖 6 个不同能力维度，满足 `config/demo.yaml` 的 `min_competency_dimensions: 3`。

覆盖的能力（对应负责人首批范围）：C/嵌入式基础与工具链（体现在 uart_dma 与 interrupt 的排障取证）、STM32 外设与中断（interrupt、spi_i2c）、UART/DMA 排障（uart_dma）、FreeRTOS Queue 与同步原语（queue、mutex、period）、任务周期与实时性（period）、状态机/非阻塞与调试取证（uart_dma 的排查路径）。

**审核状态**：六条均为 `approved`（版本 0.2.1；Level 1 与 Level 2 均 passed）。2026-09-19 完成 S24/S26/S28/S29/S30 官方 PDF 正文核对和平台修正后，负责人明确选择“六条全部通过并批准”；统一记录见 `docs/reviews/review_m2_01_level2_owner_20260919.md`。该决定只覆盖首批六条，**不得据此扩到 24 条**（AGENTS §11.4）。

来源边界：UART/DMA 与 SPI/I2C 已同时引用 F4 的 RM0090、G4 的 RM0440 和 H7 的 RM0433，并显式隔离位名、DMA 映射与 I2C 速率差异；NVIC 架构规则引用 Cortex-M4 的 PM0214，型号通道数另引对应 RM。以后新增平台仍必须登记该系列官方来源，不得沿用其它系列结论。

live 门禁只认 `config/demo.yaml` 的 `seed_bank.live_allowed_review_status`，当前值为 `approved`。`SeedBank` 加载时读取该权威配置；当前六条可由 `live_only=True` 加载，降级为 technical_review/draft 时显式失败，混合题库只返回 approved 条目。
