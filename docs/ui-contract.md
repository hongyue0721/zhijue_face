# UI Contract｜P0 面试陪练、报告与简历草稿

更新时间：2026-09-22。适用实现：`apps/web`。本文登记当前五页闭环的实际 HTTP 消费、展示语义与恢复边界；本轮迁移额外验证资料页在 1366×768、1440×900、低高度及 200% 缩放等效视口的行为。

## 1. 路由与业务门槛

| 路由 | 页面职责 | 进入下一步的服务端门槛 |
|---|---|---|
| `/start?profile={profile_id}` | 上传或无简历填写、批量核对/更正、独立通用简历 | 面试要求非空确认快照且该代 activation.ready；简历要求非空确认快照 |
| `/profiles/{profile_id}/prepare?interview={interview_id}` | 核对/修改冻结 JD、展示覆盖与五题计划、开始面试 | 绑定快照 ready；修改产生新 interview，旧会话不修改 |
| `/interviews/{interview_id}` | 展示当前题、提交回答、监控分析、呈现追问决策、失败重试 | 所有题面与状态均取自 `GET /interviews/{id}` |
| `/interviews/{interview_id}/report` | 读取持久化评分、显式生成/重试回答优化、进入简历草稿 | Interview 必须 completed 且存在唯一 Report；页面不在浏览器重算评分 |
| `/resume-drafts/{draft_id}` | 展示 Claim 绑定正文/差异/缺失项、显式确认、确认后打印 | Draft 生成成功后可读；只有 `status=accepted` 才显示打印动作 |

查询参数只保存不含正文的资源标识。简历文本、JD 正文、回答正文不得进入 URL。

## 2. 动态元素与 API 真值

| 页面元素 | 唯一数据来源 | 使用字段 | 禁止的客户端推断 |
|---|---|---|---|
| 服务可用状态 | `GET /api/v1/health/ready` | `status`、`run_mode` | 不展示模型名、密钥、token；503 不自动切换 fixture |
| Profile | `POST /api/v1/profiles`、`GET /api/v1/profiles/{id}` | `id/revision/documents/claims/latest_snapshot_id/active_operation_id/snapshot_activation` | 不从文件名生成事实，不凭快照存在推断索引成功 |
| PDF 上传 | `POST /api/v1/profiles/{id}/documents` | multipart `file`、`kind=resume`、`expected_revision`；`Idempotency-Key`；成功 Operation result 含 `resource_revision/proposed_claim_count/extraction_metadata` | 上传使用独立原生 modal，不在入口卡内展开处理详情；浏览器不得手工设置 multipart `Content-Type` boundary；202 不冒充候选事实已生成 |
| 文档处理状态 | `GET /api/v1/operations/{id}` + `GET /api/v1/documents/{id}` + `GET /api/v1/profiles/{id}` | Operation `status/error/result`；Document `extract_status/index_status/warnings/page_count`；Profile `proposed_claims` | SSE 关闭不等于成功；只有 operation succeeded 后重读 Document/Profile；`pending` 不显示成完成 |
| 解析文本抽屉 | `GET /api/v1/documents/{id}/blocks` | `items[].page_number/block_index/text`、`next_cursor` 全量遍历 | 不从浏览器重新解析 PDF；游标重复时报错停止，不静默截断；modal 有可访问名称、真实首焦点、Tab 圈闭、ESC 关闭与触发焦点归还 |
| 候选/已确认事实 | `ProfileView.proposed_claims/confirmed_claims` | `text/source_quotes/status/supersedes_id`；服务端顺序，单列表滚动 | 待确认采用“不采用 / 待定 / 采用”三态分段控件，待定对应未选择；仅当前档位进入 Tab 序列，方向键同步档位与焦点；切换、选择、更正编辑与取消零写入；不默认采用，不再分页 |
| 手工事实 | `POST /api/v1/profiles/{id}/facts` | `expected_revision`、`items[].section/text` | 无简历也可创建 Profile；有 Profile 时通过“+ 补充经历事实”打开收纳盒式弹卡；提交后仍 proposed，保持服务端返回顺序 |
| 事实确认/更正 | `POST /api/v1/profiles/{id}/confirm` | `decisions[].claim_id/action/corrected_text`、Operation；每批最多 50 | `correct` 是独立动作，不自动改为 accept；暂存更正后隐藏冲突的三态控件；第 51 条选择/更正保持界面并提示上限；弹卡焦点圈闭在 dialog 内，ESC/遮罩/取消关闭后焦点归还触发按钮 |
| 资料激活 | `ProfileView.snapshot_activation`、`POST /profiles/{id}/activate`、Operation retry | `snapshot_id/status/operation_id` | pending 显式激活，failed 重试原操作；只接受该代 ready，不用 Document 全局状态 |
| 用户 JD | `POST /api/v1/interviews` | `jd_text` 最多 8,000 字符、`jd_source_name` 1—200 字符 | 客户端不传 `source_type`；不把用户 JD 标成演示数据；不得截断超限正文后静默提交 |
| 受控演示 JD（API/fixture） | `POST /api/v1/interviews` | 省略 `jd_text`、`jd_source_name`；正式准备页不提供此入口 | 来源必须由响应 `jd_source.source_type=synthetic_demo_jd` 证明；不得把受控 fixture 能力包装成正式页面默认值 |
| JD 来源 | `InterviewView.jd_source` | 只按 `source_type` 映射：`synthetic_demo_jd`→演示岗位配置、`user_provided`→用户提供岗位描述、`official_posting`→官方公开岗位、`real_jd_derived`→公开岗位衍生材料 | 不用按钮文案或 `source_name` 推断、升级来源可信度 |
| 冻结 JD 原文 | `InterviewView.jd_text` | string；历史确未保存才 null | 刷新/修改回填来自服务端，不从要求列表拼造，不持久化到浏览器 storage |
| 岗位要求 | `InterviewView.jd_requirements` | `tier/statement/source_span`；主摘要只按 `tier` 派生四类数量，完整 N 条默认折叠并可展开 | 不改写 requirement；主界面不显示内部 ID；聚合数量不构成新业务事实 |
| Coverage Map | `InterviewView.coverage_map` | `status/relation/requirement_ids/evidence_ids` | `unknown` 必须解释为“材料未体现 ≠ 不会” |
| 五题计划 | `InterviewView.root_plan.slots` | 五个真实 slot；保持服务端顺序；`competency` 只查受控中文词典，未知值显示“验证方向 N” | 不提前生成或展示具体题目；不直接展示内部 `competency`；未知值不按字符串猜含义 |
| 技术明细 | `InterviewView.root_plan`、`limitations` | `competency/priority/reason_code/seed_id/version` | 默认折叠；不得与主流程视觉竞争 |
| 开始面试 | `POST /api/v1/interviews/{id}/start` | `expected_revision`、operation；成功时按冻结的五个 Slot 实例化本场根问题 | 只有 start operation succeeded 后进入面试页；不把后续 Policy 动态决策描述成主问题即时生成 |
| 当前题 | `InterviewView.current_question` | `wording/kind/order_index/basis/accepted_answer` | 不缓存或自造题面替代 GET 快照 |
| 主问题进度 | `root_plan.slots.length` + `current_question.order_index` | 当前主问题位置 | probe/clarification 不增加主问题总数 |
| 作答提交 | `POST /api/v1/interviews/{id}/answers` | `expected_revision/question_id/client_turn_id/answer_text`、`Idempotency-Key` | 一次点击创建一组标识；同一次网络重试复用原值 |
| 已保存回答 | `current_question.accepted_answer` | `raw_text/evaluation_status` | 202 只表示接收；处理结果仍以 Operation + GET Interview 为准 |
| 追问/澄清 | `current_question.kind`、`root_results` | `probe` 显示“为什么继续追问 / 追问方向”，`clarification` 显示“为什么需要澄清 / 澄清方向”；内容只读取 `action/reason_summary/target.followup_intent`；`counterfactual`→条件变化下的调整、`pushback`→回应反例或限制条件、`reflection`→复盘与经验总结 | `pushback` 不等于 `counterfactual`；未知 intent 使用用户可读 fallback，不暴露内部枚举或模型私有推理 |
| 分析重试 | `GET /api/v1/operations/{operation_id}`、`POST /api/v1/operations/{operation_id}/retry` | 失败 operation ID、当前 `error.retryable`、最新 `expected_revision` | `error.retryable` 是当前策略下的可执行事实；明确提高受限预算后，既有回答的 `UPSTREAM_FAILED / UPSTREAM_TIMEOUT` 可重新开放。按钮只在 true 时出现；不重新 POST answer，不新建 Answer；回答卡已展示失败时不重复渲染通用 Operation 失败卡 |
| 面试完成 | `InterviewView.status/current_question/profile_id` | completed 且无 current question时进入 `/interviews/{id}/report`；Profile 关系取服务端 `profile_id` | 不从 URL 或 storage 猜 Profile；不自行计算评分 |
| 面试控制 | `POST /api/v1/interviews/{id}/control` | `action=skip/end`、`expected_revision`、原 key | 二次确认；取消零写入；end 可在已受理分析中提交；与回答独立恢复 |
| 评分报告 | `GET /api/v1/interviews/{id}/report` | `root_assessments[].question_text/answers[]`、score、coverage、completion、limitations | 原题/主答/追问来自持久化数据，不等优化生成；null 不显示 0，浏览器不算分 |
| 回答优化 | `POST /api/v1/interviews/{id}/report/improvements` | Report revision、Operation、`improved_answers[].root_question_id/original_answers/rewritten_answer/missing_facts/cautions` | 只有整场显式点击才生成；页签/问题切换只读；不把改写答案回写成面试证据或改变分数 |
| 简历草稿 | `POST /api/v1/profiles/{id}/resume-drafts`、`GET /resume-drafts/{id}` | 当前 snapshot、可选 interview 目标、sections/changes/source_claims/missing_facts/cautions；正文与差异只按 `item_id`，来源只按 `claim_id` 显式关联 | JD/报告只影响目标表达；正文事实只来自当前快照 Claim；正文选择不写 API；主界面不展示裸 Claim ID |
| 草稿确认与打印 | `POST /api/v1/resume-drafts/{id}/accept` | expected_revision；accepted 后开放打印 | 确认不改 Claim/评分；未确认正文不得进入打印区域；打印解除屏幕高度/overflow 限制 |


## 3. 首屏信息架构与只读交互

- 顶部面试步骤固定四步；独立 Resume 显示“简历整理”，不暗示已完成面试。
- Start 提供上传 PDF 与直接填写经历两个入口；上传、重传和丢失响应恢复统一进入独立 modal，有 Profile 后材料摘要紧凑，事实列表单一滚动与批量提交栏分离。待确认/已确认切换均只读。
- Prepare 左侧以冻结 JD 为主、覆盖摘要为辅，右侧五题计划；返回与修改入口明确，修改生成新 interview。
- Interview 保留完整题面、回答输入、独立依据栏及显式 skip/end；工作区使用实际剩余视口。
- Report 左侧题号/题面摘要，右侧原题与原回答、评分/优化页签；解释直接可见，技术引用折叠。
- Resume 采用左侧正文预览、右侧当前条目来源审计。选择关系只按 `item_id`，来源只按 `claim_id` 映射到 `source_claims[].text`；待补与注意数量在确认前可见。
- 上述选择、取消、页签与来源展开不产生 POST；通用简历可从资料页独立生成，不传 interview_id。

应用固定浅色中性令牌，不随系统 dark 变成浅字白底。本轮资料页实际验证 1366×768、1440×900、1366×600 及 1366×768 在 200% 缩放下的 683×384 等效 CSS 视口，均无横向溢出且关键动作可通过页面滚动到达；其余页面不把历史验收冒充本轮重跑结果。Coverage、Plan、Requirement 保持服务端顺序，不补造计划。

## 4. Operation、SSE 与刷新恢复

1. 每个 202 响应的 `operation_id` 写入当前标签页 `sessionStorage`；正文默认不写入 storage。用户明确勾选临时保存后，未提交 JD/回答及其未知响应的完整原命令可在本标签页恢复，详见下文。
2. 浏览器同时连接 `GET /operations/{id}/events` 并轮询 `GET /operations/{id}`。SSE 只用于促使立即刷新，Operation snapshot 才是终态真值。
3. 页面切换或资源 ID 变化时关闭旧 EventSource、取消旧 fetch、停止旧轮询。观察到 `succeeded/failed/interrupted/canceled` 且没有后继时停止三类 transport；若快照已有 `next_operation_id`，关闭父操作监听并只读跟随后继，不触发终态回调或重发原请求。迟到的父操作响应、旧资源 revision 不得覆盖当前后继或成功结果。
4. `queued/running` 禁止重复提交，但本地选择、取消和“取消全部选择”继续可用；资料确认栏只在请求发送、原 Operation retry 发送或真实 `profile.confirm` queued/running 时显示处理反馈。succeeded 显示短暂完成反馈并重新读取 Profile；没有后继的 failed/interrupted/canceled 停止动画并保留真实错误。仅 `retryable=true` 提供原 Operation 重试；不可重试的资料确认表示裁决已保存、但本代资料激活无法继续 retry，应保留错误并刷新资料状态，不得引导重发 `POST /confirm`。不得用定时假百分比。
5. 回答 202 后，`accepted_answer.raw_text` 来自服务端快照，因此刷新页面不要求重新填写。
6. 失败恢复键以服务端视图为权威：回答使用 `accepted_answer.retry_operation_id`，Report/ResumeDraft 使用 failed 状态下保留的 `active_operation_id`；`sessionStorage` 只作同标签页加速。重试必须指向失败链尾 Operation，不能重发原回答或新建第二份内容任务。
7. Report 改善稿、创建 ResumeDraft 及两页 operation retry 在发送前把不含正文的请求体标识与 `Idempotency-Key` 写入对应 sessionStorage scope。网络未取得明确响应时保留；用户显式重试必须逐字段复用原 body/key，不能生成新业务命令。观察到 202 或确定的不可重试 HTTP 错误后清理。
8. Report 与 Resume 使用各自的 sessionStorage scope 恢复 operation ID；正文仍不进入 storage。generation failed 只能 retry 原 operation，不能以新 POST 绕过累计尝试预算。
9. ResumeDraft 的 resource ID 在 202 响应中已固定；页面可先导航并显示 generating 状态，Operation succeeded 后重新读取同一 Draft，不创建第二份草稿。
10. 资料页从 Profile.active_operation_id 与 snapshot_activation 恢复激活；retry 不重复裁决。document.import 未保存上传字节，确知失败/中断须重新选择文件，未知响应在当前内存保留 File/body/key。
11. 独立简历、start、control/control-retry 安全命令使用各自 scope 跨刷新恢复；上传字节、更正正文不写 storage。JD/回答仅在用户勾选临时保存后将正文与原请求标识一起暂存，禁止只恢复幂等键却换用新正文。控制回调不能释放回答请求锁，反之亦然。
12. 业务资源快照优先于 `sessionStorage`；快照没有对应操作时清陈旧键。Operation GET 明确 404 `RESOURCE_NOT_FOUND` 时立即停止 fetch/interval/EventSource、清引用并解除假 busy；临时网络错误仍保留明确刷新。
13. Profile 删除与 Interview control 的 failed/interrupted 操作按 `error.retryable` 分流：可重试只续原链，不可重试解除前端永久锁并根据最新资源快照提供可行动出口。应用 readiness 失败后必须允许用户显式重新检查，不能要求整页刷新或自动切运行模式。
14. 回答优化与简历生成最多一次服务端自动重试/修正，自动和手动共享原链预算。`retry_trigger=automatic` 且后继仍 queued/running 时显示自动处理与真实累计尝试数；queued 尚未开始不虚增已调用次数。刷新以业务资源 active_operation_id 和 Operation 的 next_operation_id 恢复，前端定时器只读，不调用 retry。自动后继仍失败时才按链尾 error.retryable 开放手动重试；认证、缺失来源和预算耗尽不伪装成可重试。
15. 自动后继的 retry_reason 分别显示“正在自动重试网络请求”或“正在自动修正输出”；累计模型尝试与 attempt_limit 配对，等待从 chain_started_at 起计，不能在每个后继重新归零。暂时读取失败不宣称后台已停止。
16. 成功终态先完成业务快照读取，再释放当前监听引用；监听切换/离页取消信号仍阻止旧回调写回，不能让自己清理操作 ID 取消新题目读取。

## 5. 错误状态

- `SERVICE_NOT_READY`：停用写操作，明确说明未自动切换到预录成功结果。
- `CAPACITY_LIMITED`（HTTP 429，`retryable=true`）：提示队列已满；保留同一业务请求供用户稍后重试，不归类成未知服务错误，也不伪装成功。
- `REVISION_CONFLICT`：重新 GET 最新 Profile/Interview；不使用过期 revision 自动重放命令。
- `PROFILE_UNCONFIRMED`：返回资料确认步骤；不绕过 Snapshot 门槛。
- PDF `requires_text`：显示真实文档警告并开放手工事实输入；不伪装 OCR 已完成。
- 网络响应不明确：回答文本保持在当前表单中，同一次显式重试复用原 `client_turn_id` 与 `Idempotency-Key`。
- `REPORT_NOT_READY`：不显示空报告或假分数，返回面试完成链检查。
- 内容生成失败：继续展示原评分、原回答或空草稿；只在原 operation 明确 retryable 时开放重试，不自动切 fixture/replay。

## 6. 当前页面明确不实现

本轮不增加岗位搜索、历史列表、完整简历编辑器、运行时模型信息页、视频/语音、社交登录或支付。fixture/replay 全局明示。桌面整改新增 activation API、Profile 激活视图、冻结 JD 原文、报告原题/原答及激活表迁移；详见 api.md 与 process.md §43。

## 2026-09-22 UI-59 更新（优先于上文旧布局描述）

按负责人审图和页面批注，初始上传改为居中的单张卡片；识别中用真实请求状态驱动扫描动画，减少动态效果时静止。事实列表仅展示采用/不采用二选滑块，初始无选择，不自动采用；更正独立弹窗。选择后才出现提交栏，操作成功后收起状态；部分事实已确认仍可继续准备，空资料和失败资料仍可管理/删除。

岗位为连续表单，可选分区折叠；面试突出当前问题与回答，次要控制折叠；复盘为题目导航与正文；简历为纸面与来源栏。减少重复卡片、装饰性小字和常驻动作，保留真实失败、来源、确认和重试门禁。上传卡片允许轻阴影与 16px 圆角。

可由正文和主动作直接推导的就绪、等待、草稿标签不得重复常驻；题型由进度区单点表达。Planner/Seed 等实现明细不得进入用户主流程。字符计数在达到字段上限 80% 后才出现；报告限制默认折叠，总分不使用独立卡片容器。

模式徽章和 fixture 提示条仍不显示；2026-10-04 Web 体验优化恢复上传格式/限制与核对步骤说明。后端 run_mode/data_mode/readiness 不变，不自动切模式；验收记录必须说明 fixture 与真实模型结果的区别。

## 2026-09-25 岗位知识页（KnowledgePacksPage）与集成

| 路由/元素 | 唯一数据来源 | 行为与禁用条件 | 禁止的客户端推断 |
|---|---|---|---|
| `/knowledge-packs` 列表 | `GET /api/v1/knowledge-packs` | 真实 items；请求中显示文本加载态，不显示“0 条” | 不补假卡片；API 不可达显示“无法连接服务+重试连接”，不伪装空列表 |
| 包详情 | `GET /api/v1/knowledge-packs/{release_id}` | 与列表 ID 同源；快速切换用序号守卫丢弃旧响应 | 不从“当前默认项”倒推详情 |
| 三状态标签 | item `validation_status / review_status / selectable+blocked_reasons` | 格式通过、负责人审核、可用于新面试分开显示 | 不得由格式通过推导审核或可用 |
| 导入按钮 | `POST /api/v1/knowledge-packs/import`（multipart+Idempotency-Key） | 防双击；202 后先受理再观察 Operation | 202 不显示“导入完成”；只有 succeeded result 才展示完成 |
| 导入进度 | 复用 `useOperationMonitor`（SSE+polling） | 关闭对话框后台继续；刷新用 sessionStorage operation id 恢复；404 清键 | 不造第二套轮询；无精确进度不模拟百分比 |
| 失败恢复 | Operation `error.retryable` | retryable=true 提供“重试导入”（parent 链）；格式/安全/版本类错误只引导换修正后的文件 | 不可重试错误不放“重试”按钮 |
| 用于新面试 | 前端下一次创建意图（sessionStorage 只存 release id） | 仅 `selectable=true` 可点；无全局激活写接口 | 不影响任何已创建面试；提交时服务器再确认可用性 |
| 来源外链 | detail `sources[].url` | 仅 http(s) 渲染链接、用户主动点击、`rel=noopener noreferrer` | 不自动抓取、不渲染不安全协议 |
| 复制标识 | 当前已取得的 DTO | 本地 clipboard 动作，失败给友好提示 | 不为此新增后端接口 |
| 准备页选择器 | `GET /api/v1/knowledge-packs`（selectable 项） | 默认“服务端默认”；选择经 `pack_release_id` 随创建提交；包被删/失选自动回落默认 | 列表读取失败只警告，仍可用默认包生成（服务器受理时校验）；不禁用其它入口 |
| 本场包摘要 | `InterviewView.knowledge_pack`（冻结字段） | 准备/面试/报告三页显示 frozen / frozen_unavailable / legacy_unresolved 三种真实状态 | 绝不从当前列表默认项倒推历史绑定 |

能力就绪分离：岗位包列表/详情/导入不依赖模型或候选人 embedding；`serviceReady=false` 只锁模型相关流程（生成计划、开始面试、回答分析），知识页不因它整体禁用。候选人接口面（列表/详情/面试视图）不返回参考答案、rubric 明细或评分细则。

## 2026-10-03 恢复、上下文与能力门禁

- 资料页首次创建直接采用 POST Profile 快照，URL 补入 profile ID 不触发竞争性的 bootstrap GET；快照仅接受当前档案且 revision 不倒退。切换档案后，旧 GET/POST 不得覆盖页面或抢回路由。
- 知识页 `returnTo` 只携带经校验的本地页面路径及资源标识，不包含正文。顶部与准备页入口、详情切换、返回均保留原 profile/interview 上下文。
- 未提交岗位按 profile/interview、回答按 interview/question 隔离。默认只在 JS 内存保留；用户主动勾选后使用本标签页 sessionStorage，不使用 localStorage。正文与未知响应原命令一起恢复；服务端已受理文本优先，受理后清理对应草稿，换题/跳过/结束按服务端最新状态清理旧题。提供清除草稿与撤回暂存授权；删除档案成功后清理本标签页该档案草稿，清理失败明确提示。浏览器恢复标签页可能同时恢复存储，不承诺关闭即安全擦除。
- 迟到回答请求仅在完整原命令（题目、revision、turn ID、幂等键、正文）仍拥有对应 pending 草稿时才能写回或清理。编辑、重置、换题、服务端已受理或旧会话卸载后，不得抢回后来编辑的正文；仍拥有的未知响应保留原 body/key。
- 准备页正常 plan/start POST 期间只显示“正在提交”；只有不在发送中且上次响应未知时才显示原请求恢复提示，不能把普通提交渲染成网络异常。
- 导入失败保留 Operation ID、错误与服务端 retryable 判定，关闭窗口或刷新不能抹掉失败。成功或实际选择替换文件后才清理旧终态。上传请求未受理时禁止关闭；202 已受理后允许关闭窗口，继续监控后台，禁止重复提交或换文件。
- 仅在 succeeded 且结果包含有效 release 时展示完成。不可重试失败要求修正后换文件；可重试失败继续原 parent-linked 操作链，不重发旧文件创建新链。
- 回答优化、简历生成及生成重试读取 `/health/ready.content_generation`；`absent` 明确禁用并说明依赖未配置。fixture 也可能配置生成器，live 也可能缺失，不能按模式猜。已有报告与已生成草稿的确认仍可用。
- 本轮新增 DOM 交互回归，真实 AnyUI 浏览器验收和模型结果另记在 process.md；不把组件测试当作视觉或真实模型证明。
- 默认标记来自服务端启动时固定的内置 release；导入更新版本不能改默认标记或无显式选择的新计划。列表和详情必须同时反映实际完整性错误，禁止“可用卡片、提交才失败”的不一致。
- 820px 以下报告采用原生五题选择器，并将“下一步”概览默认收起；保留完整题干、原回答、所有页签和概览操作，不把第 3–5 题藏在横向滑轨或长题目列表后。桌面题目侧栏与概览保持展开。

## 2026-10-04 桌面 Web 体验优化

- 等待状态使用真实 Operation 状态与 `chain_started_at` 计算整条逻辑链已等待时间；不显示虚假百分比，不新增重试。计时文本不逐秒打断辅助技术播报。
- 准备页先填写岗位，再展开岗位包设置；冻结版本摘要保持可查。宽屏面试题目与输入并排，窄屏仍按顺序显示完整题干。
- 报告摘要只引用已有评分、未评分状态及生成结果中的待补事实。相同分数、单题评分、全未评分不推断相对强弱；入口定位原题和对应页签，不排序改写原记录或计算新评分。
- 复制仅复制当前真实优化正文；剪贴板不可用或拒绝时提示手动复制，不伪报成功。
- 上传提示实际 PDF 限制与提取—核对—提交步骤；事实选择显示尚未提交，服务端确认仍是唯一事实裁决。
- 实际模型等待补充：文件发送阶段不承诺可刷新恢复；收到 document.import Operation 后，扫描动画下展示真实状态与耗时。模型识别失败给出重新上传/手填入口说明，原始错误仍可展开核对，不把服务失败归因于用户资料。
- 回答优化页签内就地展示生成进度；切回评分页签仍可查看任务状态，同一时刻不重复渲染两份进度。
- 简历 generation_failed 与 generating 分开：终态不再写“生成完成后”或无条件要求重试；无正文时不显示误导的“0 项来源”。原错误、预算和返回资料/报告入口保留，重试仍完全受服务端门禁控制。

