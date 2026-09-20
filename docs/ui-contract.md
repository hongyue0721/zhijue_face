# UI Contract｜P0 三页面试陪练

更新时间：2026-09-19。适用实现：`apps/web`。本文件只登记当前 FastAPI/OpenAPI 已实现能力，不把规划字段当成页面数据。

## 1. 路由与业务门槛

| 路由 | 页面职责 | 进入下一步的服务端门槛 |
|---|---|---|
| `/start?profile={profile_id}` | 创建 Profile、上传 PDF、查看文档状态、补充/确认事实 | `ProfileView.latest_snapshot_id != null` |
| `/profiles/{profile_id}/prepare?interview={interview_id}` | 输入用户 JD 或明确选择演示 JD、展示 Coverage Map 与五题 Plan、开始面试 | `InterviewView.status == ready` 后调用 start；start operation 成功后进入面试页 |
| `/interviews/{interview_id}` | 展示当前题、提交回答、监控分析、呈现追问决策、失败重试 | 所有题面与状态均取自 `GET /interviews/{id}` |

查询参数只保存不含正文的资源标识。简历文本、JD 正文、回答正文不得进入 URL。

## 2. 动态元素与 API 真值

| 页面元素 | 唯一数据来源 | 使用字段 | 禁止的客户端推断 |
|---|---|---|---|
| 服务可用状态 | `GET /api/v1/health/ready` | `status`、`run_mode` | 不展示模型名、密钥、token；503 不自动切换 fixture |
| Profile | `POST /api/v1/profiles`、`GET /api/v1/profiles/{id}` | `id`、`revision`、`documents`、claims、`latest_snapshot_id` | 不从本地文件名生成候选事实 |
| PDF 上传 | `POST /api/v1/profiles/{id}/documents` | multipart `file`、`kind=resume`、`expected_revision`；`Idempotency-Key` | 浏览器不得手工设置 multipart `Content-Type` boundary |
| 文档处理状态 | `GET /api/v1/operations/{id}` + `GET /api/v1/documents/{id}` | Operation `status/error/result`；Document `extract_status/index_status/warnings/page_count` | SSE 关闭不等于成功；`pending` 不显示成完成 |
| 解析文本抽屉 | `GET /api/v1/documents/{id}/blocks` | `items[].page_number/block_index/text` | 不从浏览器重新解析 PDF |
| 候选事实 | `ProfileView.proposed_claims` | `text/source_quotes/status` | 解析为空时不生成示例事实 |
| 手工事实 | `POST /api/v1/profiles/{id}/facts` | `expected_revision`、`items[].section/text` | 提交后仍保持 proposed，等待用户确认 |
| 事实确认 | `POST /api/v1/profiles/{id}/confirm` | `decisions[].claim_id/action`、operation | 只有 operation succeeded 后重新读取 Profile；不本地伪造 Snapshot |
| 资料就绪 | `ProfileView.latest_snapshot_id` | 非空 ID | `Document.index_status` 不能替代 Profile Snapshot 门槛 |
| 用户 JD | `POST /api/v1/interviews` | `jd_text` 最多 8,000 字符、`jd_source_name` 1—200 字符 | 客户端不传 `source_type`；不把用户 JD 标成演示数据；不得截断超限正文后静默提交 |
| 演示 JD | `POST /api/v1/interviews` | 省略 `jd_text`、`jd_source_name` | 来源必须由响应 `jd_source.source_type=synthetic_demo_jd` 证明 |
| JD 来源 | `InterviewView.jd_source` | 只按 `source_type` 映射：`synthetic_demo_jd`→演示岗位配置、`user_provided`→用户提供岗位描述、`official_posting`→官方公开岗位、`real_jd_derived`→公开岗位衍生材料 | 不用按钮文案或 `source_name` 推断、升级来源可信度 |
| 岗位要求 | `InterviewView.jd_requirements` | `tier/statement/source_span`；主摘要只按 `tier` 派生四类数量，完整 N 条默认折叠并可展开 | 不改写 requirement；主界面不显示内部 ID；聚合数量不构成新业务事实 |
| Coverage Map | `InterviewView.coverage_map` | `status/relation/requirement_ids/evidence_ids` | `unknown` 必须解释为“材料未体现 ≠ 不会” |
| 五题计划 | `InterviewView.root_plan.slots` | 五个真实 slot；主界面展示关联 requirement 文本与验证状态 | 不提前生成或展示具体题目；不按 `competency_id` 猜展示名称 |
| 技术明细 | `InterviewView.root_plan`、`limitations` | `competency/priority/reason_code/seed_id/version` | 默认折叠；不得与主流程视觉竞争 |
| 开始面试 | `POST /api/v1/interviews/{id}/start` | `expected_revision`、operation；成功时按冻结的五个 Slot 实例化本场根问题 | 只有 start operation succeeded 后进入面试页；不把后续 Policy 动态决策描述成主问题即时生成 |
| 当前题 | `InterviewView.current_question` | `wording/kind/order_index/basis/accepted_answer` | 不缓存或自造题面替代 GET 快照 |
| 主问题进度 | `root_plan.slots.length` + `current_question.order_index` | 当前主问题位置 | probe/clarification 不增加主问题总数 |
| 作答提交 | `POST /api/v1/interviews/{id}/answers` | `expected_revision/question_id/client_turn_id/answer_text`、`Idempotency-Key` | 一次点击创建一组标识；同一次网络重试复用原值 |
| 已保存回答 | `current_question.accepted_answer` | `raw_text/evaluation_status` | 202 只表示接收；处理结果仍以 Operation + GET Interview 为准 |
| 追问/澄清 | `current_question.kind`、`root_results` | `probe` 显示“为什么继续追问 / 追问方向”，`clarification` 显示“为什么需要澄清 / 澄清方向”；内容只读取 `action/reason_summary/target.followup_intent`；`counterfactual`→条件变化下的调整、`pushback`→回应反例或限制条件、`reflection`→复盘与经验总结 | `pushback` 不等于 `counterfactual`；未知 intent 使用用户可读 fallback，不暴露内部枚举或模型私有推理 |
| 分析重试 | `POST /api/v1/operations/{operation_id}/retry` | 失败 operation ID、最新 `expected_revision` | 不重新 POST answer，不新建 Answer |
| 面试完成 | `InterviewView.status/current_question` | finishing/completed 且无 current question | 当前无 report GET，禁止展示评分、雷达图、报告或反馈结论 |

Prepare ready 的冻结展示顺序为：岗位摘要 → Coverage Map / 五题 Plan → 开始面试动作 → 默认折叠的技术详情。该顺序只调整叙事层级；Coverage、Plan、Requirement 均保持服务端数组顺序，不按 `competency_id` 生成名称、重排 priority 或补造计划。

## 3. Operation、SSE 与刷新恢复

1. 每个 202 响应的 `operation_id` 写入当前标签页 `sessionStorage`；正文不写入 storage。
2. 浏览器同时连接 `GET /operations/{id}/events` 并轮询 `GET /operations/{id}`。SSE 只用于促使立即刷新，Operation snapshot 才是终态真值。
3. 页面切换或资源 ID 变化时关闭旧 EventSource、取消旧 fetch、停止旧轮询，避免迟到响应覆盖新资源。
4. `queued/running` 禁止重复提交；`succeeded` 后重新读取对应 Profile/Interview；`failed/interrupted/canceled` 显示真实错误。
5. 回答 202 后，`accepted_answer.raw_text` 来自服务端快照，因此刷新页面不要求重新填写。
6. 后端失败释放后，`InterviewView.active_operation_id` 为空，`accepted_answer` 也没有 operation ID。当前实现通过同标签页 `sessionStorage` 恢复 retry ID；跨标签页打开失败状态时只能展示“原回答已保存”，不能调用 retry。这是现有响应契约限制，不以猜测补齐。

## 4. 错误状态

- `SERVICE_NOT_READY`：停用写操作，明确说明未自动切换到预录成功结果。
- `CAPACITY_LIMITED`（HTTP 429，`retryable=true`）：提示队列已满；保留同一业务请求供用户稍后重试，不归类成未知服务错误，也不伪装成功。
- `REVISION_CONFLICT`：重新 GET 最新 Profile/Interview；不使用过期 revision 自动重放命令。
- `PROFILE_UNCONFIRMED`：返回资料确认步骤；不绕过 Snapshot 门槛。
- PDF `requires_text`：显示真实文档警告并开放手工事实输入；不伪装 OCR 已完成。
- 网络响应不明确：回答文本保持在当前表单中，同一次显式重试复用原 `client_turn_id` 与 `Idempotency-Key`。

## 5. 当前明确不实现

当前 OpenAPI 没有以下读取/控制能力，因此页面不得出现对应假按钮或假结果：运行时模型信息页、岗位搜索、简历优化、报告读取、评分雷达图、面试历史列表、Profile/Interview 列表、暂停/停止控制、视频/语音、社交登录、支付。`run_mode=fixture/replay` 必须在全局提示中明示，不能冒充 live 模型效果。
