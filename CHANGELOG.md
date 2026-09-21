# CHANGELOG

## Unreleased — 2026-09-20｜M4-02-DESKTOP 桌面闭环与激活恢复

- 新增按 ProfileSnapshot 代次持久化的 activation；confirm 原子受理裁决、revision、快照与 Operation，后台只激活该代。失败 retry 不再重复确认或创建新快照，累计最多三次；计划/start 同时拒绝空快照与非 ready 代次。
- 新增 `/profiles/{id}/activate`、Profile 激活视图和可逆迁移 `e62a9f8c10bd`；历史只凭可靠同代成功回执回填 ready。上传失败/中断因没有原始字节而明确重新上传，不再假称可通用 retry。
- 桌面补齐无简历入口、独立通用简历、待确认/已确认回看、更正及批量提交；取消五条分页，改为紧凑材料摘要、事实滚动区和提交栏。固定浅色中性令牌，修复系统 dark 下浅字白底。
- 准备页从服务端冻结 JD 恢复原文，提供返回/修改/取消；修改创建新 interview。明确现有 JD 分区语法限制，不冒称支持任意自由文本。面试补齐 skip/end、二次确认、独立操作恢复与 lost-202 原请求重放。
- Report 不依赖优化生成即可显示持久化原题、主答和追问；解释直接可见，导航显示题面摘要。独立 Resume 不再显示“面试四步均已完成”。
- Python 3.11.16 / Node 24.21.0：后端 **295 passed / 2 deselected / 76 warnings**；Ruff 78 files；前端 **9/9**、TypeScript、Vite 112 modules 通过。删除固定文案、孤立常量及纯转发/接线测试，保留可观察边界测试；没有为降低失败数删业务断言。
- 真实 FastAPI/SQLite/openJiuwen Workflow + 显式 synthetic fixture 浏览器实测两入口、21 事实、完整五题/一次追问、优化和打印；实际丢弃控制 202 后刷新重放未重复跳题，分析中 end 保留已保存回答。三个桌面尺寸 × light/dark × 五工作区共 30 组截图。移动端、生产模型质量及负责人独立验收 NOT_RUN；状态 IMPLEMENTED，不写 ACCEPTED。
- 负责人 live 上传中，两次文本 PDF 的 P-EXTRACT 均已进入真实 openJiuwen generator 并向 `deepseek-flash` 发起 HTTP，请求各在私密配置的 45 秒 transport deadline 超时；另一次扫描件正确返回 `requires_text / workflow=not_run`，没有调用模型。旧异常展开把 transport timeout 错写成“来源校验失败”，属于错误分类缺陷。
- 将模型请求异常移到应用端口并新增显式 timeout 子类；openJiuwen 包装链现在保留该类型，document/import、回答分析、回答优化和简历生成分别映射为 `UPSTREAM_TIMEOUT`，不再与模型返回后的 JSON/事实来源校验失败混为一谈。
- 当前独立验收 runtime 使用 ignored、0600 的私密配置副本把单次模型 transport deadline 从 45 秒调到 55 秒，仍受 60 秒 Workflow 总 deadline 约束且不增加隐藏 retry。没有代替负责人再次发送原 PDF；最新后端为 **298 passed / 2 deselected / 78 warnings**，Ruff 78 files 全绿。
- 按负责人指令新增 `MODEL_REASONING_EFFORT`，仅接受 `none / low / high / max`，默认并在当前 0600 live 配置中显式设为 `low`。Answer Analyzer、P-EXTRACT、回答优化与简历生成共用的 `/chat/completions` 请求全部发送 `reasoning_effort=low`；没有增加模型调用、隐藏 retry 或新依赖。

## Unreleased — 2026-09-20｜P-EXTRACT 流式 + 分块超时修复

- 直连探针定位根因：`reasoning_effort=low` 下 deepseek-flash 对 1.2k 字合成简历仍产生 22,420 字符推理、8,369 completion tokens，首 content token 26–28 秒；非流式请求必须静默等整段生成完，真实简历必然突破 55 秒总预算。流式时间线证明推理 token 自 0.63 秒起持续到达（max gap 0.63s），超时不是网络故障。
- 所有 `/chat/completions` 请求改为 SSE 流式：`MODEL_TIMEOUT` 保持单请求总预算，新增 `MODEL_STREAM_STALL_SECONDS`（默认 20，生效 read 取两者较小）检测死流；`reasoning_content` 增量明确丢弃，不进入任何业务内容。Answer Analyzer、P-EXTRACT、回答优化与简历生成共用该路径。
- P-EXTRACT 按 `max_chars_per_extract_call`（默认 1,600 字符）把块文本切成无损连续段分批调用真实 Workflow；每段是入库块的连续子串，逐字来源不变量保持。`extraction_metadata` 新增 `model_calls`；usage 仅在所有调用都报告时按字段求和，否则保持 null；合并后超过 50 条候选全部拒绝，不落部分结果、不静默截断。
- 验证：后端 **311 passed / 2 deselected / 90 warnings**、Ruff 78 files 全绿；live 实测 2,184 字合成简历 `succeeded / 28.1s / model_calls=2 / usage 2101+7259=9360（cost null）`，19 条候选全部逐字命中块文本。OCR 未实现（P1，负责人确认暂不做；扫描简历仍走 `requires_text` 粘贴路径）。
- 负责人 live 复验：真实上传两次 `document.import` succeeded，超时路径关闭。操作失败原因透出修复：`operations_runner` 此前只对上传保留领域 message，其它操作落错误码通用文案；现在所有 DomainError 优先显示受控可行动原因（如“JD 中没有可识别的岗位要求（需要显式标记如「必要项：」「加分项：」）”，不再是“请求格式或参数无效”）。错误码/字段/事件契约无变化。全量 **311 passed**、Ruff 78 files 全绿，live 按原输入复现确认新提示。

## Unreleased — 2026-09-20｜岗位输入改为三分区表单

- 准备页 JD 输入从“单个正文框 + 手写分区标记”改为岗位名称 + 必要项 / 加分项 / 岗位职责三个分区框，一行一条；`jd_text` 由新增纯模块 `apps/web/src/jdSections.ts` 确定性拼装（空分区省略、行去空白、固定顺序），**网络契约与后端零改动**。编辑回填反向解析；标记之前的旧行进入“未归位”提示，不自动归类、不静默丢弃、不把加分项升级为必备要求。
- 验证：前端 **14 passed（新增 5 项分区序列化用例：拼装、幂等往返、unassigned、空输入、无标记不猜）**、TypeScript 与 Vite build 通过；真实浏览器端到端：三分区填写 → 计划生成“3 项岗位要求 · 5 个主问题方向”，核心 2 / 优先 1 分类正确，冻结原文可见，“修改岗位 / JD”回填逐字一致。docs/08-ux.md 同步；api.md 无变化。

## Unreleased — 2026-09-20｜重试门控修复与失败恢复键完整浏览器 E2E

- 复盘发现 §53 接线引入的新 bug：`canRetryAnalysis` 漏查 `operation.error.retryable`（Report/ResumeDraft 两页都查了），恢复键跨浏览器后预算耗尽的失败回答会亮出只会吃 409 的假"重试分析"按钮。修复为三页同构门控（retryable===true 才出现）；AnswerComposer 新增 `retryBudgetExhausted` 文案分支——有恢复键但预算用尽时说"重试预算已用完，可跳过本题或提前结束"，不再谎称"没有可恢复编号"。
- 完整确定性浏览器 E2E（临时把 runtime 模型配置改为 MODEL_TIMEOUT=0.001/MODEL_MAX_RETRIES=1 制造真实超时失败，跑完还原并校验 sha256 一致、重启 API）：提交回答→超时失败→"重试分析"按钮出现→**清空 sessionStorage 刷新页面按钮仍在**（服务端恢复键跨刷新）→点重试→预算耗尽文案正确（假按钮不出现）→跳过本题→第 2 题再失败→恢复配置重启后点重试→分析完成→Policy 进入澄清追问。恢复键→重试→成功→继续面试的全链路首次拿到浏览器实证。
- 过程中发现并如实记录：第一次尝试改根目录 `.env.model.local` 无效——API 实际读 `runtime/owner-validation-live/.env.model.local`（`ZHIJUE_MODEL_ENV_FILE`）；上一轮"真实超时"其实是语义校验失败（模型返回了但过不了契约），当时未察觉。
- 验证：tsc + vitest 14 passed + vite build；E2E 面试 interview_7057f4f29f12fb1b5a6a（synthetic 演示档案内可审计操作）。api.md 无变化（retryable 门控是 UI 语义，契约早已规定）。

## Unreleased — 2026-09-20｜第三轮前端逻辑审查：失败恢复键断链修复

- 静态通读五页 + 浏览器实测发现系统性缺陷：**操作失败后服务端把 `active_operation_id` 清成 null，前端跨页面/跨刷新就再也找不到“重试”的入口**——“重试分析/重试回答优化/重试简历生成”只活在 sessionStorage 里，换浏览器、清缓存或从历史 URL 直入时，用户面对失败态永远只剩“预算已用完”文案，即使服务端其实还有重试额度。后端明明持久化了恢复键（`improvements_operation_id`/`generation_operation_id`/`accepted_operation_id`），视图层却没暴露。
- 契约（api.md 先行）：ReportView/ResumeDraftView 的 `active_operation_id` 在 failed 态**保留失败链尾操作**作为恢复键，只有 succeeded 落库才清 null；QuestionView.accepted_answer 新增 `retry_operation_id`（仅 failed 非 null，指向 parent 链链尾——从中间节点重试会分叉绕过累计预算）。
- 后端：`release_failed_operation`（content + interviews 两处）不再清 active_operation_id；`accept_retry` 门禁改为“failed 且恢复键指向本操作链”合法；`get_view` 用 `_failed_retry_tail`（沿 parent 链取最新 child）暴露 `retry_operation_id`。
- 前端：ReportPage/ResumeDraftPage/InterviewPage 在 failed 态优先用服务端恢复键接回 Operation 监控与重试按钮，sessionStorage 降级为兜底；PreparePage `operationSettled` 失败分支补清陈旧计划操作键（旧代码 failed 时 no-op，每次进页面重复拉取并短暂误锁）。
- 验证：后端 **317 passed**（新增 2 个恢复键契约测试：失败→链尾推进→成功清除；草稿失败保留恢复键；interview 精确形状断言更新）+ Ruff 全绿；真实浏览器端到端——live 简历生成真实超时失败后，**无 sessionStorage 的新浏览器直入草稿 URL**，页面仍显示“简历生成 · 处理失败”操作状态与如实预算文案；陈旧键注入测试确认 500ms 内被清除；计划生成流程回归正常（8 项要求 · 5 方向 · 开始按钮可用）。

## Unreleased — 2026-09-20｜事实选择按钮逻辑修复（切换语义 / 过度锁定 / 误清竞态）

- 浏览器实测确认三处按钮逻辑缺陷：① 采用/不采用/更正都渲染 `aria-pressed` 按下态，但**再点已选中按钮不取消**；最坏是“更正”——选中后输入更正正文，再点高亮的“更正”会把正文**静默重置回原文**（数据丢失级）。② 选择/编辑是本地动作（docs/08 明确不写 API），却被 `mutationDisabled` 整体禁用——后台简历生成/上传解析期间用户不能勾选事实。③ confirm 受理后 `setDecisions({})` 清空**全部**选择，运行期间新勾选的会被误删。
- 修复：`ClaimConfirmList` 的 `decide()` 实现真实切换（再点已选动作 = 取消该条；“更正”再点 = 退出编辑，重新进入时以原文开新会话）；组件移除 `disabled` prop，选择、编辑、取消全部选择不再被后台操作锁死，只有“批量提交”保留 `mutationDisabled` 门禁；提交受理后只清除本批 `claim_id` 集合内的选择。
- 验证：真实浏览器逐项量测——再点“采用”取消选择、更正输入自定义正文后切换动作不丢编辑、简历生成 running 期间勾选生效且提交禁用、提交后服务器与 UI 一致（测试事实撤回：proposed 0 / confirmed 38 / revision 4）；tsc + vitest 14 passed + vite build。docs/08-ux.md §2 补按钮切换与本地动作语义；api.md 无变化。

## Unreleased — 2026-09-20｜第二轮前端布局与交互审查：面试 ready 态矛盾修复

- 动态审查（真实浏览器逐路径量测五页：非法 ID 直入、前进/后退、1024px 窄视口、键盘 Enter/Space、三连点幂等、更正/取消编辑、手工表单校验、报告标签切换）发现 **InterviewProgress 把“还没有当前题”一律渲染成“本场提问完成 · 5 / 5”**：ready 态面试同屏出现“完成 5/5”与“面试尚未开始”两个互斥事实，并残留两个永远禁用的跳过/结束按钮（与已修的 completed 终态同类缺陷）。
- 修复：`InterviewProgress` 新增 `started` 语义（active/finishing/finish_failed/completed 为已开始），未开始渲染“尚未开始 · 0 / 5”、进度 0、无激活点；控制区改为仅已开始且未完成时渲染。completed 路径回归确认仍显示“本场提问完成 · 5 / 5”。
- 附带：删除档案成功后同时清理 `prepare` 作用域的 localStorage 操作键（此前只清 profile/resume，prepare 键会残留）。
- 验证：tsc + vitest 14 passed + vite build；浏览器实测 ready 态“尚未开始 · 0 / 5”+ 无控制区 + Alert 一致，completed 态不回归。三连点“使用演示岗位配置”服务端仅创建 1 条 interview（幂等键生效，动态证实）。api.md 无变化。

## Unreleased — 2026-09-20｜“查看解析文本”抽屉交互缺陷修复

- 浏览器实测发现 `DocumentBlocksDrawer` 三处真实交互缺陷：① anyui Drawer 不处理键盘，**ESC 完全无效**；② 面板关闭动画进行中快速重开，leave 过渡竞态把**全屏遮罩滞留在页面上吞掉所有点击**（面板已消失、mask 仍在，页面看似死锁，只能盲点遮罩恢复）；③ 打开/关闭后焦点留在 body，键盘用户落空。
- 修复：改为**条件挂载**（卸载整个 Drawer 换取确定性状态，杜绝过渡竞态残留）；本组件接管 window keydown 实现 ESC 关闭；打开时焦点移入“关闭”按钮、关闭后还给触发按钮；`role="dialog"` 与遮罩点击关闭保持。
- 验证：真实浏览器四条路径逐项量测（打开→遮罩点击关 / 打开→ESC 关 / ESC 关后立刻重开→遮罩关 / 关闭按钮关），每次 mask/panel/滚动锁/焦点四指标全对；tsc + vitest 14 passed + vite build 通过。api.md 无变化。

## Unreleased — 2026-09-20｜按钮↔API 双向审计：补齐删除/运行信息端点与桌面布局整改

- 双向审计结论：api.md 20 端点中 `DELETE /profiles/{id}` 与 `GET /runtime/info` **有契约、无实现**（文档先行、代码缺席）；前端无孤儿按钮。本轮补齐实现而非删文档。
- 后端：`profile.delete` 先 tombstone（status=deleting、拒绝其余写入、拒绝与在途操作并发），后台先删 Knowledge 索引（SDK `delete_documents`，M0-03 已验证生命周期），再单事务级联清理档案/材料/事实/快照/会话/草稿与关联 Operation+事件，只保留删除回执链；索引失败数据库不动、档案保持 deleting，failed/interrupted 的删除回执从 `ProfileView.active_operation_id` 可恢复并走通用 `/retry`（预算累计三次）。`runtime/info` 返回 run_mode/data_mode、锁定版本、feature_flags（事实性常量）与依赖健康摘要，不含密钥/路径。OpenAPI 契约物 `contracts/openapi.json` 重新导出（24 paths）。
- 前端：api.ts 增 `deleteProfile`；资料页新增“删除档案”危险区（折叠 + 两步确认 + 不可恢复说明），成功回无档案入口；页头常显 `live · synthetic` 模式徽章（闭合“MUST 明示运行模式”硬约束）；`vite.config.ts` 代理目标支持 `VITE_PROXY_TARGET` 覆盖（默认仍 8000）。
- 布局整改（浏览器量测驱动）：已确认/待确认列表获得视口高度上限并真实内滚（38 条约 4,900px 页面 → 800px 视口内，提交栏常驻）；简历失败态不再显示误导的“0 项已确认资料”，重试预算耗尽文案改为如实说明；面试 completed 终态不再渲染禁用的跳过/结束按钮；“更正”按钮垂直居中；“简历整理”改胶囊样式。
- 验证：后端 **315 passed / 2 deselected**（新增 `tests/test_profile_deletion.py` 4 项：级联清理+回执保留、revision/幂等重放/缺 key 拒绝、索引失败 deleting 保持+恢复入口+重试成功、runtime/info 无泄漏）；前端 **14 passed** + tsc + build；真实浏览器端到端：创建临时档案→删除→`profile.delete succeeded`、档案行物理删除、页面回无档案态、模式徽章/内滚/终态/失败文案逐项量测通过。api.md 实现状态与 docs/08-ux.md 同步。

## Unreleased — 2026-09-20｜PDF 上传待确认事实缺口修复

- 独立验收确认真实 PDF 已解析为 Document/SourceBlock，但旧 `document.import` 从未生成 Claim，页面因而显示 0 条待确认事实；同时 `expected_revision` 被忽略。原始回归稳定复现 revision 未增长与 stale upload 被接受。
- API-first 将上传语义闭合为 P-EXTRACT：live 模式通过真实 openJiuwen Workflow 让生产 Content Generator 只选择 SourceBlock 内逐字候选，服务端拒绝未知块、非逐字引文、联系方式、重复项和超过 50 项的输出。Document、SourceBlock、proposed Claim 与 Profile revision 在同一事务提交；扫描 PDF 不调用模型，也不伪造候选事实。
- 新增 `claim-extraction-result.schema.json`、真实 Workflow/模型 transport/语义校验/上传原子性回归；上传成功 Operation result 返回 revision、candidate count 与去敏 extraction metadata。路由、OpenAPI 外形、数据库 Schema、迁移和依赖不变，`api.md` 与前后端展示契约已同步。
- synthetic 两页 PDF 经实际 Vite + FastAPI live 页面显示 4 条可逐字回查的待确认事实；P-EXTRACT 1 次真实 HTTP，2.86 秒，usage 461/658/1119，cost=null。该单样本不证明真实简历召回率、p95 或价格；负责人需要在已重启的干净 runtime 重新上传原 PDF 完成独立复验。
- 最终后端 281 passed / 2 skipped / 74 warnings，Ruff 74 files 全绿；前端 16/16、TypeScript、Vite 112 modules 通过；规范 47/47；doctor 18 PASS / 0 WARN / 0 FAIL；完整性 225/225。M4-02 保持 IMPLEMENTED，不写 ACCEPTED。


## Unreleased — 2026-09-20｜M4-02 生产 Content Generator synthetic live

- 新增 `smoke.content_model`：使用 synthetic 回答与两个确认 Claim，分别以生产 `OpenAICompatibleContentGenerator` 执行 coaching/resume；两次逻辑操作各只发一次真实 HTTP 请求，并通过真实 openJiuwen `Start → Generator → SemanticValidation → End`。
- 首轮 live 的两个模型响应都是合法 JSON，但 Prompt 只引用模型不可见的 Schema 文件：coaching 使用错误别名 `citations/quote` 并遗漏必填字段，resume 遗漏 `schema_version/title/item_id/reason`；原有 Schema 正确拒绝，没有修复模型输出或落部分结果。
- P-COACH/P-RESUME 现逐项声明精确字段、嵌套形态、对象数组和禁止别名；新增 transport 回归验证真实 system message，而不是只断言常量。修正后同一模型两项均通过原 Schema、ID、逐字引文、Claim、数字/责任/技术词边界。
- 成功轮 `deepseek-flash` 共 2 次 HTTP：coaching 27.727351 秒、usage 669/6377/7046；resume 10.8392 秒、usage 535/2325/2860。provider 未返回价格，cost 保持 null / NOT_MEASURED；单样本不形成质量、稳定性或 p95 结论。
- 最终后端 273 passed / 2 skipped / 73 warnings，Ruff 74 files 全绿；前端 16/16、TypeScript、Vite 112 modules 通过。HTTP API、OpenAPI、数据库、迁移、依赖和前端均无变化；独立验收仍 NOT_RUN，M4-02 保持 IMPLEMENTED。


## Unreleased — 2026-09-19｜五页首屏收口与展示语义修正

- 重构 Start、Prepare、Interview、Report、Resume 五页信息密度：桌面首屏保留真实主 CTA，移动端恢复根页面滚动；21 条事实、17 条 JD、6,000 字回答、五题报告和 20 条简历正文由各自工作区局部滚动承载。
- Start 候选事实按服务端顺序每页 5 条；Prepare 使用受控能力中文词典和未知方向 fallback；Report 按 `root_question_id` 提供单题导航及“评分依据 / 回答优化”；Resume 按 `item_id/claim_id` 展示当前条目来源，不暴露裸内部 ID。
- 统一四步导航、业务状态、criterion/finding/level 与失败文案；null 分数和 0 分严格分开。Report 页签/问题、Start 分页、Resume 条目选择均为只读交互，没有写 API。
- Operation monitor 首次观察终态后立即停止 interval/EventSource/fetch，迟到 running 不覆盖终态。Report improvements、ResumeDraft 创建及两类 retry 对网络未明确响应保留原 request body 与 `Idempotency-Key`，显式重试逐字段复用。
- 打印媒体解除屏幕工作区高度/overflow，accepted 简历只打印完整正文。HTTP API、OpenAPI、Python DTO、数据库、迁移和依赖无变化。
- Node 24.21.0 下前端 16/16、TypeScript、Vite 112 modules 全绿；后端 272 passed / 2 skipped、Ruff 全绿、规范 46/46。Chromium 两轮视觉检查覆盖 1366×768、1440×900、1920×1080、390×844、125%/200%，五页无横向溢出；fixture 外部模型调用 0，生产内容模型与独立验收仍 NOT_RUN。


## Unreleased — 2026-09-19｜M4-02 事实约束生成与 Report/Resume 功能基线 IMPLEMENTED

- API-first 新增显式 `report.coach` / `resume.compose` Operation、Report 改写生命周期、ResumeDraft 生成/读取/确认、两个 ready 事件和 parent-linked retry；`InterviewView` 返回 `profile_id`，浏览器不猜资源关系。
- 回答优化与简历生成均通过真实 openJiuwen `Start → Generator → SemanticValidation → End`。服务端在落库前校验 JSON Schema、允许 ID、逐字回答引文、Claim 绑定、数字/责任边界和占位符；失败保留原回答、分数、Claim 与资料快照。
- 统一回答分析与内容生成的重试预算：单个 Operation 只发一次模型 HTTP 请求，transport/Schema/语义失败和用户显式 retry 共同消耗 `MODEL_MAX_RETRIES + 1`（硬上限三次）；补充累计预算耗尽回归，避免“每个业务重试再做三次 transport retry”放大为九次调用。
- 新迁移 `b4d7c2e91f30` 持久化 Report 改写状态及 ResumeDraft，并防止同一快照/目标重复草稿。OpenAPI、Python DTO、前端网络类型与 API 客户端同步。
- 新增 `/interviews/:interview_id/report` 与 `/resume-drafts/:draft_id` 功能页面：null 分数保持未评分；改写显示原文、来源和待补事实；简历逐项展示 Claim 来源，确认前不可打印，打印媒体只包含已确认正文。M3-03 前三页视觉未改，两个新页面尚未 Product Polish。
- 后端 272 passed / 2 skipped / 73 warnings，Ruff 全绿；锁定 Node 24 下前端 12/12、TypeScript 和 Vite 114 modules 通过；规范 46/46、doctor 18/0/0、完整性 222/222。fixture Chromium 最终复验跑通报告原文→回答优化→简历 Claim 来源→确认→打印媒体。本轮外部模型/embedding 调用 0，usage/cost null；生产内容模型 live 与独立验收 NOT_RUN，故状态为 IMPLEMENTED。

## Unreleased — 2026-09-19｜M4-01 评分与报告 VERIFIED

- `api.md` 先行落地 `POST /interviews/{id}/control` 与 `GET /interviews/{id}/report`：skip/end 通过 Operation 串行执行，重复 end 返回同一操作；报告读取只返回持久化结果，不触发模型。
- 新增纯确定性 scoring domain 和 `ReportingService`。主答/追问按冻结 criterion 合并且只计一次权重；coverage 低于 60%、未测、跳过或 disputed 均保持 null；至少三根 scored 根题后按根题等权、decimal ROUND_HALF_UP 生成总分。
- 自然五题结束与主动 end 均在短事务写五个唯一 Assessment、单场唯一 Report、`report.ready` 和 completed。回答中 end 先记录 stop request，允许当前 validated Observation 安全落库后再汇总；skip 不调用模型。
- 报告写入失败后的 operation retry 复用已保存 Observation/Decision，不重新调用 Analyzer。进程启动恢复同时把 queued/running 标为 interrupted，因为内存 `BackgroundTasks` callable 均未持久化，不能伪装自动重放。
- 新增 Alembic `7f1b9c4d2a60` 唯一约束、OpenAPI 快照、Python DTO、前端 control/report 类型与客户端方法；冻结三页没有新增 Report UI 或控制按钮，M4-02 回答优化/简历草稿未开始。
- 全量后端 261 passed / 2 skipped / 63 warnings，Ruff 全绿；规范 44/44；锁定 Node 24.21.0 / pnpm 10.34.5 下前端 11/11、production build 112 modules；doctor 18/0/0，完整性清单 211/211。真实 FastAPI/openJiuwen Workflow/SQLite + fixture Analyzer 五题烟测得到 complete、5 scored roots、overall_score=67；本轮付费模型/embedding 调用 0。


## Unreleased — 2026-09-19｜M3-01 业务文本模型 live VERIFIED

- 新增 `smoke.answer_model`：只从显式 0600 私密文件读取模型配置，使用 synthetic 回答、approved UART/DMA Seed 0.2.1、生产 `OpenAICompatibleAnswerAnalyzer` 和真实 openJiuwen `Start → Analyzer → SemanticValidation → DeterministicPolicy → End`，证据独占写入 ignored `runtime/`，不保存密钥或模型原文。
- 第一轮 `deepseek-flash` 请求真实返回，但 Prompt 没有明确 `finding` 的枚举语义，模型把解释文本写入该字段，服务端按 Observation Schema 拒绝；没有放宽 Schema、修复输出或默认成功。Prompt 现明确所有枚举、criterion 复制规则、level/quote/reference 约束。
- live 失败同时证明 SDK 会记录组件异常；为防无效模型字段携带回答派生文本进入 ERROR 日志，Workflow 边界改为固定 `analyzer output failed contract validation`，详细领域校验仍保留在纯函数单测。新增真实 Workflow 日志脱敏回归。
- 第二轮 1 次 HTTP 调用通过：10.650749 秒，Observation `relevant / adequate / supported / level=3`，程序 Policy 输出 `NEXT / ADEQUATE_EVIDENCE`；usage 为 input 1156、output 2544、total 3700，费用未知保持 null。首轮失败调用的 usage 未穿过失败边界，明确记为 NOT_MEASURED。
- 全量后端 248 passed / 2 skipped / 55 warnings，Ruff 全绿，规范 44/44，生产 live 装配同时识别 Knowledge/model 为 configured。API、OpenAPI、数据库、迁移、前端、依赖和四动作 Policy 均无变化；M3-01 升为 VERIFIED，下一任务为 M4-01 评分与报告。

## Unreleased — 2026-09-19｜M3-03 最终收尾与冻结

- 对齐后端 `CreateInterviewRequest` 真值：`jd_text` 最多 8,000 字符、`jd_source_name` 最多 200 字符。前端由同一组导出常量驱动两个 `maxlength`、提交前校验及 JD 正文实时字符计数，不截断超限内容后静默提交。
- Prepare ready DOM 调整为岗位摘要 → Coverage/五题 Plan → 开始动作 → 技术详情；数据仍只来自 `InterviewView.jd_requirements`、`coverage_map`、`root_plan.slots`，服务端顺序、priority 和业务流程不变。
- Product Polish commit `bae74d50d8af2821f93501ee700eccc059af5196` 已推送至公开 `main`。修正 handoff/process 中遗留的“尚未提交”和“下一任务等待 M4”冲突；当前唯一下一任务仍为 M3-01 业务文本模型 live 验证。
- 锁定 Node 24.21.0 / pnpm 10.34.5：Vitest **11/11 passed**，TypeScript + Vite production build **112 modules**。实际 Vite 页面以 intercepted fixture response 检查 1366×768、1440×900、390×844，Prepare 顺序正确且无横向溢出。
- FastAPI、OpenAPI、`api.md`、数据库、Workflow、Policy、Operation/SSE、retry、`/start` 与面试页均为 0 变化；业务文本模型 live 仍 `NOT_RUN`。M3-03 三页前端正式 `FROZEN`，M4 未启动。

## Unreleased — 2026-09-19｜M3-03 三页 Product Polish

- 在不改变 FastAPI、OpenAPI、`api.md`、数据库、路由、Interview/Answer 状态机、Operation/SSE 与 retry 的前提下，完成三页纯展示层精修；业务能力、API 与状态机均为 0 变化。
- Header 品牌字形由“知”统一为“职”，品牌显示“职觉 ZhiJue / AI 面试陪练”，步骤与页面 Eyebrow 统一中文；清除 Coverage Map、Interview Plan、Decision Summary 等用户可见英文模块名。
- 普通业务卡片改为 border + background + whitespace，不再使用阴影；问题卡保留极轻阴影。主卡片/问题卡 12px、Input/Button 9px、Tag 6px，并补充 Linux 常见中文字体回退。
- Prepare 页从真实 `jd_requirements` 派生四类 tier 数量，17 条示例在默认折叠的原生 `details/summary` 中展开；1366×768 首屏保留主 CTA，Coverage/Plan 继续双栏，internal ID 仍只在技术详情中。
- Interview 页保持约 65%:35% 双栏；MAIN 显示“面试依据”，PROBE/CLARIFICATION 分别显示“为什么继续追问/为什么需要澄清”与对应方向。完成态只说明尚未生成正式报告，不新增评分、报告或控制入口。
- 锁定 Node 24.21.0 / pnpm 10.34.5 下前端 **10 passed**，TypeScript + Vite production build **112 modules**；实际 Vite 页面以 intercepted fixture response 检查 1366×768、1440×900、1920×1080、390×844，无横向溢出。业务模型调用 0，token/cost 为 null。

## Unreleased — 2026-09-19｜M3-03 前端契约与语义漂移修正

- 以当前后端 `CapacityLimitedError` 和 routes 为真值，把前端及 UI Contract 的错误码从不存在的 `OPERATION_CAPACITY_LIMITED` 统一为 `CAPACITY_LIMITED`；429 仍是 `retryable=true`，回答请求失败不会被当作提交成功。
- Prepare 页明确区分 start 按冻结五个 Slot 实例化本场主问题，以及回答后 Policy 动态决定 PROBE / CLARIFY / NEXT / END；未改变后端实例化逻辑。
- JD 来源展示改为只按服务端 `source_type` 区分 synthetic、用户提供、官方公开、公开岗位衍生四类，不从 `source_name` 推断可信度。
- 补齐 `counterfactual`、`pushback`、`reflection` 三种用户可读映射，保持 pushback 与 counterfactual 独立，未知内部值继续走安全 fallback。
- 前端契约测试由 7 项增至 10 项并全部通过；TypeScript + Vite production build 通过，112 modules。后端代码、OpenAPI、`api.md`、数据库和依赖均无变化；M3-03 保持 VERIFIED，业务文本模型 live 仍 NOT_RUN。

## Unreleased — 2026-09-19｜M3-03 三页 P0 前端 VERIFIED

- 将旧的单页资料/计划工作台重构为 `/start`、`/profiles/:profile_id/prepare`、`/interviews/:interview_id` 三页纵切面；使用直接导入的 AnyUI 组件与现有 CSS Tokens，不引入 Liquid Glass、路由包或第二套业务状态源。
- `/start` 完成真实 Profile、multipart PDF、Document/blocks、手工 fact、Claim 确认和快照门禁；空 `proposed_claims` 明示“没有可确认候选事实”，不填假资料。扫描 PDF 只提示 P0 文本粘贴降级，不冒充 OCR。
- `/prepare` 严格按服务端来源真相生成演示或用户 JD，只从 `InterviewView` 渲染来源、Requirements/Coverage Map 与精确五个 Slots；internal ID 仅出现在默认折叠技术明细。
- `/interviews` 完成 caller-owned `client_turn_id`/`Idempotency-Key`、202 accepted 原回答展示、PROBE/CLARIFY/NEXT/END、Operation SSE + polling、失败原文保留及 operation retry。网络不确定性重试复用逐字相同请求；revision conflict 重新读取，capacity limited 不伪装成功。
- 新增 7 个 Vitest 前端契约测试并接入 CI；真实浏览器 fixture 纵切面覆盖 PDF→确认→JD→计划→五题结束、分析失败重试、SSE 被阻断后的 polling 收敛，以及 390×844、768×900、1366×768、1440×900、1440×1000、1920×1080 六组视口无横向溢出。生产构建通过，112 modules。
- 新增 `@any-design/anyui@0.5.2`、其显式运行时 peer `@iconify/react@6.0.2` 和测试依赖 `vitest@4.0.18`；全部可本地安装/构建，不增加云部署依赖。HTTP API、OpenAPI、数据库 Schema 与迁移均无变化。
- 本轮业务回答模型仍为显式 `ScriptedAnalyzer` fixture；真实 openJiuwen Workflow/SQLite/Operation/SSE 路径保留。业务模型 live、token/cost、评分、回答优化和报告仍 `NOT_RUN`，没有伪造结果。

## Unreleased — 2026-09-19｜公开仓库发布

- 将工程按工具链/CI、后端契约与测试、前端工作台、规范交接整理为干净公开 `main`；旧本地 `master` 只作回退点，未推送。
- 创建并推送 PUBLIC 仓库 `https://github.com/hongyue0721/zhijue_face`；默认分支和唯一远端分支均为 `main`。
- 发布前移除工作站绝对路径、私有简历文件名/身份标签/内容指纹；`.env.local`、`runtime/`、真实材料和运行证据继续 ignored。M2-02 smoke 只接受显式私密输入，不扫描工作站目录。
- 发布验证：后端 247 passed / 2 skipped、Ruff 全绿；规范 44/44；doctor 18/0/0；前端锁定 Node 24 + pnpm 10.34.5 build 通过；最终完整性清单 170/170。

## Unreleased — 2026-09-19｜M3-01 回答分析/Policy IMPLEMENTED，M3-02 后端可靠性 VERIFIED

- `POST /interviews/{id}/start` 把五个冻结 slot 实例化为可追溯 Question；approved Seed 只做精确 competency 匹配并且单场不重复，无匹配时使用明确 `seed_id=null` 的非技术回退题，不伪造技术审核来源。
- `POST /interviews/{id}/answers` 使用真实 openJiuwen Workflow 执行 `Start → Analyzer → SemanticValidation → DeterministicPolicy → End`。模型仅能提出 Observation；服务端校验 ID、冻结 Rubric、原文精确引文和审核 reference，Policy 只输出 `CLARIFY / PROBE / NEXT / END`，没有模型自决动作或招聘结论。PROBE 文案由 Policy 选中的缺口和冻结 Rubric 的合格阈值确定性生成，不再用与缺口无关的通用追问，也不泄露内部 criterion ID。
- Answer、Operation 与 revision 的短事务受理由单进程共享锁串行化；并发相同 key / `client_turn_id` 只产生一份 Answer/Operation，不把 SQLite 竞争异常抛给调用方。成功 Observation/Decision/下一题/事件原子提交；失败保留原 Answer，retry 新建 parent-linked operation、累计最多三次并复用原文；进程重启把 running 标 interrupted，不静默重放上游调用。
- 收紧隐私边界：SDK 日志提升到 WARNING 并移除文件 sink；operation 失败只公开固定契约文案，不回显 SQL 参数、回答原文或模型内部异常。模型配置仅从显式 0600 私密文件读取，禁用 ambient environment，transport 总尝试上限为三次。
- 新增 Answer→accepted Operation 唯一关系、Question.seed_id 可空迁移和 OpenAPI 快照；`api.md`、后端 DTO、前端网络类型、数据模型、架构、Workflow、环境模板同步。前端只同步 start/answer/retry 契约和只读状态文案，尚未设计答题交互；未增加依赖。
- 验证：Ruff check/format 全绿；后端全量 **247 passed / 2 skipped / 0 failed / 54 warnings**；规范 **44/44**；fixture FastAPI 冒烟真实跑过 openJiuwen Workflow，202→succeeded→NEXT，私人回答标记未进入输出。锁定 Node 24 下前端 TypeScript/Vite build 通过；浏览器 fixture 实际渲染新状态文案且不再出现过期 `technical_review` 门禁。
- M3-01 保守记为 IMPLEMENTED：测试的 ScriptedAnalyzer 只替换外部文本模型，当前 `.env.local` 缺少六个 `MODEL_* / API_*` 业务变量，业务模型 live 调用 `NOT_RUN`，token/cost 为 null。M3-02 的持久化、幂等、事件、retry 与恢复按本地后端范围 VERIFIED；前端接口设计尚未开始。


## Unreleased — 2026-09-19｜M2-01 六条 Seed Level 2 PASSED / APPROVED

- 实际下载并提取 FreeRTOS V10.0.0 issue 1、ST PM0214 Rev 10、RM0090 Rev 22、RM0440 Rev 9、RM0433 Rev 8 官方 PDF；URL、字节数、SHA-256 与正文定位记录于 ignored 的 `runtime/evidence/m2-01-level2/source-manifest.json`。
- 六条 Seed 的 reference point、red flag 与平台边界逐条核对：Queue 改为手册实际的固定 item-size 复制语义并补 ISR 边界；period 的 tick 分辨率改为带来源的技术要点；mutex 删除无原文支撑的 `"lessen/minimize"` 归因。
- UART/DMA 与 SPI/I2C 新增 F4/RM0090、G4/RM0440 来源，和 H7/RM0433 分系列陈述；明确 F4 I2C 100/400 kHz、G4/H7 另列 1 MHz，禁止跨系列套用位名、DMA 映射或清除顺序。
- 新增主演示外设种子必须覆盖 F4/G4/H7 登记来源的规范校验与回归用例。负责人明确选择“六条全部通过并批准”；Seed 批准版本为 0.2.1，Level 2 均 passed，统一审核记录为 `review_m2_01_level2_owner_20260919`。批准不扩展到 24 条。
- 修复 `SeedBank` live 门禁与权威配置不一致的根因：原实现声称读取 `config/demo.yaml`，实际却硬编码放行 `technical_review`，且 `live_only=True` 仍返回整库。现改为读取 `live_allowed_review_status=approved`，未批准题库显式失败，混合题库只返回 approved 条目。
- 验证：Seed 专项 12 passed；后端全量 186 passed / 2 skipped / 39 warnings；规范 44/44；Ruff 全绿。批准后的 SeedBank 指纹为 `1c6716b90449d375`。
- API、DTO、SSE、数据库、迁移、前端与依赖无变化；无 LLM/embedding 调用，token/cost 均为 null。

## Unreleased — 2026-09-19｜M2-03 面试准备工作台 VERIFIED

- 前端新增完整 `InterviewView` 网络类型与 `POST/GET /interviews` 客户端，所有网络字段保持 snake_case；Operation 终态后再读取服务端 Interview 快照，不把 HTTP 202 当成功。
- 工作台展示已确认资料快照、JD 来源、Coverage Map 和五个验证槽位；synthetic 来源显著标记“不是企业真实招聘公告”，unknown 明示“材料未体现，不等于不会”，related_context 与直接证据分开展示。
- 首题严格停在审核门禁：Seed 仍为 `technical_review`、所有 `seed_id=null`，页面没有题目文本和回答入口，没有调用 LLM。
- 真实浏览器点击生成计划：Operation `operation_a5690d32777560d56c06` succeeded，Interview `interview_46d8ee8bc76efccb75df` 返回 5 Slots；URL 写入恢复键，刷新后仍能恢复来源警示、计划和首题锁定态。视觉证据：`runtime/evidence/m2-03/workbench-live-final.png`。
- 固定 Node 24 下 TypeScript `--noEmit` 与 Vite build 通过；后端全量 pytest 182 passed / 2 skipped，规范校验 43/43。

## Unreleased — 2026-09-18｜M2-02 JD 来源持久化、Requirement 抽取与五题计划生成 VERIFIED（事实性与溯源闭环）

- **P0 事实性与负向校验**：排查并彻底清除"DMA 双缓冲"虚假摘要，单元测试增加负向回归测试 `test_negative_regression_ungrounded_fact_rejected`，强校验任何非 SourceBlock 子串均抛出异常拒绝；建立 Demo 关键事实检查集并测得 **8/8（100.0%）** 召回率。
- **中断 EvidenceRelation 体系重构**：查明 Demo Resume v1 对中断直接术语出现频次为 0；正式定义 `EvidenceRelation`（`DIRECT_CLAIM`、`DIRECT_EXPERIENCE`、`RELATED_CONTEXT`、`MODEL_INFERENCE`）；强制 TIM/输入捕获等仅作为 `RELATED_CONTEXT`，严禁把 unknown 升级为 unverified；在 Coverage Map 中中断严格保持 `status=unknown` 且 `evidence_ids=[]`。
- **JD 来源真实性纠错**：删除使用不可验证示例域名与未经记录 `confirmed_by` 的 `demo-jd-v2.md`，撤回 `REAL_JD_DERIVED` 宣称；默认 Demo JD 固定标记 `synthetic_demo_jd`，用户粘贴文本固定为 `user_provided`，客户端不能自报来源类型；真实衍生来源缺少上游 URL/时间/hash/派生 hash/转换说明时以 `JD_PROVENANCE_INVALID` 拒绝。
- **Planner 多维度业务优先级算法**：废除单纯字典序 tie 缺陷，综合考量岗位重要度、验证需求、证据关系、JD覆盖密度与证据丰富度；来源纠错后的 live 五槽位为验证(40)、UART/DMA(39)、ownership(39)、中断(38，unknown+related_context)、C基础(37)。
- **真机 Live 运行全链路存证**：私有登记的 Demo Resume v1 + 显式合成 Demo JD 端到端执行，21 条事实向量化入库、8 条 Requirements、5 Slots、8/8 关键事实检查通过。私有输入指纹和运行存证只保存在 ignored runtime，不随公开仓库发布。
- 全量回归 182 passed / 2 skipped / 0 failed / 39 warnings；`tools/validate_spec.py` 43/43 passed；M2-03 已完成，下一门槛为六条 Seed 的 Level 2 审核与负责人批准。
## Unreleased — 2026-09-18｜仓库落盘（本地提交 7ac1b7f）

- 首次提交：145 文件 / 24,354 行，含规范包、契约、示例、环境锁、M0 探针、M1 业务资料链与 HTTP/最小确认界面、M2-01 种子与 ADR-013。
- 不含 `runtime/`（私有原件与业务库）、`.env*`（真实密钥）、`node_modules/`、`.venv/`、`toolchain/` 发行包、`dist/`；提交前逐项验证 `.gitignore` 生效。
- 未 push（无远端）；提交前门禁全绿：doctor 18 pass / pytest 149 passed / validate_spec 37-37 / sha256sum 144-144。

## Unreleased — 2026-09-18｜M2-01 契约对齐与六条种子 IMPLEMENTED

- **ADR-013 契约对齐**（SPEC-ALIGN）：保持 P0 四动作不变，CHALLENGE 语义落在 `PROBE + counterfactual` 并在 docs/04 §5 正式说明；Seed Schema 新增 `reference_points`/`red_flags`/`follow_up_strategy`/`review_levels` 四个**显式字段**并设为必填，不用既有字段冒充新语义。
- 结构性强制：技术参考要点缺 `reference_ids` 必被拒（模型知识不能充当技术结论）；`red_flag.requires_followup` 恒为 `true`（结构上禁止 red flag→扣分）；`approved` 必须两级审核 passed 且有 review_record_id；`technical_review` 必须 Level 1 passed；`max_followups ≤ 1`。
- 新增 `data/seeds/` 六条种子（RTOS Queue/周期任务/互斥量与信号量、UART+DMA 排障、SPI/I2C 选型、中断优先级），覆盖 6 个能力维度；全部 `technical_review`（Level 1 自检通过、Level 2 待负责人），不写 `approved`。
- 来源登记新增 S24（FreeRTOS 官方参考手册 V10.0.0）、S26（ST RM0433 Rev 8，第 15/19/47/48/50/56 章）等；来源均本机下载并核对章节号与正文，RM0433 的适用范围（仅 H7 系列）如实标注。
- 新增 `zhijue/application/seed_bank.py`：种子加载/校验/live 门槛/版本指纹；空目录、坏契约、无达标种子一律显式失败。
- 校验器 37/37（新增 5 条 Schema 负例 + 种子引用可追溯性检查，并做了负向自检证明其会失败）；全量 149 passed / 2 skipped；Ruff 全绿；无新依赖；LLM 调用 0 次。

## Unreleased — 2026-09-18｜M1-03 声明确认、快照与 Knowledge 激活 VERIFIED

- Claim 状态机（proposed/confirmed/disputed/retracted + supersedes 链）与引文子串校验；更正是新 user_input 块 + 新 Claim，不篡改原 PDF 来源。
- ProfileService：`/facts` 语义的乐观 revision 校验、校验先于写入（50 条/2,000 字/30,000 字）；`/confirm` 裁决后产生**不可变** ProfileSnapshot（仓储无 UPDATE 方法）。
- Knowledge 激活链：真实 openJiuwen `SimpleKnowledgeBase` + Milvus Lite，写完**回查回执校验**，`index_status` indexing→ready，异常必落 failed；检索按当前快照 allowlist 过滤，旧代来源不漏出。
- Knowledge 构造收敛为唯一权威 `zhijue/adapters/knowledge.py`，`smoke/knowledge.py` 复用同一实现（探针与应用不再各一份构造）。
- 首个 HTTP 服务（FastAPI，`src/zhijue/api/`）：统一成功/错误包封、契约错误码映射、乐观 revision 409、幂等重放返回原操作、202 受理 + operation 后台执行（`operation.started` / `operation.completed` / `operation.failed` 持久化事件）、SSE 事件流（重放 + 心跳 + 终态收敛）、`/health/live|ready`（live 缺配置 not_ready，不回退 fixture）、multipart 上传与 `/documents/{id}`、`/blocks`、`GET /operations/{id}`；导出 `contracts/openapi.json`。
- 最小确认界面（`apps/web/`）：真实浏览器跑通 新建档案→手填事实→确认→激活，显示"材料中声明/已由你确认"区别与索引状态；前端类型为网络边界的 snake_case，无第二套字段名。
- 修复真实缺陷：① operation 终态事件必须在状态转终态前写入（原顺序触发"events closed"）；② 后台任务异常不得逃逸到已发出的响应（改为 runner 边界落 failed）；③ 运行目录不存在时启动即崩（改为启动前自建）；④ `sniff_kind` 文本类型未做 UTF-8 校验（已补）。
- 全量 141 passed / 2 skipped；Ruff 全绿；live HTTP 闭环与私有 Demo Resume v1 上传均按本地接收登记核验通过；embedding 调用 6 次逻辑，token/cost null。无新依赖；LLM 调用 0 次。下一任务 M2-01（Seed 契约对齐 + 六条审核 Seed）。

## Unreleased — 2026-09-18｜M1-02 PDF/文本导入与 SourceBlock VERIFIED

- 新增 DocumentService + pypdf 适配 + Document/SourceBlock 仓储：按页提取（page 从 1、text_hash、origin=text_layer）、魔数判型不信任文件名、Document+块单事务、SourceBlock 不可变、base64 游标分页。
- 受控失败闭合 T02/T04：全空文字层→`requires_text`+粘贴提示（不输出"解析成功零项"假成功）；混合页→parsed+缺页警告（T03）；加密→`DOCUMENT_ENCRYPTED` 且拒收不索取口令；超限/损坏/类型不符各有 code；校验先于任何持久化，失败零半行。
- 私有登记的 Demo Resume v1（0600 原件）经新链本地导入并与 ignored 接收登记一致；任何原件、正文、文件名和指纹均不进入 Git 或公开日志。合成 PDF fixture 手工构造（ToUnicode CMap 中文实测还原），红测抓住并修复空 user 口令仍可解密读取的 fixture 缺陷。
- 全量 107 passed / 1 skipped；Ruff 全绿；`api.md`、contracts、迁移无变化；无新依赖；模型调用 0 次。下一任务 M1-03（确认/快照/Knowledge 激活）。

## Unreleased — 2026-09-18｜M1-01 业务持久层 VERIFIED

- 新建 `services/api/src/zhijue/` 分层：domain 纯函数（不透明 ID、Operation 状态机、规范化输入哈希）+ adapters/db（engine PRAGMA、14 表 SQLAlchemy 模型、Operation/事件仓储）。alembic 初版迁移 upgrade/downgrade 可逆，`compare_metadata` 零漂移。
- 幂等与事件规则落地：`(scope,idempotency_key)` 唯一 + 同输入重放返回原操作 + 不同输入 409 语义异常；事件 seq 单事务原子推进且 payload 按 `contracts/operation-event.schema.json` 校验；终态关闭事件；retry 新建子操作并继承 attempts 预算。
- 并发红线测试抓住真实缺陷：输家 IntegrityError 曾抛给调用方，修为撞唯一键后重查返回赢家行；10 连跑稳定。全量回归 93 passed / 1 skipped。修复 `migrations/env.py` 曾无条件覆盖调用方 URL、会把测试打向真实库的问题。
- API/HTTP/SSE/前端无变化；无新依赖。模型调用 0 次；token/cost null。

## Unreleased — 2026-09-18｜M0-04 版本锁、doctor、干净重装、前端锁与 CI 骨架

- 新增 `config/versions.lock.json` 实测版本锁（Python 3.11.16 / openjiuwen 0.1.18 兼容 commit `72c49851` / pymilvus 2.6.7 / milvus-lite 3.2.1 / uv 0.12.10 / Node 24.21.0 / pnpm 10.34.5）与 `scripts/doctor.py` 只读就绪检查；12 项守卫测试锁定"不回显密钥、来源漂移必 FAIL、缺失私密配置只 WARN 不 FAIL"。
- 干净环境重装通过：临时 venv `uv sync --frozen` 184 包、导入与 `SimpleKnowledgeBase` 构造成功、direct_url commit 一致；失败尝试（`--active` 被 uv 忽略）保留。`apps/web` 仅建 Vite+React+TS 工具链骨架，生成真实 `pnpm-lock.yaml` 并验证 frozen install + tsc + build 全 exit 0，不是业务 UI。
- 新增 CI 骨架 `.github/workflows/ci.yml`（backend + frontend 双 job，零模型费用，integration_live 私密 env 门控）；仓库未推送远端，工作流本身 NOT_RUN。
- 模型网关核验：`deepseek-flash` 无通道（503）；`deepseek-v4-flash` 探活 200 且支持 JSON mode 与 usage 返回。属网关探针而非业务链路；单价仍缺，cost 保持 null。全量回归 62 passed / 1 skipped；API/业务 Schema/迁移无变化。

## Unreleased — 2026-09-19｜M0-03-DEL Knowledge 删除兼容 VERIFIED

- 复现正式 openJiuwen 0.1.18 的 Milvus Lite list 删除缺陷；同一回归修复前 1 failed/1 passed，应用官方 PR #1344 精确补丁后 2 passed，上游目标测试文件 21 passed。
- 基于官方 v0.1.18 建立公开兼容 commit `72c4985111b835530ec616f70dd67117eb2e015c`；相对 tag 仅 2 个文件、31 行新增。项目 pyproject/uv.lock 固定该 commit，不修改 site-packages、不 monkeypatch、不替换 Knowledge。
- 两次真实四进程 live（补丁 worktree、项目锁定安装且无 PYTHONPATH）均完成 parse/add/retrieve/provenance/restart/delete/post-delete-restart，两个 synthetic KB 删除后均 0 命中。
- 在上游现有 PR #1344 提交真实 Milvus Lite 生命周期验证，不创建重复 PR；正式 0.1.18 wheel 仍明确记录为未含修复。
- 新增依赖来源/commit 与 list 返回形态守卫；全量 pytest 50 passed/1 skipped，Ruff 与锁来源检查通过。无新增第三方包；首次安装临时来源增加 Git/网络要求。
- 同步入口 README、Demo 登记、runbook、config、架构、Knowledge、测试、风险、来源、ADR、服务说明、process 与交接；API/DTO/SSE/业务数据库/前端无变化。兼容阶段 18 次成功逻辑 embedding 调用，usage/token/cost 为 null，DeepSeek LLM NOT_RUN。

## Unreleased — 2026-09-19｜M0-03 Knowledge live 部分验证

- 新增真实 openJiuwen Knowledge 多进程 smoke：SDK 自带 Parser/Chunker/SimpleKnowledgeBase/Milvus Store+Indexer/OpenAIEmbedding；没有本地同名 Knowledge 或主链 mock。
- 使用两个 synthetic profile 实测 BGE-M3 1024 维、解析、入库、provenance 检索、KB 隔离及进程重启可用；Demo Resume 未外发。
- `delete_documents` 因 openJiuwen 0.1.18 无法处理 pymilvus primary-key list 返回而失败；底层 profile A 已删但框架返回 false，post-delete restart NOT_RUN，M0-03 标记 BLOCKED。官方 PR #1344 与根因一致，但尚未当作发布版能力。
- 将旧本地 BGE-small/torch 计划替换为负责人指定的远程 BGE-M3 配置；新增规范环境变量和私密文件权限/去敏守卫，没有新增第三方依赖。
- 同步 ADR-012、架构、Knowledge、测试、风险、来源、Demo 登记、服务说明、process 与交接。API/DTO/SSE/业务数据库/前端无变化；DeepSeek LLM NOT_RUN，usage/token/cost 为 null。

## Unreleased — 2026-09-18｜M0-BASE 续核

- 核对官方 WorkflowAgent 源码/API/通用示例及公开仓库目录；7 个被审计的本地 SDK 文件与既有锁指定 wheel 完全一致，记录官方仓库与发布版的 2 个文件差异。
- 复跑原 34 项测试与真实 smoke 通过；旧 notebook 导入按预期失败，未执行模型/外部天气服务。
- 官方答疑查询 HTTP 418，M0-BASE 仍 BLOCKED；没有把未检索到当作没有指定 starter，也没有进入 Knowledge/M1。
- 本轮仅文档与本地证据，无业务/API/Schema/依赖变化，无 commit/push。

## Unreleased — 2026-09-18｜M0 局部施工与强制约束补充

- 将负责人追加的 20 条约束写入 AGENTS.md；登记 CHALLENGE/Seed 契约冲突，不静默修改接口。
- 新增真实 Workflow/WorkflowAgent 无模型 smoke、SDK 来源与继承链证据、34 项回归；修复探针 session 漏传及超时后台节点清理问题。
- 增补官方 u-j8 解读核验；答疑正文未取得，M0-BASE 保留 BLOCKED。Knowledge/模型 NOT_RUN；未完成 M0 或业务闭环。
- 同步架构、测试、来源、风险、process 与交接；ADR-011 保留 PROPOSED，不自行 ACCEPTED。
- API/Schema/数据库/依赖无变化；未 commit/push。详细命令与失败记录见本轮交接。

## 1.0.0 — 2026-09-18

新增 Demo 规划、需求、架构、数据模型、HTTP/SSE 契约、AI 工作规范、文档同步、测试与验收、运行手册、任务板、合成契约示例和交接模板。

相对前期讨论收紧：采用新轻量前端与单 Python 后端；种子规模调整为 6 起步/24 发布目标；OCR 和跨场记忆降为 P1；废除未经校准的能力概率；恢复、幂等、来源校验纳入 P0；新增国产 OS 适配和规则确认门槛。

本版本是**工程规范发布**，不是应用版本发布。未安装/运行业务服务，未调用付费模型，未修改或推送用户仓库。兼容性和业务性能均待施工验证。

## 2026-09-18 — DEMO-INPUT-01（本地输入登记）

- 实际读取 Demo Resume v1，私有原件、身份信息、解析指纹和逐页内容只存 ignored runtime；公开记录仅确认文字层非空，不冒充 Evidence Extraction。
- 保存负责人冻结的 Demo JD v1 与输入规范；后续来源审查确认没有可核验企业原公告，已从 `REAL_JD_DERIVED` 纠正为 `SYNTHETIC_DEMO_JD`，不再把聊天标签当作来源认证。
- 补测试说明、process 与交接；本轮10项接收检查通过，现有35项 pytest通过。API/业务模型/前端无变化，无新依赖。
