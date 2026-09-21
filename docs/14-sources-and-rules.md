# 来源登记、规则核验与不确定性

**核验日期：2026-09-19（初次核验 2026-09-18）。** 外部资料是事实依据，不是已经跑过环境的证明。下列链接保留在本地工程文档供开发者追溯；框架源码使用已读到的 commit 固定引用，不能把该 commit 的代码接口自动视为 PyPI 发布版接口。

## 来源目录

| ID | 来源及地址 | 本包采用的事实 | 状态/边界 |
|---|---|---|---|
| S01 | [官方华为命题](https://cy.ncss.cn/mtcontest/detail?id=2c93f4c6a00f063201a03d77f6f01097) | openJiuwen、Knowledge、Workflow；Memory 可选；五题、追问、评分、优化、流程图和差异说明 | 本轮重新读取题面，并定位 u-j8 解读页；关联答疑帖子未读取，不等于所有补充细则已读 |
| S02 | [教育部：2026 产业赛道方案 PDF](https://hudong.moe.gov.cn/srcsite/A08/s5672/202607/W020260731408855779722.pdf) | 国产 OS 软件组背景；3—15 实际成员；9/25 12 时报名及对策截止；校企契合度审核 | 已读文本与页面图；校内时间和上传字段未知 |
| S03 | [openjiuwen PyPI](https://pypi.org/project/openjiuwen/)；[Core README](https://github.com/openJiuwen-ai/agent-core/blob/develop/README.md) | Python >=3.11,<3.14；0.1.18 为本次选择的已发布验证候选；SDK 提供 WorkflowAgent | 已安装锁定 0.1.18；仅无模型 Workflow/WorkflowAgent smoke 通过，不代表 Knowledge/M0 通过 |
| S04 | [固定 commit Knowledge 开发指南](https://github.com/openJiuwen-ai/agent-core/blob/6dfda012193d09dc3908524d5f8ae406811d909f/docs/en/2.Development%20Guide/Advanced%20Usage/Knowledge%20Retrieval.md)；[Milvus Store 实现](https://github.com/openJiuwen-ai/agent-core/blob/6dfda012193d09dc3908524d5f8ae406811d909f/openjiuwen/core/retrieval/vector_store/milvus_store.py) | SimpleKnowledgeBase 的解析、入库、检索、删除及组件配置；Milvus URI 进入客户端 | 文档与部分源码已读；发布版和 Lite 组合需实测 |
| S05 | [Milvus Lite 官方说明](https://milvus.io/docs/milvus_lite.md) | 可本地文件持久化、面向小规模；功能和系统支持有边界 | 不承诺框架全部 Milvus 调用都兼容 Lite |
| S06 | [BAAI/bge-small-zh-v1.5 模型卡](https://huggingface.co/BAAI/bge-small-zh-v1.5) | 历史本地候选，512 维 | 已被负责人指定的 BGE-M3 远程方案取代，不再继续下载/安装 torch |
| S07 | [Node 发布版本](https://nodejs.org/en/about/previous-releases)；[Vite 官方指南](https://vite.dev/guide/) | Node 24 LTS 作为环境基线；Vite 有 Node 最低版本要求 | 具体 Node/Vite/React/TS/pnpm 组合需锁文件和 build 验证 |
| S08 | [FastAPI lifespan](https://fastapi.tiangolo.com/advanced/events/) | 可管理应用启动与关闭资源 | 本包队列与 Operation 持久化为自定义设计，不声称 FastAPI 默认提供 durable job |
| S09 | [pypdf 文本提取](https://pypdf.readthedocs.io/en/stable/user/extract-text.html) | 文本提取与 OCR 不同，复杂 PDF 提取有边界 | P0 手动降级，P1 OCR 另验收 |
| S10 | [SQLite FTS5](https://sqlite.org/fts5.html) | 全文检索和 BM25；供后续可选检索参考 | 不作为 P0 指定 Knowledge 的替代；中文分词另测 |
| S11 | [FreeRTOS 官方文档入口](https://www.freertos.org/Documentation/) | 仅作为后续 RTOS 技术来源发现入口 | 本轮没有核验某条种子的全部技术答案；不能当 approved 引文 |
| S12 | [SQLAlchemy SQLite 方言](https://docs.sqlalchemy.org/en/20/dialects/sqlite.html)；[SQLite Backup API](https://sqlite.org/backup.html) | SQLite 使用约束；在线备份机制可产生一致副本 | 并发、WAL、恢复仍需本项目实测 |
| S13 | [旧 ZhiJue package.json](https://github.com/hongyue0721/ZhiJue/blob/main/package.json) | 已有 Next.js/React/Drizzle/SQLite 等依赖；用于判断旧工程边界 | 通过用户 GitHub 连接只读；本轮未运行旧项目，也未复核其全部文件 |

## 已确认、工程选择、待确认必须分开

**题面已确认：** 要使用框架 Knowledge 与 Workflow；Memory 可选；有五题等具体展示要求。[S01]

**本包工程选择：** Vite、FastAPI、SQLAlchemy、Milvus Lite 候选、24 条种子目标、五主问题加最多一次补充、先不做 OCR 和长期记忆。这些不是官方强制技术栈，也不是评审分数保证。

**外部仍待确认：** 有无额外 BaseAgent 限制；学校截止与计划书模板；源代码/演示视频/软件包是否必须上传；国产 OS 具体适配要求；报名系统限制。已读题面未出现指定固定 BaseAgent 的条款，不等于证明没有其他通知。

## 版本真实性

不要在计划书写“已验证 openJiuwen 0.1.18 + Lite 全兼容”。正确状态是“选为候选，在 M0 验证后冻结”。开发指南里的 imports、类和参数必须与安装分发版本核对，SDK 升级后要重新跑入库、查询、删除、workflow 和恢复测试。

任何资料抓取日期只表示取得它的日期，不等于其内容新鲜或技术断言正确。官方文档也有版本与平台边界；保留适用范围比给所有来源统一 A 级更重要。

## 数据与代码的使用边界

题目思路可以参考公开资料，但复制题目、答案、图片、源码、模型权重前要核对各自许可和署名条件。公开可访问不等于允许重新分发；本包不附第三方题库全文、官方 PDF 全文或用户仓库源码。

现阶段示例题全部标 draft，事实/评分示例全部标 synthetic/fixture，不声称来自真实学生、专家评审或实际系统实验。法律合规不以 AI 的单次判断为准；对真实投稿的第三方依赖和原创范围由负责人确认。


## M0-BASE 本轮官方核验补记（2026-09-18）

| ID | 来源 | 实测内容与边界 |
|---|---|---|
| S14 | [官方详细解读 u-j8](https://competition.gitcode.com/competition/guochuang-2026/u-j8) | 由 S01 分类页静态资源中的题目 ID 定位，再直接 GET 该页确认；与 S01 对应同一命题。正文要求 Knowledge 与 Agent Workflow，Memory 可选；未列专用 starter/BaseAgent 类。这只是已读页面的范围内结论 |
| S15 | [u-j8 指向的官方答疑入口](https://gitcode.com/org/openJiuwen/discussions) | 首轮 HTTP 200 仅获得应用 HTML 壳；本轮从公开客户端定位只读列表查询，返回 HTTP 418 CloudWAF，未取得帖子正文。补充约束/模板仍 UNKNOWN，未绕过拦截 |

读取时间、HTTP 状态、源页面 hash：runtime/evidence/m0-02/official/fetch.json。HTML/文本/静态资源仅作为本地核验快照保留在 ignored runtime/，不纳入对外演示包或 Git。web 工具未提供可用内容后，通过 TLS 校验开启的 Python HTTPS 请求取得页面；没有绕过登录/验证码，没有给网站上传项目数据。此为施工规则核验，不是给 Demo 加实时 Web Fetch。

核验状态 M0-BASE=BLOCKED。最小解除方式：提供官方答疑正文、指定模板仓库或命题方基座说明；若有指定宿主，须在其上重跑集成，不以本地 legacy 路径自动等同比赛指定基座。

## 已安装 SDK 来源/许可证

真实分发为 openjiuwen 0.1.18，由既有 uv.lock 定位包与下载 hash；未升级，未修改 site-packages。分发内 `openjiuwen-0.1.18.dist-info/LICENSE` 为 Apache-2.0，SHA256 `58d1e17ffe5109a7ae296caafcadfdbe6a7d176f0bc4ab01e12a689b0499d8bd`。包 METADATA 的 License 字段为空，因此依据实际许可证文件登记，不猜字段值。

源码文件与继承链的运行时定位见 smoke-a.json；官方 WorkflowAgent 使用 legacy ControllerAgent/BaseAgent，弃用警告属于已知兼容风险。本轮新增的是原创探针/测试，没有拷贝 SDK 实现、没有新增第三方依赖。


## M0-BASE 续核证据（2026-09-18）

| ID | 官方来源 | 可证结论与限制 |
|---|---|---|
| S16 | [固定 commit WorkflowAgent 源码](https://github.com/openJiuwen-ai/agent-core/blob/6dfda012193d09dc3908524d5f8ae406811d909f/openjiuwen/core/application/workflow_agent/workflow_agent.py)；同 commit `docs/en/2.Development Guide/API Docs/openjiuwen.core/application/workflow_agent/workflow_agent.md` | 官方入口为 core.application.workflow_agent，继承官方 legacy ControllerAgent；不能由 legacy 字样推断是本地伪接入，也不能认定它就是比赛额外指定宿主 |
| S17 | [官方通用 WorkflowAgent notebook](https://github.com/openJiuwen-ai/agent-core/blob/6dfda012193d09dc3908524d5f8ae406811d909f/examples/workflow_agent/build_workflow_agent.ipynb) | 天气查询教学示例，包含模型/外部服务及旧 openjiuwen.agent 导入；不是本命题指定模板的证据。仅测试旧导入（如实失败），未运行 notebook |
| S18 | [官方 GitHub 组织](https://github.com/openJiuwen-ai)及公开 API 的仓库列表/agent-core、docs、community 目录树 | 列表返回 20 个仓库；3 个目录树均 truncated=false。在名称/路径筛查范围内未定位本题专用 starter，不等于全文审计、GitCode 完整镜像审计或官方否定证明 |
| S19 | uv.lock 指定的 [openjiuwen 0.1.18 发布页](https://pypi.org/project/openjiuwen/0.1.18/)及其锁定 wheel | wheel 7,157,657 字节，SHA256 `b5fdc79cfa121324b473d9002d5c8be7514b3932f8866e22a1723147004d6d8a`；下载字节/hash 与既有锁一致，7 个审计文件与安装版 7/7 一致。仅读取 ZIP，没有安装/变更依赖 |

本轮证据位于 runtime/evidence/m0-base/。SDK wheel 和下载源文件留本地核验，不复制进业务实现；公开仓库的 README/API/notebook 不构成比赛强制模板授权。未使用选手或第三方博客项目作为官方依据。

**重要版本差异：** 与 S16 固定 commit 比较，7 个入口相关文件 5 个相同，`core/workflow/workflow.py` 与 `core/session/workflow.py` 不同；例如仓库代码的节点 `name` / session `trace_id` 参数不在该发布版对应签名中。wheel 比对证明本地被审计文件符合锁定发布包，不应为追上网页示例而自行改 site-packages 或升级。

**获取失败边界：** S15 列表接口为客户端使用的只读 POST 查询，不是创建/发帖接口；2026-09-18T08:28:40-07:00 返回 HTTP 418 CloudWAF。额外尝试公开 GitHub 组织 discussions 返回 404。保存返回体不等于读到答疑；不绕过拦截，M0-BASE 仍 BLOCKED，需官方答疑/补充材料或书面确认。

## M0-03 模型与删除兼容来源（2026-09-18—2026-09-19）

| ID | 来源 | 可证结论 | 限制 |
|---|---|---|---|
| S20 | [BAAI/bge-m3 官方模型卡](https://huggingface.co/BAAI/bge-m3) | 模型卡列出 1024 维、8192 token、多语言及 dense/sparse/multi-vector 能力 | 本项目只实测 dense 1024 维；没有测试 8192 上限、sparse 或 multi-vector，也不能仅凭维度证明网关内部映射 |
| S21 | [openJiuwen agent-core PR #1344](https://github.com/openJiuwen-ai/agent-core/pull/1344) | 官方 PR 明确描述 `MilvusIndexer.delete_index` 在 pymilvus 返回 list 时触发 TypeError，并补 list/tuple 处理与测试 | 截至 2026-09-19 仍为 Open，不能当作正式 0.1.18 已包含 |
| S22 | [DeepSeek 官方模型与价格文档](https://api-docs.deepseek.com/quick_start/pricing/) | 官方页面列出 `deepseek-flash` 模型标识 | 仅确认请求名存在；本轮没有调用 DeepSeek，provider/model/token/cost 仍 NOT_RUN / null |
| S23 | [项目兼容 commit](https://github.com/hongyue0721/agent-core/commit/72c4985111b835530ec616f70dd67117eb2e015c)与[提交到 PR #1344 的 live 验证](https://github.com/openJiuwen-ai/agent-core/pull/1344#issuecomment-5738067134) | 兼容 commit 基于官方 v0.1.18，仅含 PR #1344 两个提交；公开评论记录 Python/pymilvus/milvus-lite 版本、修复前后回归、21 项上游测试与四进程真实生命周期 | 这是项目维护的临时来源与项目取证，不是 openJiuwen 官方发布物或官方签名背书；官方 release 含修复后必须替换 |
| S24 | [DeepSeek 官方 Chat Completions API](https://api-docs.deepseek.com/api/create-chat-completion) | `reasoning_effort` 接受 `none / low / high / max`；`low` 开启低强度思考，官方默认值为 `high` | 仅用于确认请求参数语义；项目按负责人指令显式发送 `low`，不据此宣称延迟或效果改善 |

M0-03 的运行结论来自锁定环境和 synthetic 文本，不来自模型卡自述：SDK 请求 `BAAI/bge-m3` 后实测向量维度 1024；两个 KB 在兼容 commit 上完成解析、入库、检索、provenance、进程重启、删除及删除后重启零命中。正式 0.1.18 wheel 的失败证据仍保留，不因项目兼容源通过而改写历史。模型卡只用于核对候选参数，不能升级为 Candidate Evidence 或比赛成效。


## M2-01 种子技术参考来源（2026-09-18）

核验方式：2026-09-19 本机实际下载并提取 S24/S26/S28/S29/S30 官方 PDF 正文，逐条定位本轮六条 Seed 使用的 Queue/Semaphore/Task、NVIC、I2C、SPI 与 USART/DMA 段落。**每条只记录实际读到的内容**；工程推导与手册逐字事实在审核包中分开标注，不用模型记忆补齐。

| ID | 来源 | 可证结论（实际读到的内容） | 限制 |
|---|---|---|---|
| S24 | [The FreeRTOS Reference Manual V10.0.0（官方 PDF）](https://www.freertos.org/media/2018/FreeRTOS_Reference_Manual_V10.0.0.pdf) | 官方参考手册，版次 "Reference Manual for FreeRTOS version 10.0.0 issue 1"，版权 © 2017 Amazon.com, Inc.。已逐条核对：Chapter 3 `xQueueSend`/`xQueueReceive` 的固定 item-size 字节复制与 `xTicksToWait`、`FromISR` 无阻塞等待；Chapter 2 `vTaskDelay`/`vTaskDelayUntil` 的相对延时、绝对唤醒与固定频率；Chapter 4 mutex ownership、binary semaphore 差异和优先级继承；Chapter 7 `configUSE_MUTEXES` 等配置边界 | 仅支持 V10.0.0 手册明确的内核 API 语义；"节奏解耦"等工程作用须标为推导，不外推到特定移植层或 ESP-IDF 封装 |
| S25 | [FreeRTOS 官方 Kernel 文档站：Queue Management](https://docs.freertos.org/Documentation/02-Kernel/04-API-references/06-Queues/00-QueueManagement) | 官方在线 API 参考入口，标题 "Queue Management - FreeRTOS™"，页脚标注 "Updated Sep 2026"；同站 `xQueueSend` 页面存在 | 该站为客户端渲染，本机只取到页面标题与元数据；正文需在浏览器中阅读，因此本包不引用其正文细节，改用 S24 手册版次 |
| S26 | [STM32H742/743/753/750 参考手册 RM0433（ST 官方 PDF，Rev 8）](https://www.st.com/resource/en/reference_manual/rm0433-stm32h742-stm32h743753-and-stm32h750-value-line-advanced-armbased-32bit-mcus-stmicroelectronics.pdf) | 实测下载 40,711,860 字节并提取正文，确认以下章节真实存在（页码为手册页码）：**Chapter 15 Direct memory access controller (DMA)**（15.3 功能描述、15.3.1 框图、15.3.3 DMA overview，p.635 起）；**Chapter 19 Nested vectored interrupt controller (NVIC)**（19.1 NVIC features：STM32H7xxx 最多 150 个可屏蔽中断通道、**16 个可编程优先级（使用 4 位优先级）**，p.749）；**Chapter 47 Inter-integrated circuit (I2C)**（47.4 功能描述：标准 100 kHz / Fast-mode 400 kHz / Fast-mode Plus 1 MHz，SDA/SCL，p.1950 起）；**Chapter 48 USART/UART**（48.5.6 USART receiver、48.5.19 Continuous communication using USART and DMA、48.7 USART interrupts；正文在 p.2027/p.2031 交叉引用 "Section 48.5.19"；接收侧描述 RXNE/RXFNE 标志与**含 error bits 的接收数据**）；**Chapter 50 SPI**（50.4 功能描述、50.4.1 框图；同步串行通信，可轮询或中断，p.2158 起）；**Chapter 56 FDCAN**（56.4 功能描述：CAN core 处理 "ISO 11898-1: 2015" 协议功能，支持 11 位与 29 位标识符，p.2459 起） | 只覆盖 STM32H7 系列，**不能外推到 STM32F1/F4 等系列的具体寄存器与优先级位宽**；未阅读全部小节正文；手册为 ST 版权材料，本包只做定位引用，不再分发全文 |
| S27 | [ST AN4031：STM32F4 系列 DMA 控制器使用](https://www.st.com/resource/en/application_note/an4031-introduction-to-the-stm32f4-series-microcontroller-stmicroelectronics.pdf) | 官方应用笔记存在且可直接下载（HTTP 200，application/pdf） | 本轮只确认可获取，**未提取正文核对结论**；因此不作为任何种子 reference_point 的依据，仅登记可追溯入口 |

**未找到可靠官方来源的主题**：无。（上述主题均可定位到 ST 或 FreeRTOS 官方文档。）  
**本包未做的事**：没有把这些来源的答案文本复制进仓库；没有据模型自身知识补写技术结论；没有引用二手博客/教程站作为 reference_point 依据。

### 种子 reference_id → 来源登记的映射（M2-01）

种子里的 `reference_ids` 是**知识源标识**，必须能回到上面的来源登记；`tools/validate_spec.py` 会强制检查该映射，缺映射即校验失败（防止出现"看起来像真链接"的悬空引用）。

| reference_id | 指向来源 | 说明 |
|---|---|---|
| `freertos_reference_manual_v10` | S24 | FreeRTOS 官方参考手册 V10.0.0（Queue / Semaphore / Task and Scheduler / Kernel Configuration 章节） |
| `rm0433_stm32h7` | S26 | ST RM0433 Rev 8（第 15 DMA、19 NVIC、47 I2C、48 USART、50 SPI、56 FDCAN 章） |
| `rm0090_stm32f4` | S28 | ST RM0090 Rev 22（第 10 DMA、12 中断与事件、27 I2C、28 SPI、30 USART 章） |
| `rm0440_stm32g4` | S30 | ST RM0440 Rev 9（第 12 DMA、14 NVIC、39 I2C、40 USART、42 SPI/I2S、44 FDCAN 章） |
| `pm0214_cortex_m4` | S29 | ST PM0214 Rev 10（§2.3.5 异常优先级、§2.3.6 优先级分组） |

范围提示：外设事实必须引用覆盖目标 MCU 系列的来源；`rm0433_stm32h7` 不得用于证明 F4/G4 特有行为。架构级 NVIC 规则与型号级通道数必须分开引用，FreeRTOS 内核语义不得冒充芯片外设事实。

## M2-02 平台作用域来源补充（2026-09-18）

负责人指出主演示简历含 **STM32F407** 与 **STM32G431**，因此 H7 手册（S26）的事实**不得外推**到 F4/G4。以下来源均已本机下载并核对正文：

| ID | 来源 | 可证结论（实际读到的内容） | 限制 |
|---|---|---|---|
| S28 | [STM32F405/407/415/417/427/437/429/439 参考手册 RM0090（ST 官方 PDF，Rev 22）](https://www.st.com/resource/en/reference_manual/dm00031020-stm32f405-415-stm32f407-417-stm32f427-437-and-stm32f429-439-advanced-arm-based-32-bit-mcus-stmicroelectronics.pdf) | 实测下载 21,385,881 字节并提取目录，确认 **Chapter 10 DMA controller (DMA)**、**Chapter 12 Interrupts and events**、**Chapter 27 Inter-integrated circuit (I2C)**、**Chapter 28 Serial peripheral interface (SPI)**、**Chapter 30 Universal synchronous asynchronous receiver transmitter (USART)** 真实存在 | 覆盖 F4 系列（含 F407）；**不含独立的 NVIC 优先级位宽章节**（NVIC 属 Cortex-M4 内核，须用 S29）；页码/章节只对该手册有效 |
| S29 | [STM32 Cortex-M4 MCUs and MPUs 编程手册 PM0214（ST 官方 PDF，Rev 10）](https://www.st.com/resource/en/programming_manual/pm0214-stm32-cortexm4-mcus-and-mpus-programming-manual-stmicroelectronics.pdf) | 实测下载 2,732,268 字节并读取正文：**§2.3.5 Exception priorities**（手册 p.41）写明"Configurable priority values are in the range 0-15"、"A lower priority value indicating a higher priority"；**§2.3.6 Interrupt priority grouping**（手册 p.41）写明优先级寄存器分为 group priority 与 subpriority 两个字段，且**只有 group priority 决定抢占**，同组同子优先级按硬件索引决定 | 这是 **Cortex-M4** 架构级来源，可支持 F407/G431（均为 M4）的优先级与分组事实；不外推到 M7/M0 等其他内核 |
| S30 | [STM32G4 系列参考手册 RM0440（ST 官方 PDF，Rev 9）](https://www.st.com/resource/en/reference_manual/dm00355726-stm32g4-series-advanced-armbased-32bit-mcus-stmicroelectronics.pdf) | 实测下载 39,045,335 字节并提取正文，确认 **Chapter 12 DMA**、**Chapter 14 NVIC**（14.1 NVIC main features 正文写明 "102 maskable interrupt channels"、"16 programmable priority levels (4 bits of interrupt priority are used)"、"refer to the PM0214 programming manual for Cortex®-M4"）、**Chapter 39 I2C**、**Chapter 40 USART**、**Chapter 42 SPI/I2S**、**Chapter 44 FDCAN** 真实存在（手册 p.436） | 覆盖 G4 系列（含 G431）；通道数 102 与 H7 的 150 **不同**，不得混用 |


### 2026-09-19 Level 2 正文复核增量

本轮官方 PDF 快照存于 ignored 的 `runtime/evidence/m2-01-level2/sources/`，完整 URL、字节数与 SHA-256 见 `runtime/evidence/m2-01-level2/source-manifest.json`。实际读取后的增量结论：

- S28/RM0090：第 30 章列出 F4 USART 接收状态、overrun/noise/framing/parity 错误与 §30.3.13 连续 DMA；第 27 章列 I2C Standard 100 kHz / Fast 400 kHz；第 28 章列 SPI 同步通信及状态/中断管理。
- S30/RM0440：第 40 章列 G4 USART 接收状态、同类错误与 §40.5.19 连续 DMA；第 39 章列 I2C 100/400 kHz 与 Fast-mode Plus 1 MHz；第 42 章列 SPI 同步通信及轮询/中断路径。
- S26/RM0433：第 48、47、50 章分别提供 H7 USART/DMA、I2C 与 SPI 对应事实；H7 事实仍不得外推至 F4/G4。
- S29/PM0214：§2.3.5/§2.3.6 的 0–15 优先级范围、数值越小优先级越高、只有 group priority 决定抢占均已再次核对。

据此，UART/DMA 与 SPI/I2C Seed 已补齐 S28/S30，并显式区分跨系列位名、DMA 映射和 I2C 速率档位。负责人已在 2026-09-19 将六条 Level 2 全部通过并批准；审核记录为 `docs/reviews/review_m2_01_level2_owner_20260919.md`。

### 平台作用域规则（强制）

| reference_id | 覆盖平台 | 可用于 | 不可外推 |
|---|---|---|---|
| `rm0433_stm32h7` | STM32H742/743/753/750 | H7 的外设章节事实 | F4/G4/M0 等任何其它系列 |
| `rm0090_stm32f4` | STM32F405/407/415/417/427/437/429/439 | F4 的外设章节事实 | 其它系列；也不含 NVIC 优先级位宽 |
| `rm0440_stm32g4` | STM32G4 系列 | G4 的外设章节事实（含 102 通道 NVIC 表） | 其它系列；M4 通用结论应引 S29 |
| `pm0214_cortex_m4` | Cortex-M4 / M4F 内核 | 优先级范围 0-15、优先级分组与抢占规则 | M7（H7）、M0/M0+ 等其它内核 |
| `freertos_reference_manual_v10` | FreeRTOS 内核 10.0.0 | Queue/Semaphore/调度/Kernel Configuration 的机制 | 特定移植/平台特有行为（如 ESP-IDF 封装） |
