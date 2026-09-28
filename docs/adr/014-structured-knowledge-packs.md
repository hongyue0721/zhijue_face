# ADR-014｜结构化岗位知识包：不可变 release、包外审核与面试冻结绑定

状态：ACCEPTED（负责人主文件 2026-09-25 明确授权本增量并规定边界）  
日期：2026-09-25  
关联：ZhiJue_AIC_AGENT_MASTER.md §3–§6、ADR-013、api.md §6/§9、docs/05-knowledge-and-bank.md

## 背景

嵌入式初级岗的出题事实（六条两级审核 Seed、能力映射、来源登记）此前直接散落在
`data/seeds` 与代码常量中。参赛收口要求：

1. 岗位知识可被打包、导入、审核，并且每一场面试能证明它用的是哪一版内容；
2. 不新增第二套 Knowledge 系统，不把结构化 Seed 强制向量化；
3. 不做“全局切换知识包”影响历史面试；
4. 外部上传包自带的 `approved` 声明不可信。

## 决策

1. **单一真源搬移，不复制语义**：JD→competency 关键词映射、证据关键词、
   RTOS 家族借用规则集中到 `domain/competency_profiles.py` 的
   `CompetencyProfile`（`embedded-junior-v1` 携带历史规则，行为逐条不变）。
   知识包 manifest 的 `competencies.json` 只是该注册表的**声明镜像**，
   不一致即拒绝导入；包不能改写规则。
2. **不可变 release + 内容摘要**：`(pack_id, version)` 唯一；
   `content_digest = sha256(规范化文件集)`。同摘要幂等复用（相同内容不同 ZIP
   重打包不产生第二项），同版本异内容 409 拒绝覆盖。每次解析都从存储重算摘要，
   损坏/缺失显式失败，绝不回落其他包。
3. **审核与内容绑定**：服务端有效审核 = 绑定当前 `content_digest` 的包外
   `KnowledgePackReview` 记录 ∩ 逐条 Seed 内容 hash 批准范围 ∩ 声明状态门槛。
   审核只经负责人本地 CLI（`scripts/manage_knowledge_pack.py`，需
   `--confirm-content-reviewed`）登记；HTTP 面不提供自批接口。内置六条 Seed 的
   M2-01 历史批准以“可审计映射”迁移（固定白名单 + 逐条内容 hash + 原记录 ID），
   内置目录新增 Seed 不会自动获批。
4. **面试受理时冻结绑定**：`POST /interviews` 受理瞬间解析并落库
   `pack_release_id + pack_content_digest + competency_profile_id`；
   start/恢复/retry 只从冻结绑定解析。旧记录三列可空，读路径显示
   `legacy_unresolved`，不回填捏造。幂等重放先找回原操作，服务端默认包变化
   不会把重放误判成冲突（D05）。
5. **导入是异步 Operation**：multipart + Idempotency-Key → 202；上传字节按回执
   持久在受控 runtime 目录，parent-linked retry 复用同一回执（有限预算），
   重启后孤儿上传显式清理；格式/安全类错误 `retryable=false`。
6. **能力就绪分离**：列表/详情/导入不依赖模型或候选人 embedding；
   只有“生成面试”受包可选择性约束。

## 明确不做

- 不做第二套 Knowledge/RAG；候选人知识仍走 openJiuwen 原路径。
- 不做全局“激活”写接口；选择只影响新创建的面试。
- 不宣称任意职业换包即用：服务端只注册 `embedded-junior-v1` 能力配置，
  未注册 profile 的包不可选择。
- 不把结构化 Seed 强制向量化。

## 后果

- 新增三张表与 `interview` 三个可空列（迁移 `a7c4e1f29b58`），旧库数据不回填。
- `seed_bank_version` 字段语义收敛为“冻结内置 release 的内容指纹”，
  保持 runtime/info 与 Report run_metadata 兼容。
- 前端新增一个轻量知识页与准备页选择器；五页布局不重写。
- 演示与测试信任边界清晰：fixture 审核注入只存在于测试/CLI 负责人路径，
  外部上传永远从 `unreviewed` 开始。
