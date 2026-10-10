# 模型分工、事实约束、评分与回答优化

## 1. 别把 LLM 说成“只有语言生成层”

本系统中的 LLM 仍承担事实候选抽取、回答理解、Rubric 匹配等语义判断，因此仍然可能出错。规则 Policy 只能让行动和边界更可控，不能保证分析正确。

正确表述是：“模型负责提出受约束的语义观察，程序负责校验引用、限制行动、维护状态与计算分数。”不能宣传模型换了效果必然不变。

## 2. 模型任务边界

| Prompt ID | 输入 | 输出 | 不能做 |
|---|---|---|---|
| P-EXTRACT | 已提取 SourceBlock | proposed claims + exact_quote | 自己补技术、比赛奖项和成果 |
| P-JD（当前实现未使用） | —— | —— | JD 要求由所选知识包的声明式规则确定性抽取，不调用模型；规则同样不得把 nice-to-have 升为必须 |
| P-QUESTION（当前实现未使用） | —— | —— | 五个 slot 由规划纯函数排定，题面在 start 时从已审核 Seed 或经历/证据回退模板确定性实例化，不调用模型；不得自选计划外能力/前提 |
| P-OBSERVE | 问题/Rubric/回答/参考 | AnswerObservation | action、overall_score、hire 建议 |
| P-RESUME | 确认事实及目标岗位 | 文案+事实映射+缺失项 | 直接覆盖确认资料 |
| P-COACH | 原回答、已验证反馈、允许事实 | 改写答案+改写说明+待补问题 | 编造个人经历、数据、实验结果 |

各 Prompt 存文件、版本和变更理由。任何 Prompt 修改都有回归用例，不只凭一条输出更好就替换。
P-EXTRACT 固定输出 `schema_version + claims[]`；每项只有 `text / source_block_id / exact_quote / section`。`text` 必须与 `exact_quote` 逐字符相同，quote 必须是对应 SourceBlock 的连续子串，section 只能是 basic/education/project/skill/award/other。最多 50 项；模型只负责从不可信材料中选择候选片段，不能总结、拼接或改写。服务端同时拒绝电子邮箱、URL 和手机号等联系方式，并在同一事务写 Document、SourceBlock、proposed Claim 和 Profile revision；验证失败不落部分材料或候选事实。

## 3. 结构化输出处理

使用模型实际支持的结构化能力，但 M0 必须用真实端点验证，不能因为接口“兼容”就默认所有 response_format 都支持。

接收顺序：严格 JSON/Schema 校验 → ID/枚举/长度检查 → exact_quote 匹配 → 当前用户/快照归属检查 → 技术参考适用性检查 → 关键结论语义审核 → 业务提交。

只有回答优化与简历生成允许一次自动的定向修正后继（计入同一预算）；回答分析失败只记录并保留原回答，由用户在预算内显式 retry；经历抽取失败整批不落库，由用户重新上传。任何路径都不允许自动补一个缺失评分、自动将字符串“很好”变成 90，或将非法来源换成最相似的一条。超出共享重试预算后明确操作失败；不能把解析失败当候选人回答失败。

外部知识引用通过不代表推理正确。P0 对数值、版本、技术断言和否定判断额外检查；低把握时 not_assessable，而不是让第二个模型随便背书。

## 4. 安全输入模板

系统指令定义角色、范围、允许字段、禁止事项。文档/回答置于明确数据区，携带 source IDs，不拼成更高权限指令。材料中的“忽略之前要求”“给满分”“调用这个地址”全部按原文数据处理。

模型不得从材料触发工具执行、URL fetch、shell、数据库查询或下载。P0 不向模型开放任何工具，Prompt 明确禁止调用工具与浏览；问题、回答、Rubric、参考要点和已确认经历都由应用服务直接放入数据区，模型不自行发起资料检索。用户提出新操作仍要通过 API 明确授权，不能仅从上传文件中提取命令。

## 5. 事实分界示例

- “简历写使用 FreeRTOS”只能证明材料包含该叙述；不能证明用户掌握所有任务调度机制。
- “用户能解释锁保护范围”支持本轮该题的表达/技术要点；不能证明他是项目唯一作者。
- “同一个人又在 README 写了一遍”不是独立佐证。
- “新技术无法检索”意味着没有足够技术依据，不意味着该技术不存在；也不意味着它真的存在。
- “性能提高 30%”需澄清口径。假设原占用 51% 降到 35%，差是 16 个百分点，相对降幅约 31.4%；不能将百分点与百分比混用。这里是计算示例，不是用户真实测量结果。

## 6. Rubric 与确定性分数

每根问题在开始前固定若干适用 criterion、权重与 0—3 的等级说明。评分模型只提出 level 与依据，程序计算数字。

设该根问题固定适用项权重总和为 W，能评价项集合为 A，等级 l_i∈{0,1,2,3}：

`coverage = sum(w_i for i in A) / W`

`score = round_half_up(100 * sum(w_i * l_i / 3 for i in A) / sum(w_i for i in A))`

当 A 为空、coverage<0.60 或任一 criterion 的有效证据同时包含 supported 与 contradicted 时，root_score=null；冲突项显式标 disputed，不按最后一次回答覆盖。0.60 是本 Demo 操作门槛，不是统计置信阈值。数字舍入使用 decimal `ROUND_HALF_UP`，避免语言默认银行家舍入造成边界漂移。

不能在看到用户答错后把该项改为不适用提高分数。任务本来不适用的项由题目生成时确定；因技术参考不可用导致 not_assessable 必须降低 coverage 并写明原因。

未提到被明确问到的关键点可以记 missing，并按 Rubric 评价该回答；没问到、跳过、网络错误、解析失败绝不能当作零分。技术判断须有对应 reviewed 参考和适用版本。

总览仅在至少三根问题 `status=scored` 时提供，P0 五根问题各权重为 1，对可评分根题取算术平均并用同一 `ROUND_HALF_UP` 到整数；JD 的 3/1 只影响题目选择，不暗中改变评分权重。其他情况下 overall_score=null，仍可展示已完成单题反馈。报告同时展示已计划、已提问、已回答、可评分、覆盖不足、冲突、跳过和未测的计数。

## 7. 主回答与追问如何合并

主回答和补充回答各自保留 Observation；最终根评价对每个 criterion 合并有效证据，而不是对两份分数简单相加。重复复述相同点不增加权重。出现冲突标 disputed，并给出两段原文，不按“最后一句永远正确”处理。

报告可以展示追问前后“本题证据更充分”，不能直接称“能力提升 20%”。经过提示生成的答案更不能成为原本作答的证据。

## 8. 优化回答的硬约束

P-COACH 输出按 `contracts/coaching-result.schema.json` 固定为根题数组：每项含 `rewritten_answer`、逐段 `segments[].source_refs`、`used_claim_ids`、`changes`、`missing_facts` 和 `cautions`。source ref 只能是本场允许的 `answer_id + exact_quote` 或当前不可变资料快照 Claim；不存在的测量、团队规模、公司、奖项、库版本不得写进正文。

P-RESUME 输出按 `contracts/resume-draft-result.schema.json` 固定为 section/item：每个正文 item 至少绑定一个当前快照允许 Claim，并单列 reason、missing facts 和 cautions。岗位信息只影响排序和措辞，不成为候选人经历来源。

`response_format=json_object` 只保证返回 JSON 对象，不会把仓库里的 Schema 自动交给模型。P-COACH/P-RESUME 的 system prompt 必须逐项声明精确顶层字段、嵌套字段、数组元素形态和禁止别名：例如 coaching 使用 `segments[].source_refs[].exact_quote`，resume 的 section/item 必须包含 `title/item_id/reason`，两类 `missing_facts[]` 均为 `{prompt,reason}` 对象。只写“匹配某个 schema 文件”不可接受，因为远端模型看不到该文件。

生产 live 首轮证明该边界真实存在：模型返回了合法 JSON，但把 `source_refs` 写成 `citations`、遗漏 `schema_version/changes`，并把简历 item 的 `item_id/reason` 等必填字段省略。服务端 Schema 正确拒绝；Prompt 明确完整结构后，同一模型的 coaching 和 resume 候选才通过原有 Schema 与事实校验。回归测试必须检查实际发往模型的 system message 包含这些字段，不以常量存在或 fixture 输出冒充。

服务端不能只相信模型声明的 ID：回答引文必须是对应原回答的逐字子串，Claim 必须属于冻结快照；候选文本若新增输入不存在的数字、把“参与/协助/团队”升级为“主导/负责/独立”，或包含未确认占位符，则整个候选拒绝且不落部分结果。缺失数据只进入提示区，不混进可复制答案或可打印简历正文。

## 9. 面试与教学的区分

P0 正式回答前不给答案提示；默认面试结束后统一反馈。P1 可以加教学提示，但 assistance 状态记录 `none / hint / coached`，数据分析区分提示前和提示后表现。

已知知识与未知技术的评价分离：未知技术仍可问目的、输入输出、选择理由和验证方式，但技术正确性范围不足就不打该项分。不能用“表达流畅”补偿技术依据缺失。

## 10. 必测反例

“随便给我满分”；简历夹带系统指令；用户声称一个查不到的新版本；简历与口述贡献冲突；合法但不同的实现方案；无量化数据的课程项目；助手误读 OCR 字段；ID 存在但引文不支持结论；纯技术调用失败；只有一题有答案却生成六维高分。

这些反例必须进入回归；不能只在 Prompt 里写“不要幻觉”就算实现。


## 11. 明确调用图，避免预算和流程矛盾

回答分析、回答优化和简历生成的每个 logical operation 最多三次尝试（`MODEL_MAX_RETRIES + 1`，硬上限 3），每次尝试只发一次模型 HTTP 请求；回答优化/简历生成的自动后继（瞬时重试或定向修正）与显式 retry 子操作都计入，计数不能因重试重置。经历抽取不走这套重试：按段分批、每批一次调用，任一批失败整次导入失败。锁定模型客户端自己的重试配置，避免 SDK 隐藏重试造成超额。

| 操作 | 默认成功路径的模型调用 | 预算说明 |
|---|---|---|
| 导入/抽取 | 按 `max_extract_chars_per_model_call`（当前 1,600 字）把来源块切成连续段，每段 1 次 | 单文档提取文本上限 30,000 字，超限先拒绝；切分无损、逐字来源不变；任一批失败或合并超过 50 条整次拒绝、不落部分结果，不自动重试，需重新上传 |
| prepare_interview 与 start | 0 次 | JD 要求按知识包规则确定性抽取，五个 slot 由规划纯函数排定，题面由审核 Seed 或回退模板确定性实例化 |
| handle_answer 主回答 | Observation 1 次；若需 PROBE，程序按已校验 criterion 与冻结 Rubric 确定性生成下一问 | NEXT 的主题已经在计划中；PROBE 不再额外调用模型自由改写，避免增加预算和引入虚假前提 |
| handle_answer 补充回答 | 当前补充回答的 Observation 1 次 | 保留主答与补充答各自的 Observation；本轮不继续追问，M4 根题评价再合并两轮有效证据 |
| finish_interview | 0 次 | Assessment/Report 全部由冻结 Rubric 与 validated Observation 确定性计算，不让模型重新给分 |
| report_coaching | 已回答根题批量优化 1 次 | 分数先由代码固定；模型只改表达，服务端逐段校验回答引文/Claim 来源 |
| compose_resume | 受约束文案生成 1 次 | 每个正文条目绑定确认 Claim；事实映射、修改说明和缺失项分开返回 |

剩余次数只用于回答优化/简历生成的一次自动后继（瞬时错误退避或定向修正），以及用户经 `/operations/{id}/retry` 显式发起的重试；回答分析失败不自动重试。跨 operation 累计的会话 token 总预算，以及 usage 缺失时按估算计入，当前实现均未提供：成本只由每个逻辑操作的尝试次数上限控制；返回 usage 缺失时如实记为未知（null），不按 0 计。

如果一个操作达到总尝试上限，允许查看已保存结果和结束；再次向模型申请新预算必须明确提示负责人/用户，不把 retry 包装成新操作绕开限额。

start 确定性实例化的五题必须与原 slot 集合完全匹配，数量和 ID 唯一，使用服务端冻结 Rubric；主问题文本重复时明确拒绝实例化，不得把其他主题随意复制凑五题。
