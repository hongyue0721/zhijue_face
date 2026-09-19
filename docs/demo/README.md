# 冻结 Demo 输入登记

登记日期：2026-09-18。本文补充现有规范，不代表业务功能验收。

## Demo Resume v1

- 来源：负责人指定的本地 PDF；原始路径和个人身份信息不进入版本库。
- 原件可用性：已实际读取，已解除此前“只有文件名、未找到 PDF”的阻塞。
- 本地登记：原件、身份信息、解析指纹、逐页文本与 manifest 仅放在 ignored `runtime/private/` 和 `runtime/evidence/`，公开仓库不保存具体内部 ID。
- pypdf 已验证文字层非空且私有副本与显式指纹一致；具体字节数、页数、字符数和指纹不公开。
- 项目/技能/竞赛及关键技术文本可提取；这只是接收检查，不是结构化项目识别、来源审核或能力验证。
- 原件副本与解析产物为本地私有文件，0600；内部目录 0700，runtime 全部忽略。未向外部模型发送正文；未输出完整正文到日志。
- 删除策略（接收工具阶段）：尚无业务删除 API。需要删除时，应同时删除对应 ignored 私有目录、receipt 和摘要中的关联信息；原始私有文件由负责人管理。本次没有执行删除。
- Evidence Extraction / Candidate State / 确认快照已在 M1 完成验证；M2-02 从该 PDF 实际产生 21 条事实、8 条 JD Requirements 和 5 个 Slots。事实仍是 candidate_claim/confirmed 状态，不因进入计划而升级为第三方证实能力。

## Demo JD v1

冻结版本见 [demo-jd-v1.md](demo-jd-v1.md)。它是负责人提供的比赛演示岗位配置，但没有可核验的企业原始公告与上游哈希，因此来源必须标记为 `SYNTHETIC_DEMO_JD`。业务接口未提供 `jd_text` 时使用更小的 `data/jd/preset_embedded_junior.txt`，同样显式标记为 synthetic；任何本地文件路径都不构成真实来源认证。

## 冻结链路与边界

Resume → Evidence Extraction；JD → Requirement Extraction；Evidence × Requirement → Candidate State → Interview Plan → Seed Selection → Contextual Question。禁止直接 Resume + JD → 超长 Prompt 出五题。

- 自述只能是 candidate_claim；unverified ≠ weak，未找到证据允许 unknown，冲突保留。
- Linux 基础/学习声明不等于 Linux 驱动能力；姓名、邮箱、GitHub 不可作为业务分支。
- Gap 由实际材料产生；负责人给的预期仅用于检查合理性，不是硬编码输出。
- 首批仅六条：UART 错帧、Queue、Mutex/Semaphore/shared resource、任务优先级与实时性、CAN 仲裁/拥塞、状态机与非阻塞。
- 新 Seed 必须包括 id、competency、difficulty、archetype、intent、prerequisites、stem_template、reference_points、red_flags、followup_strategy、knowledge_refs、review_status。
- 状态统一为 draft → technical_review → approved；其中 technical_review = Level 1 通过、Level 2 待做，最后一级仅负责人确认。当前六条已经实现并通过 Level 1，仍未完成 Level 2，不得冒充 approved。`review_levels`、reference points、red flags 与 follow-up strategy 已由 ADR-013、Schema 和校验器显式对齐。
- 有限 Policy 顶层动作保持 CLARIFY / PROBE / NEXT / END；追加要求中的 CHALLENGE 按 ADR-013 映射为 `PROBE + counterfactual/pushback`，未静默新增第五种顶层动作。ADR-013 仍为 PROPOSED，待负责人确认。
- 追问由实际证据缺失驱动，不按固定剧本、不对充分回答强行追问。展示结构化动作原因、证据和 Workflow 状态，不展示私有推理过程。
- M0、M1、M2-02 与 M2-03 的施工验证已完成；当前门禁是六条 Seed 的 Level 2 与负责人批准，继续禁止提前扩多岗位或题库。

## 模型与 Knowledge 验证登记

负责人指定 embedding `BAAI/bge-m3` 和 OpenAI-compatible 网关；本地私密 base/key 不进入文档。M0-03 已用 synthetic 文本 profile 实测 SDK `OpenAIEmbedding` 返回 1024 维并完成 Knowledge 全生命周期；M1-03、M2-02 随后对 Demo Resume v1 的确认事实执行了真实 Knowledge 激活与检索。原始 PDF 正文未直接发送，发送的是受控事实块；实际调用和未知计费字段见各轮 evidence/handoff。

2026-09-19 更新：正式 openJiuwen 0.1.18 wheel 的 `delete_documents` list 返回缺陷仍保留为历史失败，但项目已锁定到基于官方 v0.1.18、仅含 PR #1344 两个提交的兼容 commit `72c4985111b835530ec616f70dd67117eb2e015c`。补丁 worktree 和项目锁定安装各完成一次四进程 live，解析、入库、检索、provenance、重启、两 profile 删除及删除后重启零命中均通过，因此 M0-03/M0-03-DEL 为 `VERIFIED`；这不代表正式 wheel 已修复或负责人 `ACCEPTED`。

LLM 请求名 `deepseek-flash` 已能在官方文档定位，但本项目尚未 live 调用，token/cost 仍为 null / NOT_MEASURED。旧本地 BGE-small/torch 方案已放弃，不再重试。详见 [ADR-012](../adr/012-native-knowledge-local-compatibility.md)、[M0-03-DEL 交接](../handoffs/2026-09-19-m0-03-del.md)和根目录 [process.md](../../process.md)。
