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

1. 每个 202 响应的 `operation_id` 写入当前标签页 `sessionStorage`；正文不写入 storage。
2. 浏览器同时连接 `GET /operations/{id}/events` 并轮询 `GET /operations/{id}`。SSE 只用于促使立即刷新，Operation snapshot 才是终态真值。
3. 页面切换或资源 ID 变化时关闭旧 EventSource、取消旧 fetch、停止旧轮询。首次观察到 `succeeded/failed/interrupted/canceled` 后立即停止三类 transport；迟到的 `queued/running` 不得覆盖该终态快照。
4. `queued/running` 禁止重复提交，但本地选择、取消和“取消全部选择”继续可用；资料确认栏只在请求发送、原 Operation retry 发送或真实 `profile.confirm` queued/running 时显示处理反馈。succeeded 显示短暂完成反馈并重新读取 Profile；failed/interrupted/canceled 立即停止动画并保留真实错误。仅 `retryable=true` 提供原 Operation 重试；不可重试表示确认裁决已保存、但本代资料激活无法继续 retry，应保留错误并刷新资料状态，不得引导重发 `POST /confirm`。不得用定时假百分比。
5. 回答 202 后，`accepted_answer.raw_text` 来自服务端快照，因此刷新页面不要求重新填写。
6. 失败恢复键以服务端视图为权威：回答使用 `accepted_answer.retry_operation_id`，Report/ResumeDraft 使用 failed 状态下保留的 `active_operation_id`；`sessionStorage` 只作同标签页加速。重试必须指向失败链尾 Operation，不能重发原回答或新建第二份内容任务。
7. Report 改善稿、创建 ResumeDraft 及两页 operation retry 在发送前把不含正文的请求体标识与 `Idempotency-Key` 写入对应 sessionStorage scope。网络未取得明确响应时保留；用户显式重试必须逐字段复用原 body/key，不能生成新业务命令。观察到 202 或确定的不可重试 HTTP 错误后清理。
8. Report 与 Resume 使用各自的 sessionStorage scope 恢复 operation ID；正文仍不进入 storage。generation failed 只能 retry 原 operation，不能以新 POST 绕过累计尝试预算。
9. ResumeDraft 的 resource ID 在 202 响应中已固定；页面可先导航并显示 generating 状态，Operation succeeded 后重新读取同一 Draft，不创建第二份草稿。
10. 资料页从 Profile.active_operation_id 与 snapshot_activation 恢复激活；retry 不重复裁决。document.import 未保存上传字节，确知失败/中断须重新选择文件，未知响应在当前内存保留 File/body/key。
11. 独立简历、start、control/control-retry 安全命令使用各自 scope 跨刷新恢复；上传、更正、JD 和回答正文不写 storage。控制回调不能释放回答请求锁，反之亦然。
12. 业务资源快照优先于 `sessionStorage`；快照没有对应操作时清陈旧键。Operation GET 明确 404 `RESOURCE_NOT_FOUND` 时立即停止 fetch/interval/EventSource、清引用并解除假 busy；临时网络错误仍保留明确刷新。
13. Profile 删除与 Interview control 的 failed/interrupted 操作按 `error.retryable` 分流：可重试只续原链，不可重试解除前端永久锁并根据最新资源快照提供可行动出口。应用 readiness 失败后必须允许用户显式重新检查，不能要求整页刷新或自动切运行模式。

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

负责人明确要求移除模式徽章、fixture 提示条和文件要求说明，作为本轮界面规则覆盖旧版全局明示要求。后端 run_mode/data_mode/readiness 不变，不自动切模式；服务不可用仍显示真实错误。验收环境模式由测试记录说明，不将 fixture 结果当生产模型结果。
