# UI Contract｜P0 面试陪练、报告与简历草稿

更新时间：2026-09-19。适用实现：`apps/web`。本文登记五页首屏收口后的实际 HTTP 消费、展示语义、恢复规则与只读交互边界。

## 1. 路由与业务门槛

| 路由 | 页面职责 | 进入下一步的服务端门槛 |
|---|---|---|
| `/start?profile={profile_id}` | 创建 Profile、上传 PDF、查看文档状态、补充/确认事实 | `ProfileView.latest_snapshot_id != null` |
| `/profiles/{profile_id}/prepare?interview={interview_id}` | 输入用户 JD 或明确选择演示 JD、展示 Coverage Map 与五题 Plan、开始面试 | `InterviewView.status == ready` 后调用 start；start operation 成功后进入面试页 |
| `/interviews/{interview_id}` | 展示当前题、提交回答、监控分析、呈现追问决策、失败重试 | 所有题面与状态均取自 `GET /interviews/{id}` |
| `/interviews/{interview_id}/report` | 读取持久化评分、显式生成/重试回答优化、进入简历草稿 | Interview 必须 completed 且存在唯一 Report；页面不在浏览器重算评分 |
| `/resume-drafts/{draft_id}` | 展示 Claim 绑定正文/差异/缺失项、显式确认、确认后打印 | Draft 生成成功后可读；只有 `status=accepted` 才显示打印动作 |

查询参数只保存不含正文的资源标识。简历文本、JD 正文、回答正文不得进入 URL。

## 2. 动态元素与 API 真值

| 页面元素 | 唯一数据来源 | 使用字段 | 禁止的客户端推断 |
|---|---|---|---|
| 服务可用状态 | `GET /api/v1/health/ready` | `status`、`run_mode` | 不展示模型名、密钥、token；503 不自动切换 fixture |
| Profile | `POST /api/v1/profiles`、`GET /api/v1/profiles/{id}` | `id`、`revision`、`documents`、claims、`latest_snapshot_id` | 不从本地文件名生成候选事实 |
| PDF 上传 | `POST /api/v1/profiles/{id}/documents` | multipart `file`、`kind=resume`、`expected_revision`；`Idempotency-Key`；成功 Operation result 含 `resource_revision/proposed_claim_count/extraction_metadata` | 浏览器不得手工设置 multipart `Content-Type` boundary；202 不冒充候选事实已生成 |
| 文档处理状态 | `GET /api/v1/operations/{id}` + `GET /api/v1/documents/{id}` + `GET /api/v1/profiles/{id}` | Operation `status/error/result`；Document `extract_status/index_status/warnings/page_count`；Profile `proposed_claims` | SSE 关闭不等于成功；只有 operation succeeded 后重读 Document/Profile；`pending` 不显示成完成 |
| 解析文本抽屉 | `GET /api/v1/documents/{id}/blocks` | `items[].page_number/block_index/text` | 不从浏览器重新解析 PDF |
| 候选事实 | `ProfileView.proposed_claims` | `text/source_quotes/status`；上传候选 text 必须等于 SourceBlock 的 exact_quote；保持服务端顺序，每页 5 条在浏览器只读分页 | 解析为空时不生成示例事实；翻页不得发起写请求；未确认不得进入快照 |
| 手工事实 | `POST /api/v1/profiles/{id}/facts` | `expected_revision`、`items[].section/text` | 提交后仍保持 proposed，等待用户确认 |
| 事实确认 | `POST /api/v1/profiles/{id}/confirm` | `decisions[].claim_id/action`、operation | 只有 operation succeeded 后重新读取 Profile；不本地伪造 Snapshot |
| 资料就绪 | `ProfileView.latest_snapshot_id` | 非空 ID | `Document.index_status` 不能替代 Profile Snapshot 门槛 |
| 用户 JD | `POST /api/v1/interviews` | `jd_text` 最多 8,000 字符、`jd_source_name` 1—200 字符 | 客户端不传 `source_type`；不把用户 JD 标成演示数据；不得截断超限正文后静默提交 |
| 演示 JD | `POST /api/v1/interviews` | 省略 `jd_text`、`jd_source_name` | 来源必须由响应 `jd_source.source_type=synthetic_demo_jd` 证明 |
| JD 来源 | `InterviewView.jd_source` | 只按 `source_type` 映射：`synthetic_demo_jd`→演示岗位配置、`user_provided`→用户提供岗位描述、`official_posting`→官方公开岗位、`real_jd_derived`→公开岗位衍生材料 | 不用按钮文案或 `source_name` 推断、升级来源可信度 |
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
| 分析重试 | `POST /api/v1/operations/{operation_id}/retry` | 失败 operation ID、最新 `expected_revision` | 不重新 POST answer，不新建 Answer |
| 面试完成 | `InterviewView.status/current_question/profile_id` | completed 且无 current question时进入 `/interviews/{id}/report`；Profile 关系取服务端 `profile_id` | 不从 URL 或 storage 猜 Profile；不自行计算评分 |
| 面试控制 | `POST /api/v1/interviews/{id}/control` | `action=skip/end`、`expected_revision`、`Idempotency-Key` | 当前 Interview 页面未新增 skip/end 按钮；控制结果以 Operation 和新快照为准 |
| 评分报告 | `GET /api/v1/interviews/{id}/report` | 持久化 Assessment、nullable score、coverage、completion、limitations、improvements_status；逐题只按 `root_question_id` 关联 | null 显示“未形成总分/未评”，不显示 0；浏览器不重算服务端分数；问题切换不写 API |
| 回答优化 | `POST /api/v1/interviews/{id}/report/improvements` | Report revision、Operation、`improved_answers[].root_question_id/original_answers/rewritten_answer/missing_facts/cautions` | 只有整场显式点击才生成；页签/问题切换只读；不把改写答案回写成面试证据或改变分数 |
| 简历草稿 | `POST /api/v1/profiles/{id}/resume-drafts`、`GET /resume-drafts/{id}` | 当前 snapshot、可选 interview 目标、sections/changes/source_claims/missing_facts/cautions；正文与差异只按 `item_id`，来源只按 `claim_id` 显式关联 | JD/报告只影响目标表达；正文事实只来自当前快照 Claim；正文选择不写 API；主界面不展示裸 Claim ID |
| 草稿确认与打印 | `POST /api/v1/resume-drafts/{id}/accept` | expected_revision；accepted 后开放打印 | 确认不改 Claim/评分；未确认正文不得进入打印区域；打印解除屏幕高度/overflow 限制 |


## 3. 首屏信息架构与只读交互

- 顶部进度固定为“资料 / 准备 / 面试 / 复盘”。Report 为第 4 步 active；Resume 表示四步均完成，不再把“面试”保持 active。
- Start 有 Profile 后采用“材料摘要 / 待确认事实”双栏；快照门槛和“进入面试准备”在顶部。候选事实分页、展开原文和手工补充开关均为浏览器本地交互。
- Prepare ready 采用“岗位要求与资料覆盖 / 五题验证计划”双栏；完整 Requirement/Coverage 与技术明细默认折叠，开始动作在顶部且仍受 `status=ready` 门槛约束。
- Interview 采用当前题与回答约 65% / 右侧依据约 35% 双栏；回答框随可用视口收缩并在输入框内滚动，题面不裁剪，右栏独立滚动。
- Report 采用左侧五题导航、右侧“评分依据 / 回答优化”页签。首屏只渲染当前根题；criterion 的用户标题按 kind 映射，不显示 `criterion_id` 或裸状态值。
- Resume 采用左侧正文预览、右侧当前条目来源审计。选择关系只按 `item_id`，来源只按 `claim_id` 映射到 `source_claims[].text`；待补与注意数量在确认前可见。
- 上述分页、选择和页签切换均不得产生 POST；只改变浏览器展示状态。

Prepare ready 的当前展示层只调整叙事和空间：顶部真实摘要与开始动作，主体为要求/覆盖与五题计划双栏，完整 Requirement/Coverage/技术信息默认折叠。Coverage、Plan、Requirement 保持服务端数组顺序，不重排 priority 或补造计划；`competency` 只通过受控词典显示已登记中文名。

## 4. Operation、SSE 与刷新恢复

1. 每个 202 响应的 `operation_id` 写入当前标签页 `sessionStorage`；正文不写入 storage。
2. 浏览器同时连接 `GET /operations/{id}/events` 并轮询 `GET /operations/{id}`。SSE 只用于促使立即刷新，Operation snapshot 才是终态真值。
3. 页面切换或资源 ID 变化时关闭旧 EventSource、取消旧 fetch、停止旧轮询。首次观察到 `succeeded/failed/interrupted/canceled` 后立即停止三类 transport；迟到的 `queued/running` 不得覆盖该终态快照。
4. `queued/running` 禁止重复提交；`succeeded` 后重新读取对应 Profile/Interview/Report/ResumeDraft；失败终态保持可见。
5. 回答 202 后，`accepted_answer.raw_text` 来自服务端快照，因此刷新页面不要求重新填写。
6. 后端失败释放后，`InterviewView.active_operation_id` 为空，`accepted_answer` 也没有 operation ID。当前实现通过同标签页 `sessionStorage` 恢复 retry ID；跨标签页打开失败状态时只能展示“原回答已保存”，不能调用 retry。这是现有响应契约限制，不以猜测补齐。
7. Report 改善稿、创建 ResumeDraft 及两页 operation retry 在发送前把不含正文的请求体标识与 `Idempotency-Key` 写入对应 sessionStorage scope。网络未取得明确响应时保留；用户显式重试必须逐字段复用原 body/key，不能生成新业务命令。观察到 202 或确定的不可重试 HTTP 错误后清理。
8. Report 与 Resume 使用各自的 sessionStorage scope 恢复 operation ID；正文仍不进入 storage。generation failed 只能 retry 原 operation，不能以新 POST 绕过累计尝试预算。
9. ResumeDraft 的 resource ID 在 202 响应中已固定；页面可先导航并显示 generating 状态，Operation succeeded 后重新读取同一 Draft，不创建第二份草稿。

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

五页 Product Polish 已完成，但没有新增岗位搜索、历史列表、完整简历编辑器、运行时模型信息页、视频/语音、社交登录或支付入口。`run_mode=fixture/replay` 继续在全局提示中明示，不能冒充 live 模型效果。HTTP API、OpenAPI、数据库和迁移未因本轮展示收口改变。
