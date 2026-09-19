# AGENTS.md｜AI 施工总约定

规范版本 1.0.0。适用于本项目全部代码、配置、数据、测试、提示词及文档。目标是一个可验证的 Demo，不是生产级招聘平台。

## 1. 开始任何任务前

1. 读取本文件、`process.md`、`docs/01-prd.md`、`api.md` 及本任务相关章节；读取仓库实际状态、Git 分支和工作区变更。
2. 用 `git status --short` 确认是否有用户未提交修改。不得覆盖、清理、重置、stash 用户内容而不说明。
3. 在 `process.md` 领取一个任务编号，确认依赖已完成；明确输入、输出、允许修改的路径、验收命令、回滚点。
4. 如果当前环境只有规划包，先建立工程目录与锁文件，不声称原型已经能启动。
5. 对 SDK、依赖、模型能力有疑问时查锁定版本源码或官方文档，不按记忆虚构导入路径、配置参数、事件名。

## 2. 不可违反的边界

- MUST 真正调用 openJiuwen Workflow 和 Knowledge 主链路；不得用名字相同的本地模块充当接入证明。
- MUST 保留一个业务后端和一个业务数据库写入方。前端不能直接调用模型、访问 SQLite 或判断最终分数。
- MUST 先完成一条纵向链路再横向扩展。六条种子没有通过来源审核与闭环测试前，不批量生成题库。
- MUST 区分候选人自述、面试表达、第三方技术资料。简历与 README 重复同一叙述不构成两份独立证明。
- MUST 区分“本轮没问到”“回答不足”“技术上错误”。没有证据时不得自动给零分或判断不会。
- MUST 校验被引文本确实存在并与结论有关。真实 evidence_id 不代表推断必然正确。
- MUST 将模型输出视为不可信输入；任何字段强制转换、修复、默认值都必须有语义理由与可观测记录。
- MUST 明示 `live / fixture / replay` 模式。模拟流量、预录内容、合成简历不能冒充实时运行或真实求职者。
- MUST 把成本、测试结论、实现进度写成实际情况；不得编造指标、用户访谈、专家审核、比赛获奖、国产 OS 适配结果。
- MUST 保护真实简历与密钥；不得写入 Git、截图、演示包、日志或浏览器可读配置。

## 3. 本版不允许自行增加

不得自发增加：多 Agent 讨论、图数据库、后训练、概率能力模型、实时网络抓取、企业招聘决策、社交登录体系、支付、Kubernetes、Redis/Celery、全量向量平台、语音视频面试、五十套模板、职业人格测评。

P1 的 OCR 和记忆须在 P0 验收后单独领任务。外部付费、公开公网、真实数据外发、替换框架/模型、扩大岗位范围，必须先取得负责人确认。

## 4. 实施闭环

`读现状 → 登记任务 → 更新契约草案 → 写最小失败测试 → 实现 → 回归 → 同步文档 → 附证据交接`。

小改动可把契约更新与代码同一提交完成，但不能先改接口让前端猜。失败尝试和被放弃方案简记原因，不把 process.md 写成不可读的逐 token 日志。

每个任务一次聚焦一个目标；提交要能单独回滚。涉及公共 Schema 时先串行合入契约，再允许页面/服务适度并行。

## 5. 完成定义（DoD）

满足全部才可改为 VERIFIED：

- 对应需求编号有测试；实现路径不是 UI 写死演示。
- 输入校验、超时、重复请求、恢复路径与正常路径均有覆盖。
- 没有静默吞异常、假成功响应、空结果伪装成正常评分。
- `api.md`、相关架构/数据说明、`process.md`、`CHANGELOG.md` 同步；不变项在 process.md 写“API 无变化”。
- 附运行命令、时间、环境、返回码、测试数、失败数与证据文件路径；没有运行的项目写 NOT_RUN。
- 涉及外部模型的结论附实际 provider/model、时间、prompt/seed/rubric 版本与 token 统计；无法取得的计费字段写 null，不写 0。
- 没有真实身份数据泄漏；许可证与来源登记可定位。

## 6. 失败处理

同一问题最多两轮有新证据的修复；没有新增证据时停止盲改，登记最小复现、原始错误、已尝试方案与需要确认的点。

不得为了通过测试删断言、把真实 SDK 改成 mock、放开 CORS 全域、关闭 TLS 校验、直接 `except: pass`，或把失败接口返回 200。

测试环境 mock 可以使用，但 `integration_live` 用例不得替换指定框架入口。演示接口失败时显示错误/重试，不自动切到预录成功场景。

## 7. 文档与命名

权威文件是根目录小写 `api.md`、`process.md`。不能同时维护 `API.md`、`PROCESS.md`、`docs/API.md` 三套不同真相；旧文件需要保留时只保留迁移提示和链接。

JSON 与 Python 领域字段统一 snake_case；TypeScript UI 内部变量可 camelCase，网络边界使用生成类型，不手写另一套字段名。所有文件 UTF-8、LF，不允许乱码“修复”脚本全局扫改源文件。

## 8. 每轮结束必须给负责人的交接

使用 `templates/handoff.md`：完成的任务、改动路径、实际测试结果、未通过项、API/迁移/配置变化、成本、本次提交、下一项唯一建议任务。

不得只说“已优化”“已修复”“应该没问题”。不得把计划中的功能列入已完成功能清单。

## 9. 交付界限

本文档包的 Schema 和示例是规范资产，不代表应用已运行。未来业务代码应放入规划的工程目录，不在文档里堆大段无法维护的业务实现。

规则冲突优先级：明确赛事要求与合法授权 → 本文件禁止事项 → 已接受 ADR 与 PRD → 接口/数据契约 → 任务卡。发现代码与契约冲突，必须修复或提出正式变更，不得默默选择自己喜欢的一方。

## 10. 负责人追加的强制约束（2026-09-18）

以下 20 条与本文件、api.md、process.md、docs/* 一并生效；如有冲突，以更保守、更可验证的方案为准。不能用历史规划或测试子项通过绕过本节门槛。

1. 当前目标是“比赛 Demo 可验证纵切面”，不是完整商业产品。禁止主动增加求职信、岗位搜索、多角色面试官、复杂模板、社交分享、招聘管理等非核心功能。主演示岗位固定为嵌入式软件工程师，先把一条完整链路做稳。
2. M0 第一优先级是确认赛题要求的 openJiuwen Agent 基座。必须实际确认：当前使用的 openJiuwen 版本；WorkflowAgent / Base Agent 的真实调用路径；是否存在比赛官方 starter/base agent、模板仓库或额外约束；Knowledge 是否为真实 openJiuwen Knowledge 链路。在这些项目未通过真实运行验证前，不得在 process.md 中标记“已完成”。官方要求通过可追溯的官方资料核验；SDK 路径、指定宿主与 Knowledge 必须有对应运行证据，二者不能互相替代。
3. 若发现官方另有指定 Base Agent 或 starter repo，不推翻现有业务设计。应以官方 Base Agent 为宿主，将 Evidence、Candidate State、Question Planner、Answer Analyzer、Policy、Evaluator、Memory 作为扩展能力接入，不另造一套平行 Agent。Memory 仍遵守 P1 门槛，不因列入扩展能力而提前实现。
4. 禁止用本地自定义类、Mock、假接口或同名模块冒充 openJiuwen 的 Agent / Workflow / Knowledge。Mock 只能用于测试，不能作为比赛 Demo 主链路。
5. 模型知识不能作为事实证据。所有影响评分的事实必须能追溯到：用户简历或项目材料；用户在面试中的明确回答；本地已登记的可靠技术知识源；明确受控的官方资料检索。“模型觉得如此”不能升级为 verified/supported evidence。
6. 必须遵守：未验证 ≠ 不会；简历声明 ≠ 已证实能力；找不到证据时允许 UNKNOWN；证据冲突时必须保留冲突状态，不自行选择一个版本；改写回答不得替用户补造指标、奖项、项目职责或技术细节。
7. 第一版 Policy 保持有限动作集 CLARIFY / PROBE / CHALLENGE / NEXT / END，不主动扩张。LLM 负责结构化分析回答；Workflow/程序负责下一动作决策。不要把整个 Policy 再塞回一个超长 Prompt。
8. 题库先完成少量审核 Seed 并跑通；未完成闭环前不得批量扩展。Seed 必须包含 competency、intent、difficulty、archetype、reference points、red flags、follow-up strategy、source/knowledge reference。最终问题允许根据简历与 JD 动态实例化，但不得改变 Seed 的事实边界。网络字段继续遵循 snake_case 与既有契约，不在本条擅自改 Schema。
9. 所有 API 修改必须先更新或同步 api.md，再修改实现。字段名、状态枚举、错误码、SSE 事件、幂等逻辑变化必须同步：api.md → 后端 schema/DTO → 前端类型 → 调用方 → 测试 → process.md。禁止代码和文档长期漂移。
10. process.md 严格区分 PLANNED / IN_PROGRESS / IMPLEMENTED / VERIFIED / ACCEPTED / BLOCKED。“写完代码”最多只能算 IMPLEMENTED；只有真实测试通过才能写 VERIFIED；不得自行写 ACCEPTED。沿用更保守的独立验收门槛；ADR 也不得以措辞包装成负责人已批准。
11. 每完成一个阶段必须记录：修改文件、修改原因、实际命令、测试结果、未解决问题、API 是否变化、下一阶段入口。不允许只写“已完成”“测试正常”。
12. 禁止 destructive git 操作：不得 force push、reset --hard、覆盖用户已有修改、删除旧 ZhiJue 代码来“简化工程”。重大重构前先保留可回退点。
13. 前后端数据只有一个权威写入路径。不得让旧 Next.js/Drizzle 和新 Python 同时维护同一份核心业务状态；旧代码仅作迁移来源或前端参考，明确 ownership。
14. OCR、Web Fetch、复杂向量数据库、跨场长期 Memory 不得阻塞 P0 主链路。文本 PDF 优先直接解析；OCR 是 fallback；Web 是受控事实验证 fallback，不是主知识源；数据库优先轻量本地方案。Knowledge 所需额外组件以实际兼容验证为准，不为架构图强行引入云服务。此条不授权提前实现 P1 OCR/Memory 或实时抓取。
15. 新增第三方依赖必须说明：现有依赖为什么不能满足；对 Demo 的直接价值；是否增加部署难度；有无本地/免费运行方式。没有明确收益不得引入。
16. M0/M1 未通过前，不做视觉精修，UI 仅作最低调试验证修改。优先保证：上传简历 → 解析 → Evidence → 生成 5 题 → 回答 → 动态追问 → 评分 → 优化回答 → Evidence Trace。
17. Demo 展示“为什么问这一题”“为什么继续追问/为什么换题”；只展示系统结构化决策理由、证据状态与 Workflow 状态，不展示模型私有推理过程。
18. 成功指标必须来自真实测试。禁止编造 Grounding Rate、有效追问率、幻觉率、延迟、成本等数字。尚未测试写 TBD / NOT_MEASURED；未知计费字段仍用 null，不假填 0。
19. 对规范、官方 Base Agent、openJiuwen API、版本兼容性、数据迁移有重大不确定性时不得脑补。相关任务标 BLOCKED，记录已确认事实、未确认点、最小验证方案；优先推进不依赖该阻塞的独立任务，不冒充解除阻塞。
20. 当前阶段结束后，先输出工程汇报：当前架构、真实运行链路、已完成项、测试证据、未解决风险、文档同步状态、下一步建议。不得自动扩展下一大阶段。


### 追加约束与旧契约的落地状态

当前 CHALLENGE 与 P0 四动作契约存在冲突；Seed 的 reference points / red flags / strategy 尚未在现有 Schema 中完整表达。按更保守规则，本轮不静默扩枚举、不把已有字段强行解释成满足新要求。待对齐项记录于 process.md；对齐前不得批准相关业务实现或 Seed，且不得宣称规范已完全一致。

## 11. 负责人补充施工输入（2026-09-18，覆盖此前不必要的串行阻塞）

1. 命题为“基于 openJiuwen 的 AI 面试陪练 Agent”。真实 openJiuwen、Knowledge、Agent Workflow 及简历解析→提问→回答→追问→打分→优化为已知要求，Memory 可选。额外 Base Agent/starter/模板/指定版本保持 `UNCONFIRMED`，不是任务状态枚举，不阻塞独立 Workflow/Knowledge 验证；收到官方补充资料后做 compatibility review，不提前推翻业务设计、不宣称官方没有额外要求。
2. 主演示材料统一称 Demo Resume v1；原始文件名、身份信息、内容指纹与正文不得进入版本库或公开证据。重点经历由负责人说明含 STM32 HAL、FreeRTOS、UART/SPI/CAN/DMA、串口错帧排查、ESP32-S3 + Queue、多节点 CAN、状态机/周期任务/软硬件调试。此说明不是解析产物；所有 Candidate Evidence 必须从实际文件解析/用户确认产生，不按姓名/邮箱硬编码，不将描述补造成文件内容。实际文件未提供时不伪造同名简历。
3. 主演示岗位仅嵌入式软件开发实习生/初级工程师；JD 独立输入。正式 JD 前仅可用标记 `SYNTHETIC_DEMO_JD` 的合成材料做接口/流程测试；Benchmark/最终演示须改用确认 JD，来源状态必须持久化，不从简历猜要求。
4. 首批能力仅 C/嵌入式基础、STM32 外设/中断、UART/DMA 排障、FreeRTOS Queue/Semaphore/Mutex、任务周期/优先级/并发/实时性、SPI/I2C/CAN、状态机/非阻塞、个人贡献边界核对、调试取证。先 6 条可审核 Seed 闭环 VERIFIED 后再到 24 条，禁止先造 100+ 条。
5. Seed 两级审核：Level 1 检查 schema/source/competency/事实边界/follow-up 与 intent；Level 2 依据可靠技术资料审核 reference points，ST/FreeRTOS 优先官方，C/C++ 使用稳定标准或权威资料。模型知识不能作为审核依据。不因无外部审核者停工；完成审核表后仅负责人决定进入 approved_demo_bank。未获确认只能 draft 或 reviewed，不能自行 approved。现有 technical_review 枚举与新 reviewed 要先做正式契约对齐，不静默混用。
6. 模型配置必须支持 MODEL_PROVIDER、MODEL_NAME、API_BASE、API_KEY、MODEL_TIMEOUT、MODEL_MAX_RETRIES；密钥仅来自本地 .env/secret，不进 Git、文档真值、日志或聊天索取。正式配置前允许无模型开发；如确需 LLM，可用开发者本地已有合法配置，但记录实际 provider/model。环境变量模板不等于运行适配器已实现。
7. 模型请求/格式修复/retry 有统一有限预算；完整五题场次记录调用次数和实际 usage/cost，Benchmark 单列；未知写 NOT_MEASURED，机器计费未知字段保持 null，不能填造 0。
8. P0 为本地 Linux、Python 3.11、Node/pnpm、FastAPI、openJiuwen、SQLite/本地文件的稳定单机 Demo；Docker 可后补，禁止预先引入高并发云架构、Kubernetes/Redis 集群/云向量平台。
9. 简历属于用户材料，上传/解析用内部 ID，API 不返回服务器绝对路径，日志不打印完整简历或密钥，删除覆盖派生数据或明确残留策略；区分 Demo 与真实用户数据。
10. 当前优先顺序：真实 Workflow → Knowledge 解析/入库/检索/provenance/重启/删除 → Evidence schema → Candidate State → Resume/Evidence → JD/Requirements → 六 Seed → Planner → Analyzer/Policy → Evaluation/Trace。前两项未 VERIFIED 前，不做大规模 UI/题库扩展。
11. 阶段汇报必须列 SDK 版本、WorkflowAgent/Knowledge 真实运行证据、存储/索引后端、命令/结果/失败项、文档/API 变化、blocker 和下一任务；不得只报“接入”。普通自测通过仍按既有独立验收约定保留 IMPLEMENTED，不能自行 ACCEPTED。
