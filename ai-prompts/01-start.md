# 给施工 AI 的首次指令

请先读取 AGENTS.md、process.md、docs/01-prd.md、docs/02-architecture.md、api.md、docs/13-risks-and-decisions.md 和 docs/14-sources-and-rules.md。

这是一个尚未实施的 Demo 工程规范包，不是已有项目完成状态。你的首轮任务仅为 **M0 技术验证与环境锁定**。不要一次性生成所有业务模块，不要先做首页，不要复制整套旧 ZhiJue 或 JadeAI。

先检查实际工作区、Git 状态和现有文件。若在旧仓库里，保留用户修改，默认在独立分支或新目录建 demo，不覆盖 main，不擅自 push。将开始任务与证据写入 process.md。

按顺序完成：

1. 列出本机环境、真实可执行命令、可用模型配置，以及仍需负责人的学校/材料/国产 OS 确认项。
2. 对照官方已发布版本验证 Python 3.11 与 openjiuwen==0.1.18 候选，查实际安装导入路径；优先使用文档中的真实 WorkflowAgent/Workflow 方式。不要猜 SDK API，不照抄关闭 TLS 的示例。
3. 跑一个最小真实工作流，并用实际模型完成最小结构化调用。没有密钥或费用许可则标 BLOCKED，不能改为假模型再报成功。
4. 验证 SimpleKnowledgeBase + 官方 Milvus Store/Indexer + Lite 本地索引 + 候选本地 embedding 的实际组合：入库、带来源检索、进程重启后检索、删除后不再命中、另一档案隔离。失败先最小复现，不替换为同名假模块。
5. 在真实通过后锁精确版本、保存依赖与环境 manifest、补 smoke 测试和 doctor。本文档不含真实锁文件，禁止编造 uv.lock/pnpm-lock。
6. 同步架构版本段、风险记录、process.md；涉及接口变化同步 api.md。给出实际命令、退出码、证据路径及唯一下一任务。

M0 失败时交付可靠阻塞说明和下一验证动作，不搭建看似完美但不能执行的业务空壳。涉及付费、真实材料外发、公开网络、框架替换或额外基础设施，先取得负责人授权。

本轮结束不自动展开所有后续里程碑；提交 M0 验证结论后，后续施工再按 process.md 的依赖领取任务。
