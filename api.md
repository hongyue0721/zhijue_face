# api.md｜HTTP 与事件契约

**契约版本 1.0.0。** 根目录此文件为人类可读接口语义真源。后端由 FastAPI 导出 OpenAPI 快照到 `contracts/openapi.json`；请求 DTO 由 Pydantic 建模。当前部分资源响应仍由服务层字典视图返回，`apps/web/src/api.ts` 的网络边界类型也仍为手工维护，尚不能宣称“前端类型由 OpenAPI 自动生成”；两端必须在同一变更中更新，并由精确响应契约测试、TypeScript 编译和 OpenAPI 快照检查防漂移。不得另外手写一份与本文件含义冲突的 OpenAPI。

**实现状态（2026-09-20）**：M4-01 评分/报告后端已实现并测试；M4-02 回答优化、简历草稿与对应页面已实现。已实现资料链 `POST /profiles`、`GET /profiles/{id}`、`POST /profiles/{id}/facts`、`POST /profiles/{id}/confirm`、`POST /profiles/{id}/documents`、`GET /documents/{id}`、`GET /documents/{id}/blocks`、`POST /profiles/{id}/activate`、`DELETE /profiles/{id}`，规划、面试与报告链 `POST /interviews`、`GET /interviews/{id}`、`POST /interviews/{id}/start`、`POST /interviews/{id}/answers`、`POST /interviews/{id}/control`、`GET /interviews/{id}/report`、`POST /interviews/{id}/report/improvements`，简历链 `POST /profiles/{id}/resume-drafts`、`GET /resume-drafts/{id}`、`POST /resume-drafts/{id}/accept`，以及 Operation/SSE/retry/health 与 `GET /runtime/info`。开始/回答链真实经过 openJiuwen Workflow；程序从已校验 Observation 和冻结 Rubric 生成 Assessment/Report。`DELETE /profiles/{id}` 先 tombstone（status=deleting，拒绝其余写入）再由 `profile.delete` Operation 后台清理：先删 Knowledge 索引（SDK delete_documents），再单事务级联删除档案/材料/事实/快照/会话/草稿与关联 Operation 与事件，只保留删除回执；索引删除失败时数据库不动，档案保持 deleting，可从 ProfileView 的 active_operation_id 恢复显式重试。

**前端迁移状态（2026-09-22）**：正式准备页只提交用户明确填写的岗位名称与必要项/加分项/岗位职责，不再提供“使用演示岗位配置”入口。`POST /interviews` 省略 `jd_text/jd_source_name` 时使用 `SYNTHETIC_DEMO_JD` 的 HTTP 契约仍保留给显式 fixture、受控测试或直接 API 客户端；这不是正式页面的默认值。本轮没有修改 HTTP 路径、字段、错误码、SSE、数据库 Schema、迁移或 OpenAPI。

**岗位知识包轮次（2026-09-25）**：新增 §9 `GET /knowledge-packs`、`GET /knowledge-packs/{release_id}`、`POST /knowledge-packs/import`（multipart + Idempotency-Key，202 异步）与 `knowledge_pack.import` Operation kind；`POST /interviews` 增加可选 `pack_release_id`，`InterviewView` 增加冻结摘要 `knowledge_pack`，`/runtime/info` 增加 `knowledge_packs` 增量。迁移 `a7c4e1f29b58` 建 `knowledge_pack_release/review/import` 三表并为 `interview` 增加三个可空绑定列；旧行保持 null（`legacy_unresolved`），不回填捏造。HTTP 面无“全局激活”写接口。

**恢复与冻结修复（2026-10-03）**：Profile 组合视图以同一数据库读取快照返回 revision、事实及资料；新迁移 `c91f8b34d602` 保存面试受理时的审核身份与批准 Seed 范围。重试按持久化逻辑操作根串行受理，拒绝旧题回退和兄弟分叉；内容生成重启恢复同时检查业务资源与 Operation。健康接口增加 `content_generation` 能力事实。

## 1. 全局约定

Base path：`/api/v1`。成功 JSON：`{"data": ..., "meta":{"request_id":"req_..."}}`。Content-Type 为 `application/json; charset=utf-8`，上传除外。所有网络 DTO 字段为 snake_case；时间 RFC3339 UTC；ID 为不透明字符串。

更新请求 MUST 携带 `expected_revision`，与服务端不一致返回 409 `REVISION_CONFLICT`，响应附当前 revision，不附私人原文。前端重新 GET 并明确合并，不自动覆盖。

创建异步操作的 POST 和 DELETE MUST 带 `Idempotency-Key`，长度 8—128；按 workspace+method+path+key 唯一。相同 key 和相同规范化业务输入返回原操作；相同 key 不同输入返回 409 `IDEMPOTENCY_CONFLICT`。上传 hash 使用文件 bytes hash、profile_id、expected_revision，不使用 multipart boundary。

服务端先检索同 key/同 client_turn_id 的既有结果，再校验新命令的 revision 和状态；否则成功请求的网络重试会被错误当成过期 revision。对于不同输入仍返回幂等冲突，不绕过授权。

对业务表的幂等记录保留至 workspace 删除，Demo 不做定时自动过期。重复命令即使晚于模型完成，也不应再次调用上游。

所有业务接口按服务端 workspace 隔离。P0 仅本机单用户，不是多租户 SaaS；公网前必须加真实认证和逐资源所有权校验。浏览器提供 profile_id 不能替代权限。

## 2. 错误格式

```json
{
  "error": {
    "code": "REVISION_CONFLICT",
    "message": "资料已更新，请重新加载后重试。",
    "retryable": false,
    "details": {"current_revision": 4}
  },
  "meta": {"request_id": "req_example"}
}
```

| HTTP | code | 用途 |
|---:|---|---|
| 400 | INVALID_REQUEST / INVALID_EVENT_CURSOR | 格式、游标语义无效 |
| 401/403 | UNAUTHENTICATED / FORBIDDEN | 非本地部署的认证/权限错误 |
| 404 | RESOURCE_NOT_FOUND | 不存在或不可见；不泄漏其他 workspace 资源 |
| 409 | REVISION_CONFLICT / IDEMPOTENCY_CONFLICT / OPERATION_IN_PROGRESS / INVALID_STATE / REPORT_NOT_READY / PROFILE_UNCONFIRMED / PACK_REVIEW_PENDING / PACK_REVIEW_REJECTED / PACK_VERSION_CONFLICT / RETRY_NOT_ALLOWED | 业务状态冲突 |
| 410 | EVENT_HISTORY_GONE | 游标早于保留事件；客户端获取快照 |
| 413 | FILE_TOO_LARGE / TEXT_TOO_LARGE / PACK_UPLOAD_TOO_LARGE | 超过业务资源上限 |
| 415 | UNSUPPORTED_FILE_TYPE | 格式不支持或魔数不匹配 |
| 422 | SCHEMA_VALIDATION_FAILED | 合法 JSON 但字段/枚举不符合契约 |
| 429 | CAPACITY_LIMITED | 队列或预算限制；可给 Retry-After |
| 502/503/504 | UPSTREAM_FAILED / SERVICE_NOT_READY / UPSTREAM_TIMEOUT / PACK_CONTENT_MISSING / PACK_CONTENT_CORRUPTED / PACK_UPLOAD_INPUT_LOST | 在异步受理前发现的依赖问题 |
| 500 | INTERNAL_ERROR | 未预料故障；前台不显示栈/密钥 |

异步操作受理后才失败：初始 HTTP 仍然是 202；失败记录在 Operation 和 `operation.failed` 事件。前端不得把任何 202 当作业务已成功。

## 3. 公共对象摘要

`ProfileView`：id、revision、display_name、synthetic、status、documents、proposed_claims、confirmed_claims、latest_snapshot_id、active_operation_id、snapshot_activation。`active_operation_id` 是当前资料写操作（上传/确认/激活）的恢复键，无操作时为 null。`snapshot_activation` 无快照时为 null；否则为 `{snapshot_id,status,operation_id}`，status 仅 `pending/indexing/ready/failed`，operation_id 为该代次最近激活操作（可为 null）。资料事实确认和 Knowledge 就绪是两个状态；不得从 Document 的全局 index_status 推断一个快照代次已经激活。

`DocumentView`：id、profile_id、kind、filename_display、sha256、page_count、extract_status、index_status、warnings；不含实际文件路径。

`InterviewView`：id、revision、status、run_mode、profile_id、profile_snapshot_id、jd_text、jd_requirements、jd_source、root_plan、coverage_map、current_question、root_results、active_operation_id、stop_requested、report_id、limitations、knowledge_pack。`profile_id` 只用于把报告明确关联回所属档案，不返回资料正文。`knowledge_pack` 是该场受理时冻结的摘要：`{binding:"frozen"|"frozen_unavailable"|"legacy_unresolved", pack_release_id, pack_id, name, version, content_digest, competency_profile_id}`；旧记录无可证实绑定时 binding=`legacy_unresolved` 并附说明 note，绝不从“当前默认包”倒推或捏造版本。`jd_text` 只读返回该会话冻结的岗位输入原文，供准备页刷新后核对与修改；仅历史记录确未保存原文时为 null，不从 requirements 拼造原文，不写浏览器持久存储。`jd_source` 至少包含 source_type、source_name、content_hash、imported_at、is_synthetic；`official_posting` 额外返回 source_url/retrieved_at，`real_jd_derived` 额外返回 upstream_source_name/upstream_url/upstream_retrieved_at/upstream_content_hash/derived_artifact_path/derived_content_hash/transformation_note。

`OperationView`：id、kind、status、resource_type、resource_id、parent_operation_id、retry_trigger、retry_reason、next_operation_id、attempts、attempt_limit、chain_started_at、result、error、last_event_seq、created_at、updated_at。`retry_trigger` 为 `automatic / manual / null`：自动来源以持久化 `operation.retry_scheduled` 为准，普通 parent-linked retry 为 manual，原操作为 null。`retry_reason` 为该自动事件记录的 `transient / correction / null`，不从错误文案猜测。`chain_started_at` 为逻辑原操作的 created_at；`attempt_limit` 为回答分析、回答优化和简历生成的当前实际模型总额度，其他操作为 null。`next_operation_id` 指向已受理的唯一直接后继，没有后继时为 null；它不修改原操作的失败状态。attempts 是累计已开始的尝试数，queued 后继尚未开始时继承父值。

`OperationAccepted`：operation_id、resource_type、resource_id、status=`queued` 或原操作真实状态、events_url。重放幂等请求时仍返回原操作状态；不得伪装为新 queued。

所有 question 的 rubric/reference_answer 在无提示面试模式下不返回给候选人视图。观察者接口需要显式 observer_mode；P0 可使用同一接口按服务端模式裁剪字段，不以隐藏 CSS 保护答案。

`QuestionView`：id、root_id、kind、seed_id（经历/证据回退题可为 null）、wording、basis、order_index、accepted_answer（可为 null；只含 id、client_turn_id、raw_text、evaluation_status、retry_operation_id）。`retry_operation_id` 仅当 `evaluation_status=failed` 时非 null，指向该回答失败链的链尾 operation（retry 经 parent 链关联，链尾 attempts 为累计预算真值），前端凭它跨刷新走 `/retry`；其他状态为 null，不得用链中其他节点重试以免分叉绕过预算。候选人视图不返回 `rubric_snapshot`、reference_points、red_flags 或参考答案；返回原回答仅用于本人刷新恢复，不能把分析失败伪装成未提交。

`root_results` 当前只返回可观察的程序 Decision 摘要：root_question_id、observation_id、action、reason_code、reason_summary、target；不返回模型原始输出或私有推理。

## 4. 资料 API

| 方法与路径 | 输入 | 成功 | 语义 |
|---|---|---|---|
| POST `/profiles` | display_name、synthetic | 201 ProfileView | 新档案 revision=0，synthetic 默认 true |
| GET `/profiles/{id}` | 无 | 200 ProfileView | 服务端完整快照；刷新恢复用 |
| POST `/profiles/{id}/facts` | expected_revision、items:[{section,text}] | 201 ProfileView | 手填事实形成 user_input SourceBlock 和 proposed Claim；不自动“真实认证” |
| POST `/profiles/{id}/documents` | multipart：file、kind、expected_revision | 202 OperationAccepted | kind=resume/project；校验并提取 SourceBlock 后，live 通过 P-EXTRACT Workflow 选择逐字候选事实，作为 proposed Claim 与 Document 原子提交；不自动确认 |
| GET `/documents/{id}` | 无 | 200 DocumentView | 查看提取/索引状态 |
| GET `/documents/{id}/blocks` | cursor?、limit 默认20最大100 | 200 {items,next_cursor} | 页块文本及位置，用于确认和引用回查 |
| POST `/profiles/{id}/confirm` | expected_revision、decisions:[{claim_id,action,corrected_text?}] | 202 OperationAccepted | action=accept/reject/correct；写确认快照并更新 Knowledge |
| POST `/profiles/{id}/activate` | expected_revision；header：Idempotency-Key | 202 OperationAccepted | 显式激活当前已确认快照；不新建事实/快照、不增加 Profile revision；已有该代次操作返回原操作，失败使用原 operation retry |
| DELETE `/profiles/{id}` | query：expected_revision；header：Idempotency-Key | 202 OperationAccepted | 先 tombstone，再清理档案及关联资料/索引/会话/记忆 |

手填 items 一次最多 50 条，section 为 basic/education/project/skill/award/other，text 长度 1—2,000。合计字符上限沿用配置。展示姓名/联系方式不会自动进入模型评价上下文。

上传最大 10 MiB、最多 5 页；新传入文件通过 `expected_revision` 乐观锁，Document、SourceBlock、逐字 proposed Claim 与 Profile revision 在一个事务提交。P-EXTRACT 只能从输入块选择 `exact_quote`，Claim 正文必须与该引文完全相同；未知 block、非逐字引文、联系方式、重复候选或超过 50 条全部拒绝，不落部分结果。长文档按源文字预算切成连续段、分多次真实 Workflow 调用抽取，切分无损（段可拼接还原），逐字来源不变量不因分块改变；50 条上限对合并结果生效，超出同样全部拒绝。`extraction_metadata` 增加 `model_calls`（本次导入的模型调用次数），`usage` 为各次调用聚合，任一调用缺该字段则保持 null，不填造 0。Operation result 返回 `resource_revision / document_id / extract_status / index_status / proposed_claim_count / extraction_metadata`；未确认的新内容不改变已经绑定旧快照的面试。加密 PDF 不要求用户上传密码，返回明确 warning 或失败；扫描文档在 P0 转 `requires_text`，不调用 P-EXTRACT，提示用 `/facts` 粘贴文本。chat/completions 请求默认使用 SSE 流式（`MODEL_STREAM=true`）：`MODEL_TIMEOUT` 是单请求总预算，`MODEL_STREAM_STALL_SECONDS` 是块间静默预算；实测部分兼容网关的 SSE 通道不落实 `response_format=json_object` 强制，此类网关显式 `MODEL_STREAM=false` 走单 JSON 体，两条路径的严格校验语义一致。`MODEL_STREAM_STALL_SECONDS` 是块间静默预算（生效取较小值），生成器元数据同时公开两者与 `reasoning_effort`。P-EXTRACT 的模型传输超时（含总预算与 stall）记录为 `UPSTREAM_TIMEOUT`，其他模型请求失败记录为 `UPSTREAM_FAILED`；模型已返回但 JSON/逐字来源校验失败仍为 `UPSTREAM_FAILED`，三类错误不得用同一“来源校验失败”文案混淆。

confirm 只能操作属于当前 Profile 且未被撤回的 Claim。correct 必须提供 corrected_text，创建新的 user_input 依据；用户不能把随意改写的内容继续绑定为原文 exact_quote。一个明确提交的批次原子写入裁决、确认快照、Profile revision 和确认 Operation，再异步激活该代次 Knowledge。单个批次最多 50 项；不替用户默认选中。Knowledge 失败保留确认事实与同一快照，snapshot_activation.status=failed；重试仅激活该快照，不再次应用 decisions、不再增加 revision。创建计划和开始面试均要求各自绑定的快照代次 ready，失败返回 409 INVALID_STATE。所有未完成/失败激活必须能从 ProfileView 恢复，不依赖单个标签页缓存。

旧快照只有可追溯的成功激活回执才可标 ready；没有凭证保持 pending，并由 `/activate` 明确激活。空的 confirmed_claim_ids 不可用于开始面试或生成简历，不能用“索引了空集合”冒充资料就绪。新事实修订不修改已绑定旧快照的面试。

## 5. 简历 API

| 方法与路径 | 输入 | 成功 | 语义 |
|---|---|---|---|
| POST `/profiles/{id}/resume-drafts` | expected_revision、profile_snapshot_id、interview_id?、jd_text? | 202 OperationAccepted | 从指定不可变快照生成一份草稿；interview_id 与 jd_text 最多一个，前者必须绑定同一快照 |
| GET `/resume-drafts/{id}` | 无 | 200 ResumeDraftView | 生成中、失败、待确认和已接受都返回持久化快照 |
| POST `/resume-drafts/{id}/accept` | expected_revision（草稿） | 200 ResumeDraftView | 只接受已经生成的草稿；增加 revision，不新增事实、不改变 ProfileSnapshot |

`ResumeDraftView` 精确字段：`id / revision / profile_id / profile_snapshot_id / interview_id / status / sections / source_claims / source_claim_ids / changes / missing_facts / cautions / target_context / active_operation_id / run_metadata`。status 只取 `generating / generation_failed / draft / accepted`；`generation_failed` 时 `active_operation_id` 保留失败链尾操作作为跨刷新恢复键（可 GET 并走 `/retry`），只有 succeeded 后清 null。`sections[]` 为 `{section_id,title,items:[{item_id,text,claim_ids}]}`；每个实质 item 至少绑定一个当前快照内 confirmed Claim。`source_claims[]` 只返回 `{id,text}`，用于人工 diff；`changes[]` 为 `{item_id,before,after,claim_ids,reason}`，before 由服务端按绑定 Claim 生成，不信任模型回填原文。

jd_text 最多 8,000 字符，只作为岗位上下文，不成为候选人事实。提供 interview_id 时使用该会话冻结的 JD，且该会话的 profile_snapshot_id 必须与请求一致；两者都不提供时生成通用单模板。首次生成失败满足下文自动恢复条件时，沿原链受理一次自动后继；没有可执行的自动后继时保留 draft 行与失败链尾，status=`generation_failed`，通过 `/operations/{id}/retry` 在剩余额度内恢复，不重新创建第二份草稿。

创建简历的同 scope、Idempotency-Key、规范化输入重放，始终返回原创建 OperationAccepted（包括原 events_url），不因自动/手动后继或草稿状态变化而换成链尾回执；恢复进度通过 next_operation_id 和资源快照读取。重放先于可变资源校验；同键不同输入仍返回 409 IDEMPOTENCY_CONFLICT。不同键的同目标去重不重置预算、不创建第二份草稿。

浏览器只允许对 `accepted` 草稿进入打印样式；打印内容必须可选中、长文本不截断，不输出 missing_facts、cautions 或未确认占位符。P0 没有服务端 PDF 字节导出接口。

## 6. 面试 API

| 方法与路径 | 输入 | 成功 | 语义 |
|---|---|---|---|
| POST `/interviews` | profile_id、profile_revision、jd_text?、jd_source_name?、role_preset、memory_enabled=false、observer_mode=false、pack_release_id? | 202 OperationAccepted | 检查确认/索引状态，固定快照、生成五题计划；受理时冻结岗位包 release+摘要；成功 ready |
| GET `/interviews/{id}` | 无 | 200 InterviewView | 当前问题与服务端状态；不靠聊天文本恢复 |
| POST `/interviews/{id}/start` | expected_revision | 202 OperationAccepted | ready→active，显示第一题；幂等 |
| POST `/interviews/{id}/answers` | expected_revision、question_id、client_turn_id、answer_text | 202 OperationAccepted | 接受原回答，分析、决策、生成下一题或结束 |
| POST `/interviews/{id}/control` | expected_revision、action | 202 OperationAccepted | action=skip/end；skip 仅当前题，end 请求停止提问并串行生成现有报告 |
| GET `/interviews/{id}/report` | 无 | 200 ReportView | 无结果时 409 REPORT_NOT_READY；只读持久化结果，不临时调用模型 |
| POST `/interviews/{id}/report/improvements` | expected_revision（Report） | 202 OperationAccepted | 一次批量生成已回答根题的受约束优化建议；数字评分不变 |

end 在回答操作进行中也可受理：服务端原子记录 `stop_requested=true` 和唯一结束 operation；不再接受新答案、不再向 InterviewView 暴露待答问题，结束 operation 在当前回答安全释放后串行汇总。结束不保证远端调用立即取消或退费。重复 end 返回同一 operation。skip 仅在没有 active operation 且仍有 current_question 时受理：跳过主问题会使该根题 `status=skipped`、`score=null`；跳过追问保留该根题已有 Observation，但整场 `completion=incomplete`。两种 control 都不调用模型。

已受理的 end 若排队等待期间由最后一题 skip/answer 完成同一报告，end 成功复用该已持久化 report_id，不产生矛盾的 INVALID_STATE、不再评分或创建报告。该收敛只作用于已受理操作；completed 会话的新结束命令仍拒绝，既有同键重放及同输入 end 去重保持原回执。

role_preset P0 只支持 `embedded_junior`。JD 不提供时使用显著标注的预置（`SYNTHETIC_DEMO_JD`）；不将其称为某企业真实招聘要求。JD 最多 8,000 字符。五主问题与追问上限由服务端配置，客户端不得无限增加。

`pack_release_id`（`kpr_` + 16 hex）为可选：省略 = 服务端在受理瞬间解析默认岗位包。无论显式或默认，release ID、内容摘要与能力配置 ID 都在受理时冻结进 Interview；后续默认变化、包被替换或损坏都不改变本场。未审核/被拒/损坏/能力配置未注册的包在受理前同步返回 409（`PACK_REVIEW_PENDING`/`PACK_REVIEW_REJECTED`/`PACK_CONTENT_*`/`COMPETENCY_PROFILE_UNSUPPORTED`），不进入后台。幂等重放按 §1 先找回原操作返回受理结果：客户端未显式给 `pack_release_id` 时，服务端解析出的默认值不参与输入 hash，避免“默认变化导致重放误报冲突”。

冻结绑定还包含受理时的审核记录、审核内容摘要和逐 Seed 批准范围（内部 `pack_review_snapshot`）。受理后的审核撤销或范围变更只影响新面试，不能重新解释旧场次的题库资格。旧行的审核快照保持 null，不用今天的审核倒填历史事实；缺少可证实审核绑定时不得启动或继续生成依赖该绑定的新题，已有报告仍可读取。相同幂等键必须比对规范化的显式输入：JD、revision、显式 release 或选项变化返回 `IDEMPOTENCY_CONFLICT`；合法重放不重新解析默认包。

开始面试（`POST /interviews/{id}/start`）只按本场冻结绑定解析岗位包：绑定 release 内容与登记摘要不符返回 409 并明确失败，绝不回落其他包顶替；`legacy_unresolved` 记录不允许再开始新回答流程，原报告仍可读。

开始面试时，服务端按五个冻结 slot 逐一实例化根问题：优先绑定同 competency 的 approved Seed；`embedded.rtos.fundamentals` 只允许映射到未重复使用的 approved `embedded.rtos.*` Seed。没有相符 Seed 时，退回经历/证据表达题并令 `seed_id=null`，其 Rubric 不评价无技术参考支持的技术正确性。不得为了凑五题绑定无关 Seed，也不得把回退题冒充经 Level 2 审核的技术题。

同场规划优先覆盖不同能力；能力不足五类时，仅以该能力的不同验证切面补足，不能循环复制同一道泛化题。回退题面保留注册能力的中文名称、真实岗位要求和验证切面；缺失技术参考不会被包装为已批准技术题。

来源类型由服务端根据可信输入路径决定，客户端不能仅凭枚举把 JD 升格为真实来源：

- 未提供 `jd_text`：加载 `data/jd/preset_embedded_junior.txt`，固定标记为 `synthetic_demo_jd`；
- 提供 `jd_text`：固定标记为 `user_provided`，`jd_source_name` 只作用户可见标签，不构成来源认证；
- `official_posting` 和 `real_jd_derived` 只能通过后续受信任导入路径创建。前者必须有可验证的 HTTP(S) source_url 与 retrieved_at；后者必须同时有上游名称、URL、抓取时间、上游内容 hash、本地派生工件 hash 和转换说明；
- 本地路径、保留示例域名和未经记录的 `confirmed_by` 不构成真实来源。缺少上游事实时必须保持 `synthetic_demo_jd` 或 `user_provided`，不得静默升级。

answer_text 为非空 1—6,000 字符；全空白拒绝。client_turn_id 是浏览器为一次点击生成并在重试复用的随机 ID，和 Idempotency-Key 共同防重复。只接受 current_question.id；不是当前题则 409。正在有 active_operation 时其他答题命令返回 409。

重复提交已接受的 client_turn_id 且内容相同返回原 operation，不再改 revision。相同 client_turn_id 内容变化返回冲突。原回答已落库而模型失败时，页面显示“回答已保存，分析失败”；使用 operation retry，不再 POST 一份新回答。

新答案受理与 Answer 原文、operation、`active_operation_id` 和 Interview revision 在同一事务提交；202 返回后即使分析失败，原回答也必须能由 Interview 快照恢复。后台成功后再以单事务提交 Observation、程序 Decision、下一题/结束状态并清除 `active_operation_id`。后台失败只把 Answer 标为 failed 并释放当前 operation，不把用户回答改成错误结论。

创建 operation 时校验逻辑预算；队列上限为 8，满时返回 429 CAPACITY_LIMITED，不接受后丢失任务。

`ReportView` 精确字段：

- `id / revision / interview_id / completion / overall_score / coverage / root_assessments / improvements_status / active_operation_id / improved_answers / limitations / run_metadata`；`completion` 只取 `complete / incomplete`，不包含 `hire/no_hire` 等招聘决定。
- `coverage` 为 `{planned_root_count, asked_root_count, answered_root_count, scored_root_count, insufficient_root_count, disputed_root_count, skipped_root_count, unmeasured_root_count, skipped_question_count, overall_eligible}`。这些是范围计数，不把未测根题换算成 0 分。
- 每个 `root_assessments[]` 为 `{id, root_question_id, question_text, answers, status, score, coverage, criterion_results, answer_ids}`；`question_text` 为持久化根问题全文；`answers[]` 按题目顺序保留 `{answer_id,question_id,question_kind,question_text,raw_text}`，包括主回答与追问/澄清回答。未回答的根题数组为空。原题和回答来自已有 Question/Answer，不依赖回答优化是否成功，不现场生成。`status` 只取 `scored / insufficient / disputed / skipped / unmeasured`；`score` 可为 null，coverage 是该根题可评分 criterion 权重占冻结总权重的比例。
- 每个 `criterion_results[]` 为 `{criterion_id, kind, weight, level, finding, answer_quotes, knowledge_refs, explanations}`。同一根题的主回答与追问按 criterion 合并，权重只计算一次；`supported` 与 `contradicted` 同时出现时保留 `finding=disputed` 且 `level=null`，不得自行挑一个版本。
- `improvements_status` 只取 `not_requested / generating / ready / failed`。生成中或失败时保留唯一 active/last operation；失败时 `active_operation_id` 即该失败操作（可重试恢复键，跨浏览器刷新后仍可 GET 该 Operation 并走 `/retry`），只有 succeeded 后清 null。同一 Report 已 ready 后，即使换 Idempotency-Key 也返回原成功 operation，不再次调用模型。
- 每个 `improved_answers[]` 为 `{root_question_id,original_answers,rewritten_answer,segments,used_claim_ids,changes,missing_facts,cautions}`。`original_answers[]` 保留 `{answer_id,question_id,question_kind,raw_text}`；`segments[]` 的每段必须绑定当前根题回答 exact_quote 或当前 ProfileSnapshot 的 confirmed claim_id，服务端校验 ID、精确引文、数值与责任边界后才提交。
- `run_metadata` 的评分部分只返回运行事实：`run_mode / seed_bank_version / rubric_version / prompt_versions / policy_version / model_fingerprint / sdk_version / scoring_version`。回答优化成功后追加 `content_generation={run_mode,workflow,workflow_version,prompt_version,generator,usage}`；未知模型、SDK 或 usage 字段为 null，不填造默认值。

回答优化的首次生成是显式异步操作，不与结束评分绑成一次隐式模型调用。它使用真实 openJiuwen `Start → Generator → SemanticValidation → End` Workflow；模型只生成候选文案，不能改 Assessment/score。首次可恢复失败允许一次自动后继；自动处理终止且仍失败时 Report 保留且 `improvements_status=failed`。自动与手动 retry 都复用同一 Report 与输入快照。缺失数字、职责或实验事实必须进入 missing_facts/cautions，不得进入 rewritten_answer。

根题计算严格采用冻结 Rubric：可评分项为 level 属于 0—3 且 finding 不为 `not_assessable/disputed` 的 criterion；`coverage=sum(可评分权重)/sum(冻结权重)`。可评分集合为空、coverage<0.60 或存在 disputed criterion 时根题 score=null。否则 `score=round_half_up(100 * sum(weight*level/3)/sum(可评分权重))`。至少三根题 `status=scored` 才提供 overall_score，按各根题等权算术平均并 `round_half_up`；JD priority 不进入分数。Report 与 Assessment 在同一事务落库，每场只允许一份；`report.ready` 与业务状态同事务追加。GET 无报告时返回 409 `REPORT_NOT_READY`，不得现场补算或重复调用模型。

## 7. 操作、事件与运行信息 API

| 方法与路径 | 输入 | 成功 |
|---|---|---|
| GET `/operations/{id}` | 无 | 200 OperationView |
| GET `/operations/{id}/events` | after? 或 Last-Event-ID | 200 text/event-stream |
| POST `/operations/{id}/retry` | expected_revision（目标业务资源） | 202 新 OperationAccepted |
| GET `/runtime/info` | 无 | 200 {run_mode,versions,feature_flags,health_summary,knowledge_packs} |
| GET `/health/live` | 无 | 200 {status:"ok"} |
| GET `/health/ready` | 无 | 200 ready 或 503 not_ready |

retry 仅 failed/interrupted 且当前允许恢复的操作可受理；输入、快照和题目不变。`knowledge_pack.import` 的 retry 复用同一上传回执（后台输入持久在受控 runtime 目录）与 parent 链累计预算（最多三次）；回执字节丢失返回 `PACK_UPLOAD_INPUT_LOST` 并要求重新上传同一文件（内容 digest 去重保证不会登记第二份）。interview 操作用 Interview revision，回答优化用 Report revision，简历生成用 ResumeDraft revision。目标被修改/删除、已由其他操作推进或草稿已经 accepted 时返回 409，不悄悄覆盖新状态。

`GET /operations/{id}` 的 `error.retryable` 表示当前可执行的恢复动作，不只是错误原因是否瞬时。回答优化/简历生成与 retry 受理共用链尾、整树实际尝试及排队预留、剩余预算、资源状态和归属判定；第三次执行被重启中断后不可出现可点击但必被拒绝的第四次重试。新的内容生成失败记录只保存原因本身的可恢复性，GET 按当前策略投影，不重写历史失败；历史已记为不可恢复且缺少独立证据的内容错误不猜成可恢复。负责人提高 `MODEL_MAX_RETRIES` 后，可恢复原因仍需满足其他条件及三次硬上限。

一次模型 Operation 只发一次 HTTP 请求；`MODEL_MAX_RETRIES` 表示同一 logical_operation 可额外创建的 parent-linked retry 数，父子所有 transport/Schema/语义失败合计最多 `MODEL_MAX_RETRIES + 1` 次且硬上限为三次，不能以隐藏 transport retry 或换 Idempotency-Key 绕过额度。

同键重放返回已创建的原 retry；不同键不得从已有子节点的旧父操作再开兄弟分支。预算计入整棵历史重试树的实际尝试和已排队预留，不重置旧分叉记录。回答和 skip 重试受理、异步结果提交都必须仍对应当前题及合法面试状态；即使携带最新 revision，也不能重试已经跳过的旧题或重开 completed 会话。已接受 END 后失败的报告收尾仍可按原操作恢复。

`report.coach / resume.compose` 的原始操作首次失败、原因可恢复且预算允许时，服务端最多自动受理一个后继；自动后继和之后的手动 retry 不再触发自动 retry。瞬时网络错误、超时、HTTP 429/5xx 采用一次短暂退避；候选 JSON、Schema、引用或事实边界错误携带具体校验代码与位置定向修正，再执行原有完整门禁。认证、权限、非法配置及缺失事实来源等不可恢复失败不自动重试；缺失事实不补造。上次候选输出与修正上下文仅在进程内存中传递，不写入 Operation、事件或公开错误。

原操作失败、自动子操作受理、`operation.retry_scheduled` 与业务资源的 active_operation_id 在同一事务发布，客户端不会看到“最终失败已公开但自动后继尚未受理”的间隙。自动后继复用 runner 槽位但拥有独立 operation_id，仍共享 `MODEL_MAX_RETRIES + 1` 总预算和每次执行 deadline；失败记录不覆盖。刷新只 GET 当前链尾，不发起新调用。重启将尚未完成的尝试标为 interrupted，后续由用户在剩余预算内明确恢复，不从内存丢失的候选内容静默重放。本自动策略不扩展至文件重传或面试回答分析。

重启恢复扫描 Report 的 `generating` 和 ResumeDraft 的 `generating` 状态及其操作指针，而不只扫描本次被标 interrupted 的 Operation；因此“Operation 已 failed、业务清理写回失败”也能收敛为可观察失败并保留原恢复键。重复恢复不会反复增加 revision。

资料确认/激活 operation retry 使用当前 Profile revision，并校验目标仍是最新快照；每个逻辑激活最多三次尝试，换 Idempotency-Key 不重新开启预算。恢复只作用于原代次 Knowledge，不重复确认事实。上传原始字节不持久化，`document.import` 失败不可通过通用 `/retry` 重放，error.retryable=false，页面明确提供重新选择并上传文件的恢复方式；网络受理结果不明确时，同一已选文件与原请求 body/Idempotency-Key 必须复用，不擅自新建一次模型调用。

健康接口不返回个人数据或密钥；readiness 检查已初始化依赖状态，不每请求调用付费模型。runtime/info 只有 model ID 和配置指纹，不暴露 base URL 中 token/query、真实 key 或内部存储路径。

`GET /health/ready` 的 `content_generation` 为 `configured` 或 `absent`，只说明实际内容生成适配器是否配置，不代表已完成一次模型调用。前端按此字段限制回答优化、简历生成及相应重试；不得仅由 fixture/live 模式推断能力。已有报告读取与已生成草稿确认不受该能力缺失影响。

## 8. SSE 规范

推荐采用 fetch 读取流，便于统一认证、取消读取和错误处理。事件格式：

```text
id: 7
event: policy.decided
data: {"schema_version":"1.0.0","operation_id":"operation_example","seq":7,"payload":{"action":"PROBE","reason_code":"MISSING_REQUIRED_DETAIL","root_question_id":"question_main_1"}}

```

事件类型：`operation.started`、`operation.retry_scheduled`、`node.started`、`node.completed`、`policy.decided`、`question.ready`、`report.ready`、`coaching.ready`、`resume_draft.ready`、`operation.completed`、`operation.failed`、`operation.interrupted`。`operation.retry_scheduled` 写在自动后继上，payload 为 `{parent_operation_id,trigger:"automatic",reason:"transient"|"correction"}`，不含候选正文。既有 `operation.started` 的 `{kind,resource_id}` 形状不变。

P0 不推送未验证的模型 token，因此不会先把错误前提渲染给用户再撤回。节点状态可以即时出现；问题通过来源校验并持久化后才发 question.ready。确有需要再添加独立 P1 token 流，不改变业务事件语义。

- `id` 和 seq 是 operation 内单调整数；客户端去重，不假设到达恰好一次。
- 支持 `after=N` 或 Last-Event-ID=N；两者同时且不同返回 400。服务端重放 seq>N 的持久化事件，然后接续 live。
- 心跳为 `: ping` 注释，不占 seq，不持久化；默认每 15 秒。
- UTF-8 可跨网络块拆分；使用流式 TextDecoder；按空行解析，data 可多行，不能假设一个 chunk 就是一条 JSON。
- 连接断开只停止该监听，不自动取消后台业务；页面重连先获取 Operation/Interview 快照，再按 last_event_seq 接事件。
- 终态至少保留在 Operation 快照；拿不到历史事件时 GET 快照，不能重新发一次答题来“恢复”。
- `question.ready` 必须附已提交 question_id 和 interview_revision；客户端可 GET 最新 InterviewView。
- 禁止把 HTTP 连接正常关闭当作 operation.completed。没有终态事件时查快照。
- 设置 no-cache；反向代理不得缓冲 SSE；本机不经过代理也要测试断流恢复。

## 9. 岗位知识包 API

| 方法与路径 | 输入 | 成功 | 语义 |
|---|---|---|---|
| GET `/knowledge-packs` | 无 | 200 {items,default_pack_release_id,import_limits} | 真实 release 列表；每项含格式/审核/可选择三个独立状态与阻断原因 |
| GET `/knowledge-packs/{release_id}` | 无 | 200 KnowledgePackDetailView | 详情：范围、能力覆盖、来源登记、校验明细；不含参考答案/评分细则/Seed 正文 |
| POST `/knowledge-packs/import` | multipart：file（ZIP）；header：Idempotency-Key | 202 OperationAccepted | 安全解压校验后异步登记；结果只声明格式通过 |

契约要点：

- 无“全局激活”写接口。默认 release 固定为当前进程启动时登记的内置资产，不按最新导入版本查找；导入同一 pack_id 的新版本不得改变默认值。选择只影响新创建的面试；已创建面试使用其冻结绑定（§6）。
- 导入幂等：相同 key + 相同上传内容 hash 复用原操作；相同 key 不同内容返回 409 `IDEMPOTENCY_CONFLICT`。相同内容不同 ZIP 重打包按内容 digest 去重复用原 release（`result.reused=true`），不生成第二项；同 `(pack_id, version)` 不同内容返回 409 `PACK_VERSION_CONFLICT`，禁止覆盖旧包。
- 上传限制由 `config/demo.yaml knowledge_packs.limits` 集中声明（ZIP 5 MiB、解压 20 MiB、单文件 1 MiB、条目 256、压缩比 50、路径深度 5）；超限 413 `PACK_UPLOAD_TOO_LARGE`；ZIP 内绝对路径/`..`/符号链接/设备文件/加密条目/声明外文件全部拒绝（`PACK_PATH_*`/`PACK_SYMLINK_FORBIDDEN`/`PACK_ENCRYPTED`/`PACK_UNDECLARED_FILE` 等，422 类不可重试修复）。
- 普通 ZIP 目录条目（例如 `seeds/`）经过路径和类型校验后允许存在，不作为内容文件计入摘要；目录与文件同名冲突、路径穿越等仍拒绝。是否可用只由实际声明文件与内容校验决定。
- ZIP manifest 里的 `approved` 只是作者声明，服务端一律从 `unreviewed` 开始。有效审核 = 绑定当前 `content_digest` 的包外负责人记录 ∩ Seed 内容 hash 批准范围；批准经 `scripts/manage_knowledge_pack.py` CLI 由负责人登记，HTTP 面不提供自批接口。
- Operation result：`{release_id, pack_id, version, content_digest, reused, review_status, selectable_for_new_interview}`。导入成功 ≠ 可用于技术评分。
- 列表/详情/导入不依赖模型或候选人 embedding 就绪；没有可用包时这些入口仍可访问，仅“生成面试”能力不就绪（`/health/ready` 的 `knowledge_packs` 与 `default_pack_release_id` 增量报告）。
- 内置 embedded-software-junior release 由启动时 `ensure_builtin` 登记，批准范围锁定为 M2-01 负责人已批六条 Seed 的固定历史版本与内容 hash；不从本次待导入文件重新计算“可信批准值”。新增或修改的内置 Seed 不会自动获批。
- 列表与详情读取实际存储并重新核对内容摘要；损坏、缺失或不合法时 `validation_status=failed`、`selectable=false`，附真实阻断原因与完整性失败明细。历史审核记录不因损坏被改写，也不能替损坏内容取得当前使用资格；面试受理与恢复仍独立复查，不依赖浏览器标签作安全判断。

## 10. 示例业务请求

```http
POST /api/v1/interviews/interview_example/answers
Content-Type: application/json
Idempotency-Key: answer-demo-turn-0001

{"expected_revision":3,"question_id":"question_main_1","client_turn_id":"turn_demo_1","answer_text":"我们在访问共享总线的位置加了锁。"}
```

```json
{"data":{"operation_id":"operation_example","resource_type":"interview","resource_id":"interview_example","status":"queued","events_url":"/api/v1/operations/operation_example/events"},"meta":{"request_id":"req_example"}}
```

这是合成契约示例，不是抓取到的真实响应。实际服务必须用契约测试验证。

## 11. 文档同步要求

每次接口变更先登记：涉及路径、字段、状态、错误、幂等、事件、迁移、兼容性。更新本文件后同步 Pydantic DTO、导出的 OpenAPI、TS 生成类型、前端错误分支、契约测试和 process.md。

新增字段不能只改返回示例；修改 enum 必须检查所有 switch 与恢复逻辑。破坏性语义变更先加 ADR，并保持 P0 Demo 客户端和服务端同一发布版本。
