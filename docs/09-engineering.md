# 工程规范、依赖、可观测性与协作

## 1. 代码组织

后端 API 只做认证/校验/调用应用服务/异常映射。业务条件不能散落前端和 Prompt；Policy、分数聚合、状态迁移是纯函数。SDK 细节只在 adapters/workflows。

Python 使用类型标注、Ruff 格式/规则、mypy 对 domain/application 逐步严格检查。TypeScript 开启 strict；禁止到处 `as any` 掩盖接口不一致。第三方不可控类型可以在适配器局部封装并注释，不关闭整个工程类型检查。

每个 public 函数解释职责和失败语义；注释说明“为什么”，不逐行翻译代码。文件优先内聚，一般超过约 400—500 行再评估拆分，不以机械行数强制碎片化。

## 2. 依赖与环境

只使用一个 Python 包管理器 uv 和一个前端包管理器 pnpm。精确 Python/Node 版本文件、真实 lock 文件提交。运行/部署使用冻结依赖，不在容器启动时 `pip install -U` 或 `pnpm add latest`。

AI 不能为一个小问题随意拉入新框架。新增依赖记录用途、替代方案、体积、许可证、安全风险、是否需要联网下载资产。升级 openJiuwen/模型后必须重跑知识接入和语义回归。

同一项目不要混用两个不同大版本 React 类型定义/运行时，或把 Next.js 老 ESLint 配置整体复制到 Vite。旧依赖不是“之前能跑所以现在无条件复用”。

## 3. Git 与变更粒度

首次进入旧仓库先读取未提交改动，不直接 reset。默认建立独立 demo 目录/分支；不删除旧项目，不 force push，不自动提交敏感配置。复用组件记录来自何处。

建议提交前缀：feat/fix/test/docs/refactor/chore。提交消息带任务编号，例如 `feat(M3-T02): bound follow-up policy and persist decision`。同一个功能的代码/测试/文档尽量同提交，避免接口文档滞后一周。

涉及破坏性 Schema/资源状态变化先写 ADR；禁止通过删除旧 migration 伪造历史。不把数据库二进制、缓存、模型权重、node_modules、.env、真实资料提交 Git。

## 4. 异常与重试

领域错误类型化，API 对应统一 code。重试只针对明确可恢复上游问题；401/403、非法参数、无效模型名、权限错误不重试。

模型网络重试与 JSON 修复共享一个三次尝试预算；总时间也受操作 deadline 限制。retry API 不能重置计费/token 总预算。修复同样记录尝试与输出有效性。

禁止 `except Exception: return default_report`。对于预料之外异常，记录去敏栈和 request_id，给用户可读失败，不泄漏 base URL token、正文或完整文件路径。

## 5. 日志与指标

结构化日志字段：timestamp、level、request_id、operation_id、interview_id（不含姓名）、node、duration_ms、status、attempt、error_code、sdk_version、model_id、run_mode。

节点日志不得包含完整简历、邮件、电话、API key、Authorization、完整 system prompt、原始答题长文本。合成测试数据的内容级追踪与普通服务日志分开；默认不开生产原始内容日志。

计量真实 token、模型尝试、操作耗时；provider 未返回 usage 时设 null 并保留 unavailable_reason，不能估成“免费”。费用计算仅在负责人给定单价和货币时启用，标 estimated；不能从模型名猜价格。

## 6. 并发与资源

API 单进程；应用允许最多两个上游模型请求并发。SQLite 不在网络等待期间持锁，事务短，连接不跨线程共享 Session。解析和 OCR 使用有界执行池；限制内存、页数和耗时。

不为单机 Demo 增加 Redis/Celery。进程内队列必须有 Operation 持久化和 restart 恢复规则；不能只加 BackgroundTasks 后就声称可靠任务调度。

SSE 是操作事件流，不是第二份业务状态。关键状态从已提交快照取得；事件重放只更新展示，不重复执行业务。

## 7. 最低安全要求

默认端口只发布到 127.0.0.1。容器内部可监听 0.0.0.0，但不能因此自动把宿主端口开放公网。公开前负责人确认、添加认证/授权/限流/HTTPS/访问日志与数据说明。

上传检查扩展名、MIME、文件头、真实 bytes 大小，使用服务端随机文件名及临时隔离目录；不信任用户文件路径，不解压未知压缩包，不执行宏/脚本。PDF 解析限制 CPU/内存/时长，避免大展开流耗尽资源。

TLS 验证默认 true；即使上游官方示例为演示关闭校验，也不得照抄。只在本机受控 HTTP 开发端点例外且明确记录，不得拿含个人资料的远程明文地址当正常配置。

真实信息传给远程模型前取得用户同意；最小化数据，只送必要项目段落。删除必须涵盖索引、缓存、日志中获准保存的内容及派生报告。备份删除时效如实说明。

## 8. AI 并行协作

最多两个有明确边界的并行任务：例如 UI 和不改契约的题库审核。公共 Schema、api.md、process.md 由主施工 Agent 统一维护。

不允许两个 Agent 同时改领域 Schema/数据库 migration。任务领取写路径锁与预期接口；合并时先检查契约变化，再跑集成回归。负责人不需要调度十个 Agent。

## 9. 复用与来源

旧 ZhiJue 的自有组件可选移植但必须验证接口与状态；第三方项目只借思路或明确许可下复用，记录文件/版本/许可/改动。不能把未阅读代码的高级功能当作已有能力。

材料来源、题库许可、框架版本归档见 `docs/14-sources-and-rules.md` 和审核清单。网页可访问不等于可批量抓取再分发；不为赶 Demo 大规模采集真实简历。
