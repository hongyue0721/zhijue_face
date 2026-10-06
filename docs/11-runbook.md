# 环境、部署与故障处置手册

## 1. 环境策略

M0 在独立目录创建 Python 3.11 环境、Node 24 LTS 环境；不要修改用户全局默认环境。按照 `config/environment.env.example` 创建本机 `.env`，只填写实际允许使用的端点与密钥。

选一个文本模型，先测中文、超时、上下文长度、JSON 输出和 usage 返回。模型名称保持配置项，不在源代码硬编码某个新发布型号。TLS 默认校验。

当前 P0 embedding 使用负责人授权的远程 OpenAI-compatible BGE-M3 配置，经 openJiuwen `OpenAIEmbedding` 调用；没有下载本地 embedding 权重。密钥仅放 `.env.local`/secret。若后续改为本地模型，必须另行说明新增依赖、固定 revision/hash 并重新验证；不得把候选方案写成已实施。当前兼容 openJiuwen 来源首次同步需要 Git/网络，Docker 镜像如后补应在演示前预构建，不在现场临时安装。

## 2. 配置来源

业务限制读 `config/demo.yaml`。环境相关和密钥读 `.env`。前端只接收需要展示的公开运行信息，不编译密钥、远程模型 token、数据库路径到 VITE_ 环境变量。

本地部署默认发布到 127.0.0.1。真实数据、数据库、知识索引、上传分别在 gitignored runtime 下；启动时拒绝将 tests/fixture 库当成用户数据运行。

## 3. 命令接口（2026-09-25 岗位知识包轮次后：已落地目标与仍为目标的项）

根目录 `Makefile` **只登记真实可运行的目标**。已落地：

| 命令 | 实际行为 |
|---|---|
| `make setup` | 锁定依赖安装：后端 `uv sync --frozen --python 3.11`、前端 `pnpm install --frozen-lockfile`；零模型调用 |
| `make doctor` | 三档画像检查（offline/toolchain/live）；不打印密钥 |
| `make check` | `lint` + `test` + `spec` + `integrity` + `doctor`，默认不花模型费用 |
| `make spec` | 规范资产校验；新记录写入 ignored `runtime/validation-report.md`，不改发行源码的静态报告或 checksum；`BUNDLE_MANIFEST.json` 是发行元数据，不参与规范资产扫描 |
| `make test` | 后端离线回归，显式排除 `integration_live` |
| `make test-live` | 显式真实 SDK/embedding smoke；需要私密 env 与负责人授权 |
| `make demo-fixture` | `scripts/demo.sh fixture`：默认 `runtime/demo-fixture/`，合成 Knowledge/脚本分析，剥离模型 env 文件配置，零模型调用；不提供回答优化/简历草稿成功结果 |
| `make demo-live` | `scripts/demo.sh live`：默认 `runtime/demo-live/`，要求显式导出私密 env 文件路径；启动只检查 HTTP 存活，不发送模型测试请求，不打印密钥 |
| `make api` / `make web` | 分别前台启动后端（127.0.0.1:8000）与 Vite（5199，/api 代理）；使用 PATH 中真实 node，不依赖仓库外私有目录 |
| `make openapi` | 由运行时代码导出 `contracts/openapi.json`（契约测试断言与实时 document 一致） |
| `make checksums` | `scripts/write_checksums.py` 重建 `CHECKSUMS.sha256`；与 doctor/打包共用索引+未忽略源码清单，排除工作区已删除路径，不改 Git 索引或恢复文件 |
| `make competition-bundle` | `scripts/build_bundle.py`：源码发行包 zip + 逐文件 sha256 manifest + 包指纹 |
| `make verify-bundle` | `scripts/verify_bundle.sh`：干净临时目录解压、防目录穿越、逐文件校验、排除 env/runtime/缓存；锁定安装、`make check`、前端测试/构建，再实际启动隔离 fixture，经 Vite 代理走确认/激活/冻结计划/五题/报告；结束回收自身进程 |

需要更新随源码冻结的静态记录时，在仓库根显式执行 `services/api/.venv/bin/python tools/validate_spec.py --report validation-report.md`，通过后再 `make checksums` 并重新打包。验证既有发行包时不要重签解包目录的 checksum。

仍是目标契约、未实现前不写入 Makefile：`make migrate`（当前由 API 启动时执行或手工 alembic）、`make seed-demo`、`make build`、`make up`、`make backup`、`make export-demo`、`make test-e2e`（浏览器闭环当前以验收脚本+人工证据记录，不是一键目标）。

AI 必须维护命令真实行为；不把“建议手动做的步骤”藏在一键启动宣传后面。

### 3.1 启动、隔离与退出

在仓库根目录执行：

```bash
make demo-fixture
```

launcher 必须保留在前台：Ctrl-C 或向 **launcher PID** 发送 SIGTERM 会结束并回收它创建的前后端进程组；任一服务退出（包括前端正常退出或启动失败）也会停止另一方。先 TERM，最多等待 5 秒再 KILL；不杀占用端口的既有用户进程。端口释放后可再次执行同一启动命令。Linux 需要 Bash、`setsid`、`python3`、`curl`、Node，以及已安装的项目 venv/Vite。不要把 launcher 最后一行改成 `exec` 替换 shell。

真实 live 启动示例（私密文件自行准备，不将密钥写入命令行或 VITE_ 配置）：

```bash
export ZHIJUE_MODEL_ENV_FILE=./.env.local
export ZHIJUE_EMBEDDING_ENV_FILE=./.env.embedding.local
export ZHIJUE_RUNTIME_DIR="$PWD/runtime/competition-accept"
make demo-live
```

两个 env 文件必须存在且可读；**相对路径按执行 launcher 时的调用者 cwd 解析**，不是 `services/api`。launcher 不 source/打印文件内容；后端按配置加载。文本模型自身 `MODEL_TIMEOUT` 在私密模型配置里设置；所有模型 Workflow（事实提取、回答分析、回答优化、简历生成）的外层 deadline 统一从对应适配器解析，默认 `max(60, MODEL_TIMEOUT + 30)` 秒。例如 240 秒请求超时对应 270 秒 Workflow；没有请求超时事实的 fixture 适配器默认 60 秒。

可选正有限值 `ZHIJUE_MODEL_WORKFLOW_TIMEOUT_SECONDS` 显式覆盖全部模型 Workflow；它可以刻意短于请求超时，此时会更早取消，不能把它误当仅回答分析的设置。旧 `ZHIJUE_ANSWER_WORKFLOW_TIMEOUT_SECONDS` 已移除，部署配置须切换新名称；通常不设置覆盖值即可随 `MODEL_TIMEOUT` 变化。SDK session deadline 与外层 asyncio 等待使用同一解析值，事实提取的每个批次也必须传入，不依赖 SDK 默认 60 秒。当前 embedding 使用授权远端 BGE-M3，不需要本地 embedding shim。

`ZHIJUE_RUNTIME_DIR` 可指定独立目录（相对路径也按调用者 cwd）；未指定才使用 `runtime/demo-fixture` 或 `runtime/demo-live`。launcher 强制将业务库和 Milvus Lite 分别定位为该目录的 `business.db`、`knowledge.db`，覆盖宿主遗留的 `ZHIJUE_DATABASE_URL`/`ZHIJUE_MILVUS_URI`，避免跨实例写入。**验证、恢复试验使用全新隔离目录，不复用已有 `runtime/demo-live`。**

端口默认 API 8000、Web 5199，可分别通过 `ZHIJUE_DEMO_API_PORT`/`ZHIJUE_DEMO_WEB_PORT` 覆盖。启动存活探测默认 30 秒，可用正整数秒 `ZHIJUE_DEMO_STARTUP_TIMEOUT` 覆盖；每次 curl 连接与总请求均限制 1 秒。超时或 API 提前退出明确失败并清理，不启动前端、不输出就绪假象。`/api/v1/health/live` 成功只表示 HTTP 存活，**不证明**模型、Knowledge、岗位包或业务 readiness 通过；请检查 `/api/v1/health/ready` 与页面能力状态。

### 3.2 岗位包审核 CLI 的数据库选择

`scripts/manage_knowledge_pack.py` 复用 API 的 `AppConfig`：数据库优先级为 `--database-url` > `ZHIJUE_DATABASE_URL` > `<ZHIJUE_RUNTIME_DIR 或 ./runtime>/business.db`。runtime 同样来自 `ZHIJUE_RUNTIME_DIR`，不会从显式数据库文件的父目录另猜内容存储路径。相对路径与 API 一样相对于当前 cwd；`make api` 会切到 `services/api`，而从仓库根直接运行 CLI 不会。操作已有实例时应显式给出相同的绝对 runtime 与库路径：

```bash
ZHIJUE_RUNTIME_DIR="$PWD/runtime/competition-accept" \
ZHIJUE_DATABASE_URL="sqlite:///$PWD/runtime/competition-accept/business.db" \
services/api/.venv/bin/python scripts/manage_knowledge_pack.py list
```

CLI 不再隐式迁移或创建数据库。`list` 使用 SQLite 只读连接；库不存在、尚未初始化或版本不兼容时失败，先核对目标实例并由 API 启动流程迁移。`review` 仍要求负责人实际核对、期望 digest、身份/备注及 `--confirm-content-reviewed`；未确认不会打开库。此入口不能替代来源审核，也不能让执行 Agent 自行批准新题。

### 3.3 显式付费 live 闭环

服务使用上面的隔离 runtime 启动后，可另开终端执行：

```bash
cd services/api
PYTHONPATH=src .venv/bin/python -m smoke.demo \
  --base-url http://127.0.0.1:8000/api/v1 \
  --output ../../runtime/competition-accept/full-live.json \
  --allow-model-spend
```

该命令调用正在运行的 live API，**会产生真实模型/embedding 费用**，需授权额度。验收目标包括五道根问题自然结束、至少一次追问、报告、全场回答优化与简历草稿确认；失败也保存证据。命令存在不代表本轮已通过，结论必须以实际运行产物为准。它不应纳入默认离线 CI 或 launcher 自动启动流程。

## 4. 推荐容器形态

多阶段构建：Node 构建 SPA → Python 运行层保存静态资源与 API。SPA 非 API 路由回退 index.html；不存在的 /api 路由必须返回 JSON 404，不误返回首页。

API 一个 Uvicorn worker，非 root；可写目录仅 runtime 和受控临时目录；镜像内的种子/代码只读。持久化业务库与索引。配置合适健康检查和停止宽限期，关闭时取消/标记未完成操作。

若后续使用独立反代，确认 SSE 不缓冲、超时足够、不要把私有文档目录直接暴露成静态路径。对国产 OS 的测试使用目标系统实际环境，不只更换 Docker 镜像标签。

## 5. 三种模式

**live**：真实 LLM 与真实 Knowledge，供最终核心演示。

**fixture**：内存合成 Knowledge 回执与脚本回答分析，仍使用真实安装的 openJiuwen Workflow 编排，供界面/流程测试，显著标注 synthetic；不调用真实 LLM/embedding，不证明真实检索、模型效果或性能。回答优化与简历草稿没有 fixture 生成器，相应能力显式 `SERVICE_NOT_READY`，不能把 fixture 当完整 live 演示。已有审核和来源约束仍生效。

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
