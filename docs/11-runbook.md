# 环境、部署与故障处置手册

## 1. 环境策略

M0 在独立目录创建 Python 3.11 环境、Node 24 LTS 环境；不要修改用户全局默认环境。按照 `config/environment.env.example` 创建本机 `.env`，只填写实际允许使用的端点与密钥。

选一个文本模型，先测中文、超时、上下文长度、JSON 输出和 usage 返回。模型名称保持配置项，不在源代码硬编码某个新发布型号。TLS 默认校验。

当前 P0 embedding 使用负责人授权的远程 OpenAI-compatible BGE-M3 配置，经 openJiuwen `OpenAIEmbedding` 调用；没有下载本地 embedding 权重。密钥仅放 `.env.local`/secret。若后续改为本地模型，必须另行说明新增依赖、固定 revision/hash 并重新验证；不得把候选方案写成已实施。当前兼容 openJiuwen 来源首次同步需要 Git/网络，Docker 镜像如后补应在演示前预构建，不在现场临时安装。

## 2. 配置来源

业务限制读 `config/demo.yaml`。环境相关和密钥读 `.env`。前端只接收需要展示的公开运行信息，不编译密钥、远程模型 token、数据库路径到 VITE_ 环境变量。

本地部署默认发布到 127.0.0.1。真实数据、数据库、知识索引、上传分别在 gitignored runtime 下；启动时拒绝将 tests/fixture 库当成用户数据运行。

## 3. 命令接口（M1-03 起：已落地目标与仍为目标的项）

根目录 `Makefile` 已存在，且**只登记真实可运行的目标**：`doctor`、`check`、`lint`、`test`、`test-live`、`api`、`web`、`dev`（`dev` 只提示分别启动两个前台进程）。其余命令仍是目标契约，未实现前不写入 Makefile（不把未实现能力包装成一键启动）。


| 命令 | 应做什么 |
|---|---|
| `make doctor` | 检查 OS/架构、版本、配置、卷权限、模型资产；不打印密钥 |
| `make install` | 用锁文件安装依赖；首次无锁需显式 bootstrap |
| `make migrate` | 执行 Alembic migration，不自动丢表（目标；当前用 alembic 命令直接执行） |
| `make seed-demo` | 导入合成资料/已审核题库；重复执行不产生重复数据 |
| `make dev` | 启动 API 与前端开发代理，默认本机（当前实现：分别运行 `make api` 与 `make web`） |
| `make check` | 格式/类型/单测/契约/文档，默认不花模型费用（当前实现：`lint` + `test`） |
| `make test-live` | 显式真实 SDK/模型 smoke，需授权与预算 |
| `make test-e2e` | 浏览器闭环，区分 fixture 与 live |
| `make build` | 生成静态前端与生产镜像，不带真实 runtime |
| `make up` | 生产模式本机启动、卷与健康检查 |
| `make backup` | 创建一致性备份与版本清单 |
| `make export-demo` | 只打包合成输入、许可允许内容、报告、截图、版本 |

AI 必须维护命令真实行为；不把“建议手动做的步骤”藏在一键启动宣传后面。

## 4. 推荐容器形态

多阶段构建：Node 构建 SPA → Python 运行层保存静态资源与 API。SPA 非 API 路由回退 index.html；不存在的 /api 路由必须返回 JSON 404，不误返回首页。

API 一个 Uvicorn worker，非 root；可写目录仅 runtime 和受控临时目录；镜像内的种子/代码只读。持久化业务库与索引。配置合适健康检查和停止宽限期，关闭时取消/标记未完成操作。

若后续使用独立反代，确认 SSE 不缓冲、超时足够、不要把私有文档目录直接暴露成静态路径。对国产 OS 的测试使用目标系统实际环境，不只更换 Docker 镜像标签。

## 5. 三种模式

**live**：真实 LLM 与真实 Knowledge，供最终核心演示。

**fixture**：固定输入输出，供单元/界面测试，显著标签；不用于性能和智能效果声明。

**replay**：播放已记录真实历史轨迹，显示录制时间/版本与“非实时”；网络故障时只能显式选择，不自动冒充 live。

首启缺 LLM 密钥时 health/live 可正常，health/ready 根据 mode 判断；live 未配置则不允许开始面试。不能自动偷偷进入 fixture。

## 6. 故障处置

| 故障 | 保留什么 | 用户动作 | 开发排查 |
|---|---|---|---|
| PDF 无文字/错序 | 原件、提取片段、状态 | 粘贴/校正，不重填全部 | 页级提取和资源限制 |
| Knowledge 入库失败 | 原件与 profile 快照 | 重试入库 | SDK/backend/version/来源映射 |
| 模型超时/429 | 原回答和 operation | 等待后显式 retry | 重试预算、超时、额度 |
| JSON/引用无效 | 原回答、错误原因 | 重试或结束 | Schema/语义校验，禁止默认分 |
| 浏览器刷新 | 全部已提交业务状态 | 自动 GET 快照并重连 | seq/cursor/重复事件 |
| API 重启 | DB 中原回答与操作 | interrupted→显式 retry | 不将遗留 running 当已完成 |
| SQLite busy | 短事务未提交的内容回滚 | 可重试 | 长事务/并发 Session/多 worker |
| 删除部分失败 | tombstone 与最小清理操作 | 查看 deleting/重试 | 索引/文件/报告残留 |

## 7. 备份与恢复

不能运行中只复制 SQLite 主 .db 而忽略 WAL 一致性。使用 SQLite 备份机制或短暂停写/停止服务后备份；保存 manifest、schema/migration 版本与原件，索引可按同一版本重建。[S12]

恢复先用隔离目录验证：迁移版本一致、原件 hash 一致、知识索引可读/可重建、旧 operation 不会自动重放已完成业务。成功后再切换。备份包含真实资料时加访问控制，不打包给评委。

## 8. 演示前检查

模型连通、剩余额度、系统时间、live 标签、当前合成资料、Knowledge ready、五题计划、一次追问路径、报告引用、刷新恢复、导出打印、删除测试、版本清单和网络备用方案。

稳定快照提前至少一天冻结；现场只改配置，不升级依赖和模型。原始来源、许可证和 API 文档一起准备，便于回答“用到了哪部分框架”。
