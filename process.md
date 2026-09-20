# process｜工程事实、进度和交接

**规范版本：1.0.0**  
**记录日期：2026-09-19**  
**仓库发布：公开 `main` 已推送至 `https://github.com/hongyue0721/zhijue_face`；本地 `master` 仅作发布前回退点，未推送**
**当前阶段：M4 / IMPLEMENTED（M4-01 VERIFIED；M4-02 事实约束生成、五页功能纵切面与首屏 Product Polish IMPLEMENTED；生产内容模型 live、独立验收待做）**
**当前交付：M0 本地技术验证 + M1 业务资料链 + M2 approved Seed/计划 + M3 回答 Workflow/有限 Policy/可靠性 + M4 确定性评分、受约束回答优化、简历草稿与五页首屏收口。**

## 1. 当前真实状态

| 项目 | 状态 | 证据 |
|---|---|---|
| Demo 需求、架构、接口及 AI 施工规范 | 文档已编制 | 规范文档与本轮补充；当前完整性校验见第 12 节及交接，初始 55 文件快照另留存 |
| 赛题和产业赛道基础规则 | 已查阅公开来源 | `docs/14-sources-and-rules.md` |
| 旧 ZhiJue 仓库修改 | 未执行 | 旧业务仓库不在本机；本轮仅向独立 openJiuwen 兼容 fork push，不涉及旧 ZhiJue 代码 |
| 本地工程环境（Python/Node/依赖） | IMPLEMENTED；M0-04 复验通过 | `services/api/uv.lock`（194 包）、`apps/web/pnpm-lock.yaml`、`config/versions.lock.json`、`scripts/doctor.py`、`runtime/evidence/m0-04/` |
| 业务持久层（表模型/迁移/Operation 仓储） | IMPLEMENTED；M1-01 VERIFIED（本地） | `services/api/src/zhijue/`、`migrations/versions/18e3af0d1942`、93 项 pytest（含并发/回滚/约束）；见 §20 |
| openJiuwen SDK 真实安装 | IMPLEMENTED，来源复验通过 | openjiuwen 0.1.18 API 基线；当前从固定兼容 commit `72c49851` 安装，direct_url/源码 hash/lock 一致 |
| openJiuwen Workflow/WorkflowAgent 局部 smoke | IMPLEMENTED，34 项回归通过；独立验收待做 | runtime/evidence/m0-02/；仅合成文本图，不是业务主链 |
| 官方基座/补充 starter 要求 | BLOCKED | 已读 NCSS/u-j8/API/通用示例；答疑查询 HTTP 418，不能排除补充要求 |
| openJiuwen Knowledge + Milvus Lite | VERIFIED（项目锁定兼容组合） | `runtime/evidence/m0-03-del/knowledge-locked-live-20260919T011100Z.json`、ADR-012；正式 0.1.18 wheel 失败记录保留 |
| 实际模型、额度、延迟 | PARTIAL | BGE-M3 full lifecycle live；M3-01 `deepseek-flash` 业务 Workflow 第二次调用通过，10.650749 秒，usage 1156/2544/3700。首轮失败 usage 与全部费用均 NOT_MEASURED/null；单样本不形成 p95 或效果结论 |
| 题库技术审核 | VERIFIED（首批六条） | 六条 Level 1/Level 2 均 passed，负责人明确全部批准；版本 0.2.1，统一记录 `docs/reviews/review_m2_01_level2_owner_20260919.md`。只覆盖首批六条，未扩到 24 条 |
| 本仓库版本落盘 | VERIFIED（公开发布） | GitHub `hongyue0721/zhijue_face` 为 PUBLIC、默认分支 `main`、远端仅该分支；远端 main 已包含公开发布基线与 M3-03 后续提交，本地 `master` 未推送 |
| P0 业务集成/LLM/浏览器测试 | PARTIAL | 真实 FastAPI/SQLite/openJiuwen Workflow + fixture Analyzer/Content Generator 的五页纵切面已通过；生产 Answer Analyzer 曾跑通一次 `deepseek-flash` 合成回答。本轮另以显式 synthetic fixture API 完成五页两轮视觉、状态语义、lost-202 幂等恢复与只读交互验收；生产内容生成模型 live、独立验收与跨代理 SSE 组合仍 NOT_RUN |
| 学校窗口、额外上传项、国产 OS 口径 | 待负责人确认 | 不以此前聊天推断替代正式通知 |

## 2. 任务板

| ID | 依赖 | 状态 | 下一步产物 |
|---|---|---|---|
| M0-01 | — | IMPLEMENTED | 审计、风险与 ADR-011 已登记；独立验收待做 |
| M0-BASE | M0-01 | BLOCKED | 仅额外规则信息 UNCONFIRMED；负责人明确不阻塞独立技术验证 |
| M0-02 | M0-01 | IMPLEMENTED | 本地 smoke/34 项回归通过；独立验收未做，不等于 M0 通过 |
| SPEC-ALIGN | — | IMPLEMENTED（待负责人确认 ADR-013） | 已按 ADR-013 显式对齐：保持四动作、CHALLENGE=PROBE+counterfactual；Seed 新增 reference_points/red_flags/follow_up_strategy/review_levels 并由 Schema+校验器强制；未静默扩枚举 |
| M0-03 | M0-02 局部运行证据 | VERIFIED | 锁定兼容 commit 上解析/入库/检索/provenance/重启/删除/删除后重启均 live 通过 |
| M0-03-DEL | M0-03 最小复现、负责人开始指令 | VERIFIED | PR #1344 精确补丁、项目锁、两次四进程 live 与上游公开反馈均有证据 |
| M0-04 | M0-03 | VERIFIED | 实测锁、doctor（12 守卫测试）、干净重装、pnpm frozen+build、CI 骨架均有本地证据；CI 工作流本身未推送 NOT_RUN；独立验收待做 |
| M1-01 | M0-04 | VERIFIED | 14 表迁移可逆、唯一键/FK 真库生效、幂等/事件/状态机仓储 + 并发竞态通过；独立验收待做 |
| M1-02 | M1-01 | VERIFIED | DocumentService/SourceBlock 落库、T01—T04 受控失败、真实登记 PDF 本地导入 1655 字符与 DEMO-INPUT-01 逐字节一致 |
| M1-03 | M1-02 | VERIFIED | Claim 状态机 + 确认快照（不可变）+ 真实 openJiuwen Knowledge 激活 live 通过；FastAPI 落地 api.md §4/§7 资料与操作路径（含 SSE）、最小确认界面浏览器闭环通过；独立验收待做 |
| M2-01 | M1-03 | VERIFIED | ADR-013 契约对齐 + 六条 Seed 来源与平台边界审核；负责人确认 Level 2 passed 并 approved，统一 review record 可追溯；approved-only live 门禁回归通过 |
| M2-02 | M2-01 | VERIFIED | 真实 Demo Resume v1 PDF→21 facts→快照与 Knowledge→显式 `SYNTHETIC_DEMO_JD`→8 Requirements→Coverage Map→5 Slots live 通过；伪造/缺失真实来源字段会 `JD_PROVENANCE_INVALID`，客户端不能自报真实来源 |
| M2-03 | M2-02 | VERIFIED | 真实浏览器展示资料快照、synthetic 来源警示、Coverage Map、5 Slots 与首题审核门禁；点击生成计划 operation succeeded，URL 可恢复，刷新后仍为 5 Slots |
| M3-01 | M2-03 + Seed Level 2 | VERIFIED | `deepseek-flash` 合成回答经生产 Answer Analyzer、真实 openJiuwen Workflow、Observation 语义校验和确定性 Policy 通过；首次失败按契约拒绝并修正 Prompt/日志边界，证据见 §37 |
| M3-02 | M3-01 | VERIFIED | 本地后端的 Answer/Operation 原子受理、幂等/SSE、失败保留、三次累计 retry、重启 interrupted 恢复及隐私错误边界均通过回归；真实模型单样本与本地可靠性证据分开记录 |
| M3-03 | M3-02 | VERIFIED | 业务链继续 VERIFIED；原视觉冻结由负责人本轮明确授权五页首屏收口后解除。Start/Prepare/Interview 已与 Report/Resume 一并完成当前首屏、响应式与中文展示语义调整，未改变后端契约 |
| M4-01 | M3-03 + M3-01 | VERIFIED | 冻结 Rubric 确定性评分、Assessment/Report 唯一持久化、自然完成与 skip/end 控制、失败恢复、OpenAPI/前端类型和 fixture 五题烟测均通过 |
| M4-02 | M4-01 | IMPLEMENTED | 受事实约束回答优化/简历草稿、Operation/retry、迁移/API、五页 UI 与 Product Polish 均已实现并通过 fixture 回归/浏览器烟测；生产模型 live 与负责人独立验收待做 |
| M5-01 | M4-02 | PLANNED | 题库扩充/对照记录 |
| M5-02 | M5-01 | PLANNED | P0 综合验收 |
| M5-03 | M5-02 | PLANNED | 演示与提交物 |

只在有真实产物时更新。IMPLEMENTED、VERIFIED、ACCEPTED 不可互换；测试没运行写 NOT_RUN；确实尝试失败才填写失败输出。独立验收前保留 IMPLEMENTED 状态。

**`tools/validate_spec.py` 现为 46/46 通过**（2026-09-19；新增两个 M4-02 生成结果 Schema 检查，主演示外设 Seed 的 F4/G4/H7 来源守卫继续通过；历史 28/31、31/31 记录保留在后文章节）。结构校验不冒充生产模型、业务验收或负责人结论。

## 3. 负责人待办

| ID | 内容 | 当前状态 | 对施工的影响 |
|---|---|---|---|
| O01 | 确认校内截止和系统上传字段 | 未提供 | 不能承诺报名资格/必交物 |
| O02 | 确认真实团队与指导教师 | 未提供 | 正式报名门槛 |
| O03 | 确认国产 OS 软件组适配口径 | 未提供 | 提交前合规与环境验收 |
| O04 | 配置实际文本模型与开销上限 | **部分完成**：负责人提供 `deepseek-flash` 私密配置并授权 M3 受控测试；两次实际 HTTP 调用，成功样本 usage 1156/2544/3700，价格/持续调用上限仍未提供。M4-01/M4-02 本轮外部模型调用均为 0 | M3-01 live 已完成；M4-02 生产内容生成 live 或批量验证前仍须明确费用上限，未知 cost 保持 null |
| O05 | 确认合成数据/真实资料许可 | 默认合成 | 不擅自用真实简历 |
| O06 | 完成六条 Seed 的 Level 2 负责人结论 | **已完成**：六条全部 passed / approved，记录 `review_m2_01_level2_owner_20260919` | M3-01 的 Seed 审核前置已解除；批准只覆盖六条 |

## 4. 当前唯一首要任务

**M4-02 生产 Content Generator 受控 live 与负责人独立验收。**

功能、五页 UI 和本地 fixture 证据已经闭合：HTTP/API 事实边界不变，Report/Resume 的生成仍通过真实 openJiuwen Workflow 与严格语义校验，五页当前展示不重算服务端结论。生产内容模型的质量、延迟、usage/cost 仍未验证，负责人独立验收仍 `NOT_RUN`；不能由本轮 16 项前端回归和 synthetic fixture 视觉证据升级为 `VERIFIED/ACCEPTED`。

本轮回滚点：负责人给定基线 commit `59e509e30291e284c5bfd2f2796b294171f5504a`。代码按可靠性、Report/Resume、Start/Prepare/Interview、证据/文档/测试四组独立提交回退；不使用 reset/stash，不覆盖后续用户修改。

更早回滚点：M1-03 开工基线 `runtime/evidence/m1-03/task-start.txt`。M1-03 全部新增路径：`domain/claims.py`、`adapters/knowledge.py`、`adapters/db/profiles.py`、`application/{profiles,operations_runner}.py`、`api/*`、`__main__.py`、`tests/unit/{test_profile_confirm,test_knowledge_activation}.py`、`tests/test_api_contract.py`、`contracts/openapi.json`、`Makefile`、`apps/web/src/{api.ts,App.tsx}`；改动文件 `smoke/knowledge.py`、`adapters/db/{documents,profiles}.py`、`application/documents.py`、`adapters/pdf.py`、`apps/web/tsconfig.json`、`config/environment.env.example`、`api.md`。回滚=删除新增 + 按 `docs/handoffs/2026-09-19-m1-03.md` 恢复改动文件哈希。不使用 reset/stash。

## 5. 每轮更新格式

每轮施工更新本表上方的当前阶段，并在下方追加：日期/任务 ID、工作区 commit 或未提交 diff、修改文件、实际执行命令与退出码、通过/失败/未运行、API 影响、文档同步、阻塞、下一任务。原失败记录保留，不用“最后通过”覆盖全过程。

模型调用使用了假数据还是 live、累计调用/用量是否取得，也要写。时间统一使用带时区 ISO 8601；未知开始/结束时间不补造。

## 6. 变更记录

### 2026-09-18｜SPEC-INIT

编制规范 1.0.0，冻结单岗位与两个入口；明确真实 Knowledge 验证、唯一业务写入者、有限追问、评分与来源边界。补充全国对策提交截止和国产 OS 组别待确认门槛。

本条只记录文档产物，不代表业务阶段已完成。静态校验单独记录在 `validation-report.md`。首次代码施工尚未开始。

## 7. 施工日志

### 2026-09-18T22:31+08:00｜M0-ENV：本地环境配置与依赖锁定

**负责人本轮授权范围：只配置环境，不写业务代码。** 本轮据此只产出环境与锁文件；所有临时探针脚本在执行后已删除，未留在仓库。

**工作区状态**：仓库根（本地绝对路径不公开），分支 `master`，**尚无任何 commit**（空仓库），本轮改动全部为未提交的工作区文件。

**修改/新增文件**

| 路径 | 说明 |
|---|---|
| `.gitignore` | 新建。把 `runtime/`、`.venv/`、`toolchain/`、`.env*`、`node_modules/` 等挡在库外 |
| `services/api/pyproject.toml` | 新建。仅依赖声明，`package = false`，不含 build-system 与业务包配置 |
| `services/api/uv.lock` | 新建。由 `uv sync` 生成的真实锁，未手工编辑 |
| `services/api/README.md` | 新建。说明本目录只有环境、无业务代码 |
| `toolchain/VERSIONS.txt` | 新建。记录本目录 Node/npm/pnpm 实测版本 |
| `process.md` | 更新。当前阶段、真实状态、任务板、下一任务、本日志 |
| `CHECKSUMS.sha256` | 更新**仅 `process.md` 一行**。该文件自称覆盖全部 55 个文件，而 `process.md` 按规范每轮更新，不同步会使完整性基线自相矛盾。其余 54 行未动 |

业务目录 `src/zhijue/`、`tests/`、`migrations/` 曾临时创建用于探针，已按授权范围删除。

**实际执行命令与结果**

| 命令 | 退出码 | 结果 |
|---|---:|---|
| `uv python install 3.11` | 0 | 安装 CPython 3.11.16 到 uv 受管目录，未改系统 Python（系统仍为 3.14.7） |
| `cd services/api && uv sync --python 3.11` | 0 | 解析 194 个包并装入 `.venv`；重复执行幂等 |
| `curl nodejs.org/dist/v24.21.0/...tar.xz` + 解包 | 0 | Node 24.21.0（LTS Krypton）落到 `toolchain/node24/`，未改系统 Node 26.8.1 |
| `npm install --prefix toolchain pnpm@10` | 0 | pnpm 10.34.5（系统原为 11.3.0） |
| `uv run python -c "import openjiuwen, pymilvus ..."` | 0 | python 3.11.16 / openjiuwen 0.1.18 / pymilvus 2.6.9 / fastapi 0.141.1 / sqlalchemy 2.0.54 / milvus_lite 可导入 |
| `sha256sum -c CHECKSUMS.sha256` | 0 | 55/55 一致，规范文档未被改动 |
| `uv run --no-project --python 3.13 --with jsonschema --with pyyaml python tools/validate_spec.py` | 0 | **环境安装前**执行：31/31 通过。该脚本会重写 `validation-report.md`，已逐字节还原并通过校验和复核。环境安装后的复测结果为 28/31，见第 8 节末 |

**外部事实核验（PyPI，2026-09-18）**：`openjiuwen` 当前最新发布版为 `0.1.18`（2026-09-11 上传），`requires_python = >=3.11,<3.14`。这解释了系统 Python 3.14 无法安装该 SDK，必须使用 3.11/3.12/3.13。`docs/14-sources-and-rules.md` 的 [S03] 口径与实测一致。

**未运行项**：没有调用任何真实模型或 embedding 服务；没有运行业务服务、迁移、浏览器测试；没有做前后端 build。**本轮累计模型调用 0 次，token 与费用为 null（未发生，不是 0 元）。** 无任何隐式 mock 或回放。

**API 影响**：无。`api.md` 全部接口仍为 PLANNED，本轮未改动 `api.md`（已检查，无变化）。

## 8. 本轮发现的阻塞与风险（M0 待处理）

### K04 复现：Milvus Lite 与 `pymilvus` 的 `db_name` 推断冲突

状态：**已最小复现，尚未用真实 `SimpleKnowledgeBase` 全链路确认**。级别：高。

`pymilvus` 2.6.9 的 `MilvusClient.__init__` 在未显式传 `db_name` 时调用 `_extract_db_name_from_uri`，把 URI 路径的**第一个路径段当作数据库名**（`pymilvus/milvus_client/base.py:23`）。本地文件 URI 因此被误判：

| 传入 URI | 实际推断的 db | 结果 |
|---|---|---|
| `/tmp/.../m3.db` | `tmp` | `MilvusException: database 'tmp' does not exist` |
| `./m.db` | `.` | `invalid database name: '.'` |
| `m2.db` | `m2.db` | `database 'm2.db' does not exist` |
| `/tmp/.../m4.db` + 显式 `db_name="default"` | `default` | **成功**：建集合、插入、检索命中 1 条 |

即**显式指定 `db_name="default"` 时本地路径可用**；不指定时全部失败。

相关源码事实：`openjiuwen` 的 `MilvusVectorStore.create_client` 调用 `MilvusClient(uri=path_or_uri, token=token, **kwargs)`，**未传 `db_name`**（`openjiuwen/core/retrieval/vector_store/milvus_store.py:108`）；`MilvusIndexer` 复用同一方法建客户端。因此按当前调用方式，框架侧很可能撞上该问题。

**尚未确认的部分**：上述结论来自直接驱动 `pymilvus` 的复现，**不等于**已在 `SimpleKnowledgeBase → MilvusVectorStore/MilvusIndexer` 全链路上复现。M0-03 必须先用真实框架路径确认，再决定修复方式。可选方向（需 ADR，不得静默择一）：向框架的 `create_client` 传 `db_name`；或改用框架原生支持的其他本地后端；或本地 Milvus Standalone。**不得把自建检索包装成原生 Knowledge。**

### 本地 embedding 实现缺口

`openjiuwen` 0.1.18 的 `retrieval.embedding` 仅提供 `OpenAIEmbedding`、`APIEmbedding`、`VLLMEmbedding`、`DashscopeEmbedding`，**均为 HTTP 调用型**；抽象基类 `Embedding` 要求 `embed_query` / `embed_documents` / `dimension`。`config/demo.yaml` 中的候选 `BAAI/bge-small-zh-v1.5`（本地 CPU、512 维）**没有对应的框架内置实现类**；`symphony/experience/embed.py` 中的 `EmbeddingClient` 虽支持 sentence-transformers，但为同步接口，不满足上述抽象契约。

当前 `.venv` 中 `torch`、`sentence_transformers` **均未安装**（未被 openjiuwen 直接依赖引入）。若坚持本地 embedding 路线，需要自行实现 `Embedding` 子类并额外引入权重依赖；若改用 API embedding，则与 `O04` 模型配置一起受限。此项需在 M0-03 / M0-04 明确，并同步 `config/demo.yaml` 的 `actual_compatibility_verified` 字段。

### 失败尝试记录（保留，供后续避免重复）

临时探针首次以 4 节点链（start→upper→tag→end）执行时，`Workflow` 返回 `WorkflowExecutionState.COMPLETED` 但 `result` 为 `{'text': None}`。原因定位为探针自身错误：在 `set_end_comp` 上额外传入了 `outputs_schema={"text": "${text}"}`，把 `End` 实际返回的 `response` 字段重映射到不存在的 `text`。移除该参数后，2 节点与 4 节点链均正确返回 `{"response": "R=HELLO|tagged"}`，`dict` 与 `EndConfig` 两种写法均可。**结论：这是使用方误用，非框架缺陷**；`EndConfig` 的 `response_template` 配 `inputs_schema` 是正确用法。该探针脚本已删除，未落为可复现 smoke，因此 `M0-02` 仍记 NOT_RUN。

### 校验器基线冲突（已实测，3 项失败）

本轮配置环境后实测 `python tools/validate_spec.py`：**28/31 通过，3 项失败**（初始规划发布时为 31/31）。三项失败均非业务实现回归：

| 失败检查 | 原因 | 性质 |
|---|---|---|
| 初始进度未冒充实现 | `tools/validate_spec.py:125` 断言全部任务为 PLANNED，而 `M0-01` 现为 IN_PROGRESS | 预期的基线过期，校验器注释本身写明“将来施工后应更新这项初始基线检查” |
| UTF-8 与 LF | 校验器用 `ROOT.rglob("*")` 扫全仓库，未过滤 `.gitignore` | 环境引入的副作用：扫到 `.venv/`（18,491 个文件）中第三方包的 CRLF 文件 |
| Markdown 本地链接 | 同上，扫到 `.venv/`、`toolchain/` 中第三方 README 的相对链接 | 环境引入的副作用：扫描文本文件从 52 个涨到 19,226 个 |

**已单独复核**：本轮新增的 `.gitignore`、`services/api/README.md`、`services/api/pyproject.toml`、`services/api/uv.lock` 均为合法 UTF-8 且无 CRLF；只看规范文档自身的 11 条本地链接，坏链为 0。即失败项来自校验器**未按 `.gitignore` 过滤扫描范围**，而非本轮文件不合规。

修复方向（需单独授权，涉及改工具行为）：让校验器跳过 `.gitignore` 命中项，或显式排除 `.venv/`、`toolchain/`、`node_modules/`；同时把 PLANNED 断言改为“初始基线快照”或在施工后退役。**在修复前，不得把这三项失败当成实现回归。**

**2026-09-18 已修复（M1-03 轮）**：校验器新增 `iter_assets()`，按目录名排除 `.git`/`.venv`/`node_modules`/`runtime`/`dist`/`build`/各类缓存，并按前缀排除解包的 Node 发行包 `toolchain/node24`，文本与 Markdown 扫描都走该入口；PLANNED 断言改为施工期不变量（状态枚举合法 + VERIFIED/ACCEPTED 必带产物说明）；密钥模板断言从写死的 `LLM_API_KEY=` 改为检查 `API_KEY`/`EMBEDDING_API_KEY` 留空、TLS 开启、无 `VITE_*KEY`、无显式密钥字面量（旧断言自始假失败）。现为 **31/31**，`validation-report.md` 已覆盖重写；未删除任何断言，未回退任务状态。

## 9. 前轮 M0-ENV 未做的事（历史记录）

没有写任何业务代码；没有创建 `src/`、迁移或测试；没有调用模型；没有创建 ADR 文件（建议中的 ADR 仍需负责人确认后再落 `templates/adr.md`）；没有 commit 或 push；没有改动 `api.md`、`CHANGELOG.md`、`docs/` 及 `config/` 下任何文件；没有修改 `validation-report.md` 的既有结论。


## 10. 2026-09-18T07:44:15-07:00｜M0-01 收尾 / M0-02 领取

- 授权：负责人“开始做”；本轮仅完成下一首要任务，不横向展开业务。
- M0-01 审计：master 无 commit；已有文件全部未提交，保留原状；旧仓库不在本机，不迁移。现有 Python 锁与工具链记录保留，不升级依赖。
- 前置输出：风险登记补 K04、本地 embedding 缺口及 SDK legacy 风险；ADR-011 固定本轮验证边界。M0-01 审计交付完成，标 IMPLEMENTED，未冒充独立验收。
- 输入：services/api/uv.lock、已安装 openjiuwen 0.1.18 源码、既有契约和合成字符串；不读取密钥、不外发真实资料、不调用模型。
- 输出：独立 smoke、最小失败测试、实际 SDK 路径与版本、输出 hash、运行日志和交接。
- 路径锁：services/api/smoke/、services/api/tests/、services/api/README.md；docs/adr/、docs/handoffs/、docs/02-architecture.md、docs/07-test-and-acceptance.md、docs/13-risks-and-decisions.md、docs/14-sources-and-rules.md；process.md、CHANGELOG.md、CHECKSUMS.sha256；runtime/evidence/m0-02/（不入 Git）。
- 契约草案：start → transform → end，明确非空文本输入，真实 SDK 调度自定义纯函数节点；分别检查 Workflow 状态和 WorkflowAgent 包装结果，必须严格匹配输出，不允许 COMPLETED + 空结果假成功；非法输入/超时/节点异常失败，重复执行结果一致，失败后新执行可恢复。此处不是业务幂等或持久恢复证明。
- 模式：live（仅本地框架真实执行）+ synthetic 合成输入；LLM/Knowledge NOT_RUN。API 无变化，不创建 HTTP 服务或迁移。
- 验收命令（计划，未运行）：`.venv/bin/python -m pytest tests -q`；`.venv/bin/python -m smoke.workflow --output <新证据文件>`；`.venv/bin/ruff check smoke tests`；`sha256sum -c CHECKSUMS.sha256`。
- 回滚点：修改前原件保存在 runtime/evidence/m0-02/baseline/；本轮新文件按交接清单单独移除，原件仅在比对后恢复，不 reset/stash 用户文件。
- 不改 tools/validate_spec.py（已知三项基线冲突需单独任务）；不处理 M0-03 的后端选择/embedding 实现。


## 11. 2026-09-18T07:51:04-07:00｜负责人追加约束 / M0-BASE 核验

- 20 条强制约束已同步 AGENTS.md 第 10 节；更保守、更可验证优先。本轮不进入 M1、不扩展 UI、题库或产品范围。
- 新增 M0-BASE 专项；M0-02 无模型 smoke 与它独立，但 smoke 通过不意味着官方基座适配、Knowledge 或 M0 完成。
- 已确认：官方 NCSS 题面本次可读，明确 Knowledge 与 Agent Workflow、Memory 可选；该页面正文未列指定 BaseAgent 类或 starter 仓库。
- 初次读取工具未返回可用页面，浏览器工具返回 No browser is available；随后改用 HTTPS 只读获取，成功取得 NCSS、GitCode 分类页和 u-j8 具体解读页（返回码与 hash 见 official/fetch.json）。解读页未列专用 BaseAgent/starter，但还链接官方答疑区；答疑区本次仅取得应用 HTML 壳，未取得帖子正文。因此仍不能排除额外模板/通知，M0-BASE 保留 BLOCKED，不能把“未检索到”写成“官方没有”。
- 最小解阻：取得该命题的详细解读正文/附件/官方模板仓库或企业书面答复；若指定基座，核对仓库与版本，再在其宿主上验证现有能力接入。保留现有业务设计，不另建平行 Agent。
- 允许独立收尾：现有 M0-02 smoke 的源码路径/继承链证据、日志隔离、测试与交接。不运行 Knowledge、不替换 SDK、不升级/新增依赖。
- 补充路径锁：AGENTS.md、services/api/tests/conftest.py 与 docs/handoffs/；修改前快照见 runtime/evidence/m0-02/constraint-checkpoint/。AGENTS 原件已加到 baseline。
- ADR-011 从 AI 自行标记的 ACCEPTED 改为 PROPOSED；既有 smoke 仅是局部实验，未取得官方基座和负责人阶段验收，不称为已接受架构。
- API 无变化；UNKNOWN 与 Seed 条目此轮仅固化语义要求，不修改既有字段/枚举。


### 追加约束的两处契约冲突（尚未修改接口）

- Policy：追加要求列出 CHALLENGE，但 docs/04-workflow-policy.md、policy-decision/operation-event Schema 与校验器明确只允许 CLARIFY/PROBE/NEXT/END，并将 counterfactual 作为 PROBE 子意图。按更保守规则，当前契约暂不增加 CHALLENGE；是否升级独立动作及其预算/状态语义待正式契约变更。涉及 M3-01，不能实现后再补文档。
- Seed：已有 competency_id、intent、difficulty、archetype、rubric、followup_intents、reference_ids；没有显式 reference_points/red_flags，追问意图列表也不能自动冒充完整 strategy。不得声称已满足新增条款。M2-01 前必须经契约草案明确字段或经审核的语义映射；未对齐前不批准/扩充 Seed。
- 以上对齐事项 BLOCKED（语义待确认）；不阻碍 M0-02 局部框架实验，但不是给业务实现的临时豁免。本轮 api.md/Schema/示例原样保留。


## 12. 2026-09-18T07:59:42-07:00｜M0-02 局部交接（阶段未通过）

- 真实链路：Workflow.invoke + 官方 create_workflow_session；WorkflowAgent.invoke → legacy ControllerAgent → WorkflowController → Runner.run_workflow_streaming → Workflow。图为 Start → 纯文本节点 → End，输入 hello，输出 R=HELLO|tagged。
- 本地环境：Python 3.11.16 / openjiuwen 0.1.18 / pytest 9.1.1 / Ruff 0.16.8 / Linux x86_64；不升级依赖。
- 测试：最终 34 passed、0 failed、38 warnings；其中 7 个真实 SDK 用例，27 个输入/结果守卫用例。Ruff check 和 format --check exit 0；两次独立进程 smoke 均 exit 0。
- 输出 hash：`a16f7569d77bdf402de0c9b051d81f24bd82e3e3e2e5fedef6b01a5fb8114b94`（两次相同；只哈希规范化 outputs，不是完整证据文件 hash）。
- 失败保留：red.log 缺模块收集失败 exit 2；first-run.log 为 10 passed/5 failed（session 漏传、Agent 超时后台任务未取消）；依源码修复后 second-run.log 15 passed，再增加边界用例得到 34 passed。ruff.log 保留首次 5 项检查问题；最终格式、显式 subprocess check、错误类型与清理后原异常重抛均处理，未删除断言/吞异常。
- 运行时间、完整命令、退出码：runtime/evidence/m0-02/commands.jsonl；最终日志 pytest-final.log、tests-final.xml、ruff-final.log、format-final.log、smoke-a/b.log 与 JSON。只读官方核验在 official/；旧 SDK 默认日志已移入 sdk-default-logs/，不留源码目录。
- API 无变化；Schema/DTO/调用方/迁移不变，无业务服务。AGENTS、CHANGELOG、架构/测试/来源/风险、services/api/README、ADR/交接同步；数据文档和配置未改，因无持久层/模型变更。阅读版 HTML 与 validation-report.md 保留初始发布快照，不当作当前进度。
- LLM/Knowledge/E2E/干净依赖重装/独立验收：NOT_RUN。模型调用 0；provider/model/prompt/seed/rubric/token/费用 null；没有业务性能或 Grounding Rate 指标，均 NOT_MEASURED。
- 未解决：M0-BASE、SPEC-ALIGN、K04 Lite、K16 embedding、O04 模型配置、官方 SDK 弃用警告、全仓库校验器旧基线。M0/M1 不标完成；任务不写 ACCEPTED。
- 本次没有 commit/push，基线仍是 master 无提交；修改/新增文件、原因、回滚方式见 docs/handoffs/2026-09-18-m0-02.md。所有旧未提交内容保留。
- 唯一建议下一任务：M0-BASE。先汇报，等负责人决定后续，不自动进入下一大阶段。

- 补充资产校验：5 个 JSON Schema 与 8 个示例通过；14 个本轮文本文件 UTF-8/LF/本地链接通过；未授权修改的原始规范资产 hash 不变；CHECKSUMS.sha256 当前覆盖 62 个文件，62/62 通过。命令、时间与返回码另见 commands-assets.jsonl，结果 asset-final.log / checksum-final.log。此校验不替代旧全仓库校验器。


## 13. 2026-09-18T08:13:44-07:00｜M0-BASE 续接领取

- 负责人授权：“开始”后中断，再“继续”；中断前仅只读检查，无新增改动。本轮唯一目标为官方 Agent 基座要求核验，不进入业务阶段。
- 输入：S01/S14 官方题面、S15 官方答疑入口、0.1.18 已安装源码与前轮真实 M0-02 证据。
- 前置：M0-01 的审计产物已在前轮登记；M0-02 仅 IMPLEMENTED/局部回归通过，未将其当作 Knowledge 或整体基座验收。
- 输出：有边界的官方要求/模板/基座证据表、明确调用与继承路径、未确认点及最小解阻方案、阶段交接。查询无结果不等于不存在。
- 允许修改路径：process.md、CHANGELOG.md、CHECKSUMS.sha256、docs/02-architecture.md、docs/13-risks-and-decisions.md、docs/14-sources-and-rules.md、docs/handoffs/2026-09-18-m0-base.md；runtime/evidence/m0-base/（本地原始证据，不入 Git）。本轮不改业务 API/Schema/依赖/源码。
- 方法：仅读公开官方页面、其公开资源/只读接口及官方仓库；TLS 校验开启，不登录、不外发项目数据、不申请付费服务。SDK 路径/版本优先读取已安装文件，不凭最新文档替换锁定 API。
- 验收命令（计划，未运行）：官方 HTTP 读取及 hash 记录；真实 smoke 复跑（如无需额外依赖）；`sha256sum -c CHECKSUMS.sha256`；本轮文本编码/链接与原始资产变更范围检查。API 无变化。
- 回滚点：runtime/evidence/m0-base/baseline/ 保存本轮之前原件；只回退本轮差异，不覆盖用户修改，保留所有旧证据，不执行 destructive git。
- 退出条件：无法取得关键官方说明则保留 BLOCKED 并交付最小解阻点；不能因此自行更换 Agent/绕过 Knowledge。当前阶段汇报后停止。


## 14. 2026-09-18T08:36:03-07:00｜M0-BASE 本轮交接：SDK 证据加固，官方答疑仍阻塞

- 实际新增证据：公开 GitHub 组织列表为 20 个仓库；对 agent-core/docs/community 的非截断目录树做命题/starter/Agent 路径筛查，并读取固定 commit 的 WorkflowAgent 源码/API/通用示例。此范围内未定位到“本命题必须使用的专用 starter”，不推广为官方绝无额外要求。
- 已确认 SDK：安装及 uv.lock 均为 openjiuwen 0.1.18。7 个被审计的入口/调度/session 文件与锁定发布 wheel **7/7 逐字节一致**，下载 wheel 的 SHA256 与 uv.lock 相同；只读取 ZIP，未安装/升级。前轮源码 hash 未变化。
- 版本边界：上述 7 文件中仅 5 个与官方固定 commit `6dfda012193d09dc3908524d5f8ae406811d909f` 相同；Workflow/session 2 个文件有版本差异（例如 name/trace_id），不是本地篡改。以锁定发布版源码为准，不混用 develop 参数。
- 通用 notebook 是天气查询示例，不是已确认的比赛模板；含旧 `openjiuwen.agent.*` 导入。单独导入验证按预期 exit 1（ModuleNotFoundError），未执行 notebook 模型/天气服务代码；正式 smoke 的 `openjiuwen.core.application.workflow_agent` 入口实际通过。没有为跑旧示例而换 SDK。
- 外部失败：官方前端公开资源中确认只读 `/api/v1/discuss/page` 查询，匿名请求返回 **HTTP 418 CloudWAF**，并未拿到帖子；页面壳 200 不等于读取成功。公开 GitHub 组织 discussions 另返回 HTTP 404，也不能作“无额外要求”的依据。不登录、不尝试绕过 WAF/验证码。
- 本轮真实回归：2026-09-18T08:31:21-07:00 至 08:31:37-07:00；SDK 审计 exit 0；原 34 项测试 34 passed/0 failed/38 warnings，exit 0；真实 smoke exit 0，结果/hash 与前轮一致。完整命令、时间、返回码见 runtime/evidence/m0-base/commands.jsonl。
- 证据：同目录 sdk-audit.json、wheel-audit.json、smoke.json、tests.xml、pytest.log、official-example-import.log、fetch.jsonl（HTTP 状态单列；获取器保存错误响应成功不等于 HTTP 成功）、public/。官方原始资源仅留 ignored runtime/，不进 Git/演示包。
- API 无变化；业务源码/测试/依赖锁/配置/Schema/迁移均未修改。仅同步 process、CHANGELOG、架构/风险/来源、本轮交接与 CHECKSUMS。
- Knowledge、实际模型、持久化业务闭环、独立验收仍 NOT_RUN。调用模型 0；provider/model/token/费用/prompt/seed/rubric null；业务指标 NOT_MEASURED。M0-BASE 保留 BLOCKED，M0 整体未通过，无任务自行 ACCEPTED。
- 最小解阻：负责人提供该命题的官方答疑/补充要求/模板仓库材料，或命题方确认是否指定 Base Agent；不能用选手仓库/普通例程替代官方要求。
- 本轮工程汇报：docs/handoffs/2026-09-18-m0-base.md。无 commit/push；不进入 M0-03/M1，不重复扩大搜索。唯一下一动作仍为 M0-BASE 外部证据解阻。

- 本轮收尾检查：6 个修改/新增文本的 UTF-8/LF/本地链接通过；上一清单中非本轮修改的 57 个文件 hash 未变（含 API 和 smoke 源码）；完整性清单新增本轮交接后覆盖 63 文件，63/63 通过。原始命令、时刻、返回码另见本轮 commands-docs.jsonl / document-check.log / checksum-check.log，不替代旧全仓库校验器。


## 15. 2026-09-18T08:46:27-07:00｜M0-03 领取与负责人输入落实

- 主目标：原生 SimpleKnowledgeBase + Milvus Store/Indexer + 本地真实 embedding 的可复现 smoke；先复现 Lite URI/database_name 问题，基于新证据选兼容方案，禁止同名假 Knowledge/mock 接入。
- 前置证据：M0-02 真实运行、34 项回归及包来源审计已具备；不冒充独立验收。额外官方要求状态 UNCONFIRMED，仅保留 compatibility review 待办。
- 授权与路径：AGENTS.md、process.md、CHANGELOG.md、CHECKSUMS.sha256；docs/02、05、07、13、14、docs/adr/、docs/handoffs/；services/api/smoke/、tests/、README、pyproject.toml/uv.lock（如明确需要本地 embedding 或约束内兼容 pin，先记录理由）；config/demo.yaml/environment.env.example；runtime/evidence/m0-03/ 和 runtime/models/（忽略）。不改业务 API/领域 Schema/前端。
- 验证输入：显著 synthetic 的临时简历/项目文本及两个 profile；输出仅内置 ID/hash/来源映射/结果判定，不在日志输出完整简历。
- 契约草案：原生 parse_files → 原生 add_documents → 原生 retrieve；严格检查解析不为空、来源/文本一致、profile 过滤，按已持久化 ID 重启检索，按文档删除后再重启确认不命中；空/无效输入不能报成功。不是业务资料确认或 Candidate State 实现。
- 验收计划：最小失败 pytest；原生链路 smoke 多进程；全量现有测试回归、Ruff、完整性校验。LLM/正式简历/正式 JD 未测不算失败，不伪造模型/成本。
- 回滚点：runtime/evidence/m0-03/baseline/；保存锁文件与文档原件，不改 SDK 源文件、不破坏用户修改、不自动 commit/push。
- 负责人新增输入已落 AGENTS 第 11 节；Seed reviewed/原 technical_review、JD 来源持久化、模型新环境变量属于后续契约对齐，当前没有后端 DTO/API 实现，不静默宣称已支持。
- API 无变化。模型配置未使用，不读取/展示密钥；若引入本地 embedding，须登记实际模型 revision/hash、依赖目的/部署代价/免费本地方式。

## 16. 2026-09-18｜DEMO-INPUT-01：真实 PDF 本地接收核验（IN_PROGRESS）

- 输入：负责人本轮显式提供的私有 PDF；替代此前仅有文件名、无法定位原件的状态。不改 M0-03 优先级，不将此接收检查当作 M1 Evidence 实现。
- 输出：ignored runtime 中的内部 ID 原件副本、逐页真实文本和原件/解析结果追溯清单；公开文档只登记 Demo Resume v1 标签和去敏结论。
- 修改范围：ignored runtime/evidence/demo-resume-v1/、runtime/private/demo-resume-v1/；docs/demo/、docs/handoffs/、process.md、CHANGELOG.md、CHECKSUMS.sha256、docs/07-test-and-acceptance.md。
- 验收：现有 pypdf 本地解析；检查非空页、重点章节与关键技术词；私有副本与显式指纹一致；记录文件权限与 Git ignore。不得把关键词匹配当成 Evidence Extraction 或能力验证。
- API 无变化；不引入依赖、不调用外部模型、不外发简历、不创建业务数据库记录。无法提取即失败，不补写正文。回滚点：runtime/evidence/demo-resume-v1/baseline/，仅比对恢复本轮差异。

### DEMO-INPUT-01 本轮交接（IMPLEMENTED）

- 私有 PDF 已收到并完成本地读取与指纹核验；原件、逐页结果、manifest 和具体计数只在 ignored 私有目录，0600 文件/0700 内部目录，未外发正文或身份信息。
- 接收脚本实际运行 exit0；10项追溯/非空/关键词/权限/忽略/状态检查全部通过；全量 pytest exit0，35 passed、0 failed、38 warnings，11.08s。命令及证据见 docs/handoffs/2026-09-18-demo-input-01.md。没有将检查条件数算作pytest数。
- Demo JD v1 当时按聊天输入登记为 `REAL_JD_DERIVED`，但未持有企业原公告、上游 URL、抓取时间和原文哈希；M2-02-PROV 审查已纠正为 `SYNTHETIC_DEMO_JD`。本条保留接收时序，但不再把聊天标签冒充来源事实。
- API 无变化；未改数据模型或 Workflow/Policy。登记文档明确旧 Seed 状态与 CHALLENGE 契约对齐仍待施工；不暗改枚举。
- 负责人指定 BAAI/bge-m3 远程 embedding 取代本地 BGE-small 计划；deepseek-flash 实际可用模型 ID 尚待核验。本轮没有模型调用；五题 token/cost NOT_MEASURED。旧本地 torch 安装依赖失败/BGE下载TLS失败的日志保留，不重试旧方案。
- 下一项唯一任务仍 M0-03 原生 Knowledge 全生命周期；官方附加基座要求 UNCONFIRMED 不构成其阻塞。当前只验证构造，不能标完整 Knowledge VERIFIED。停止于本轮输入登记交接，不扩业务大阶段。

## 17. 2026-09-19｜M0-03 Knowledge live 交接（BLOCKED）

> 运行发生于本地时区 2026-09-18；本节于 2026-09-19 汇总。状态为 BLOCKED，不是 VERIFIED/ACCEPTED。

### 实际架构与运行链路

- `openjiuwen==0.1.18`；Embedding 为 SDK 自带 `OpenAIEmbedding`，请求负责人指定 `BAAI/bge-m3`。
- Knowledge 为真实 `SimpleKnowledgeBase → TxtMdParser → CharChunker → MilvusIndexer/MilvusVectorStore → Milvus Lite .db`，FLAT/cosine/dense。
- 四阶段设计为不同 OS 进程：ingest → restart_check → delete → post_delete_check；最终只执行到 delete 失败，post_delete_check NOT_RUN。
- 输入是两个明确 synthetic 的文本 profile；Demo Resume v1 未外发。

### 实际通过与证据

- 最小红测：缺少 `smoke.knowledge`，pytest collection exit 2；`runtime/evidence/m0-03/knowledge-lifecycle-red.log`。
- 配置/去敏/真实 SDK 构造守卫最终 13 passed、1 skipped；skip 为未在常规回归中显式开启的 integration_live，不算 live 通过。
- live ingest PID 8317：BGE-M3 返回 1024 维；两 profile 原生 parse/add/retrieve 通过，document/chunk/source/hash provenance 完整；缺文件与重复 doc_id 被拒绝。
- live restart PID 8404：关闭后新进程重建同一 DB，两个 KB 均命中各自来源，未串档。
- 成功逻辑 embedding 调用 7；SDK 未暴露 usage，准确 HTTP transport 尝试数 NOT_MEASURED，token/cost null。DeepSeek LLM NOT_RUN。
- 去敏汇总：`runtime/evidence/m0-03/knowledge-partial-20260918T172000.json`，状态字段明确为 BLOCKED；密钥与工作区绝对路径扫描均 0 命中。

### 失败项与根因

- 前两次 live 使用直接 `/embeddings` URL，2xx 非 JSON 导致 JSONDecodeError；这是实现对 GET 200 的错误推断。更正为 OpenAI-compatible `/v1` base 后读路径通过。失败日志保留：`knowledge-live-20260918T171000.log`、`...T171500.log`。
- delete PID 8470：`delete_documents` 进入真实 SDK；profile A row_count 已由 1 变 0，但 pymilvus 对成功删除返回 primary-key list，openJiuwen 0.1.18 执行 `int(list)` 后返回 false。profile B row_count 仍为 1，post-delete restart NOT_RUN。
- 官方 agent-core PR #1344 正在修复同一问题；当前开放 PR 不能当作锁定发布版已具备。未 monkeypatch、未改 site-packages、未用底层效果冒充框架成功。
- 部分证据生成脚本首次误用系统 Python 3.14，因找不到 venv 包失败且未生成文件；随后用锁定 Python 3.11 成功。

### 修改、命令与同步

- 代码：`services/api/smoke/knowledge.py`、`services/api/tests/test_knowledge_smoke.py`、pytest marker；没有新增第三方依赖。`pymilvus==2.6.7` 是此前 SDK 允许范围内的 Lite URI 兼容 pin。
- 配置：`config/demo.yaml`、`config/environment.env.example`；本地 `.env.local` 为 0600/Git ignored，真实值不进文档/日志。
- 文档：ADR-012、docs/02/05/07/13/14、services/api/README、handoff、CHANGELOG、process。
- API/DTO/SSE/数据库迁移/前端：无变化；`api.md` 已检查，无需改动。
- 实际命令与完整退出码见 `docs/handoffs/2026-09-19-m0-03.md`；最终全量回归与校验和结果以该交接为准。

### Blocker 与下一入口

- 已确认事实：读路径/重启通过；删除返回值处理失败；官方已有同根因开放 PR。
- 未确认：含修复的正式发布版本/时间；比赛是否允许项目内临时适配层。
- 最小验证：优先采用含官方修复的发布版；否则负责人批准窄适配后，完整重跑删除与 post-delete restart，再做全量回归。
- 唯一下一任务：M0-03-DEL。停止于本阶段，不进入 Evidence/JD/Seed/UI。



## 18. 2026-09-19｜M0-03-DEL 删除兼容交接（VERIFIED）

> 命令运行时间为本地时区 2026-09-18 晚间，UTC/交接日期为 2026-09-19。VERIFIED 仅指项目锁定兼容组合通过真实测试，不代表负责人 ACCEPTED，也不代表正式 openJiuwen 0.1.18 wheel 已修复。

### 架构、来源与真实链路

- 正式最新发布仍为 openJiuwen 0.1.18；官方 tag commit `1d37ae3007f9df9a8489a7ab271141b03be08f66`。
- 官方 PR #1344 截至交接仍为 Open/MERGEABLE；精确代码修复为 Milvus Lite list/tuple 返回使用 `len(result)`，另有两项回归测试。
- 项目兼容 commit：`72c4985111b835530ec616f70dd67117eb2e015c`，基于 v0.1.18，仅应用 PR #1344 两个提交；相对 tag 仅 2 个文件、31 行新增。
- 项目 `pyproject.toml`/`uv.lock` 已固定上述 commit；`uv sync --frozen` 成功从该来源构建 openjiuwen 0.1.18。安装后的 `direct_url.json`、commit 和 `MilvusIndexer` SHA256 均与验证 worktree 一致。
- live 主链保持真实 `SimpleKnowledgeBase → TxtMdParser → CharChunker → MilvusIndexer/MilvusVectorStore → Milvus Lite`，FLAT/cosine/dense；没有自定义同名 Knowledge、monkeypatch、site-packages 手改或主链 mock。

### 实际测试证据

- 未修复 v0.1.18 list 回归：1 failed / 1 passed，原始错误 `int(list)`；`runtime/evidence/m0-03-del/baseline-regression.log`。
- 相同回归应用补丁后：2 passed；上游目标测试文件：21 passed。
- 补丁 worktree 四进程 live：exit 0，解析/入库/检索/provenance/重启/两 profile 删除/删除后重启零命中全部通过；证据 hash `5fa0e87f...`。
- 项目锁定安装且明确清除 `PYTHONPATH` 后再次四进程 live：exit 0，4 个不同 PID，两个 profile 删除后总命中 0；证据 `runtime/evidence/m0-03-del/knowledge-locked-live-20260919T011100Z.json`，文件 SHA256 `a6ff46d1...`。
- Knowledge 兼容守卫：16 passed / 1 skipped；全项目 pytest：50 passed / 1 skipped / 0 failed / 38 warnings，8.52s；Ruff check/format、`uv lock --check`、安装来源、静态/安全检查均 exit 0；`CHECKSUMS.sha256` 74/74 通过。
- 上游反馈已发布到 PR #1344：`https://github.com/openJiuwen-ai/agent-core/pull/1344#issuecomment-5738067134`；未创建重复 PR。

### 修改、失败尝试与边界

- 修改代码/锁：`services/api/pyproject.toml`、`services/api/uv.lock`、`services/api/tests/test_knowledge_smoke.py`；没有改业务实现或 API。
- 修改配置/文档：`config/demo.yaml`、`.gitignore`、`CHECKSUMS.sha256`、根 README、docs/02/05/07/11/13/14、Demo 登记、ADR-012、服务 README、CHANGELOG、process 与本交接。openJiuwen 默认 `logs/` 已纳入 ignore，密钥扫描 0 命中。
- 新第三方包：无。依赖来源由 wheel 改为固定 Git commit；对 Demo 的直接价值是解除真实 Knowledge 删除 blocker，代价是首次同步需要 Git/网络，本地免费且无新运行时服务。
- 失败尝试保留：第一次 `gh repo fork` 使用不受支持的 `--remote=false` 参数，exit 1；随后按 CLI 帮助改为 `--clone=false` 成功。一次 shell hash 比对命令括号/管道语法错误，exit 2；来源日志已先成功生成，修正命令后 hash 一致。没有靠删断言或隐藏失败过关。 最终安全/状态检查首轮的宽泛 `sk-` 与 `ACCEPTED` 正则分别误命中 `task-start` 路径和否定说明，两个检查均 exit 1；收紧为边界匹配与正向状态匹配后复跑 exit 0，真实密钥命中仍为 0。
- live 日志会出现 dense-only 集合缺少 `sparse_vector` 的 BM25 fallback warning；最终 dense 检索和所有断言通过。本轮未扩到 hybrid/BM25，不把 warning 包装成已验证 sparse 能力。
- API：无变化；`api.md` SHA256 仍为 `7d85d7fc8abfe56bb75cd87516274800770775d4c416f7e6746a4034f3ff5cb0`。

### 调用、成本、隐私与未解决项

- 兼容阶段两次 live 各 9 次成功逻辑 embedding，共 18 次；连同初次 M0-03 的 7 次，累计 25 次。准确 HTTP transport 尝试数 NOT_MEASURED；usage/token/cost 均为 null。DeepSeek LLM NOT_RUN；五题 Demo 成本 NOT_MEASURED。
- 输入只有两个 synthetic profile；Demo Resume v1 未发送给 embedding 服务。`.env.local` 保持 0600/Git ignored；公开评论、兼容 fork、证据与文档均未包含 API Key 或简历正文。
- 正式 0.1.18 wheel 缺陷仍存在；官方 release 含修复后须切回正式源并重跑 M0-02/M0-03。
- 官方指定 Base Agent/starter/额外约束仍 UNCONFIRMED，M0-BASE 保持 BLOCKED；Evidence/JD Requirement/Candidate State/六 Seed/Planner/Analyzer/Policy/UI 仍 NOT_RUN。
- `tools/validate_spec.py` 本轮 NOT_RUN，历史 28/31 基线冲突未借本任务修改。

### 收尾补记（2026-09-18T18:45-07:00 复核）

- 本轮独立复验：`.venv/bin/python -m pytest tests -q` 复跑 exit 0（50 passed / 1 skipped / 38 warnings, 8.06s）；工作区安静 25 秒以上后文件哈希稳定。
- 完整性基线修复：`CHECKSUMS.sha256` 重建为 74 项，新增 `.gitignore`、`docs/handoffs/2026-09-19-m0-03-del.md`，刷新全部漂移哈希；`sha256sum -c` exit 0，74/74 OK（清单不含自身，沿用既有约定）。AGENTS.md 不在清单内，属负责人授权修改的规范资产，未动。
- §18 与交接中引用的 `knowledge-partial-20260918T172000.json`（旧 BLOCKED 证据）保留不删，历史失败记录按规范并存。

唯一下一建议任务：M0-04 版本锁与 doctor。按阶段停止规则，本轮不自动开始。

## 19. 2026-09-18T19:02—19:20-07:00｜M0-04 版本锁、doctor、干净重装、前端锁与 CI 骨架（VERIFIED）

> 负责人指示"推进 M0-M4"，据此开始并连续施工。VERIFIED 仅指本地真实运行；CI 工作流因仓库未推送远端为 NOT_RUN；不代表负责人 ACCEPTED。

### 交付与实测

- **实测版本锁**：新增 `config/versions.lock.json`，固化 Python 3.11.16 / openjiuwen 0.1.18（兼容 commit `72c49851`）/ pymilvus 2.6.7 / milvus-lite 3.2.1 / uv 0.12.10 / Node v24.21.0 / pnpm 10.34.5。`toolchain/VERSIONS.txt` 与实测一致。
- **doctor**：`scripts/doctor.py` 只读检查 OS/Python/包版本/openJiuwen 安装来源（direct_url commit 比对）/配置存在与 compat-commit 交叉核对/`.env.local` 权限+忽略+键名完整性/runtime 权限/Git 可见文件密钥扫描/toolchain/完整性清单。收尾终态 exit 0：18 pass / 0 warn / 0 fail（中途一次 17 pass / 1 warn，warn 即当时未重建的 process.md 漂移）。密钥扫描覆盖 78→86+ 个 Git 可见文件均 0 命中；输出仅相对路径与计数，守卫测试断言真实密钥值不出现在任何输出中。
- **doctor 守卫**：`services/api/tests/test_doctor.py` 12 项：真实工作区 exit 0 且不泄密、锁缺失 exit 2、植入假密钥必命中且不回显、完整性 hex 不误报、0644 私密文件 FAIL、来源漂移 FAIL、缺 .env.local 为 WARN 非 FAIL、明细无绝对路径、private 目录权限检查。红→绿：首跑因路径深度差一层 collection ERROR，修正后 12 passed。
- **干净环境重装**：`uv venv /tmp/zhijue-clean-m004/.venv --python 3.11` + `UV_PROJECT_ENVIRONMENT=<tmp> uv sync --frozen` 成功安装 184 包；新 venv 内导入 openjiuwen/pymilvus/milvus_lite/fastapi/sqlalchemy/alembic/pypdf/httpx 并构造 `SimpleKnowledgeBase` 入口成功，`direct_url` commit 与锁一致。失败尝试保留：首次用 `--active`，uv 警告 VIRTUAL_ENV 与项目 `.venv` 不匹配并忽略，包仍装进项目 venv，临时 venv `IMPORT_EXIT=1`；改用 `UV_PROJECT_ENVIRONMENT` 后 exit 0。证据：`runtime/evidence/m0-04/clean-reinstall-{sync.log,summary.txt}`。
- **前端锁（非 UI 施工）**：`apps/web` 最小 Vite 7 + React 19 + TS strict 骨架（package.json/tsconfig/vite.config/index.html/main.tsx/App.tsx），真实 `pnpm-lock.yaml`（pnpm 10.34.5 生成，1145 行）。`pnpm install --frozen-lockfile` exit 0；`pnpm build`（tsc --noEmit + vite）exit 0，产物 dist 222.72 kB JS。仅此证明工具链锁定可构建，不含任何业务功能。
- **CI 骨架**：`.github/workflows/ci.yml` 双 job：backend（uv sync --frozen、ruff、pytest、doctor）+ frontend（pnpm 10.34.5 + Node 24 frozen install + build）。不调用任何付费端点；integration_live 由私密 env 门控。YAML 结构经 PyYAML 解析核验。**工作流本身 NOT_RUN（仓库无远端）。**
- **模型网关核验（O04 部分解阻）**：`GET /v1/models` 返回 83 个模型；计划名 `deepseek-flash` 无通道（503 model_not_found），`deepseek-v4-flash` chat 探活 200，`response_format={"type":"json_object"}` 生效且返回完整 usage（prompt 66/completion 33/reasoning 27）。本次登记探针共 2 次 chat 尝试（1 次 503 未计费错误 + 1 次 200）与 1 次 models 列表；这是网关可用性探针，不是业务链路，不计入面试 token/cost。单价格式仍缺，cost 保持 null。
- **回归与卫生**：全量 pytest 62 passed / 1 skipped / 38 warnings exit 0；Ruff check/format `scripts/` 与新测试均 exit 0（修 2 处 subprocess check 参数与 1 处 import 排序）。密钥扫描 0 命中。doctor 首次运行即暴露两处真实缺陷并修复：空仓库下 `git ls-files` 默认输出 0 文件造成假通过（改 `-c -o --exclude-standard`）；`\b` 词边界漏检 `APP_PASSWORD=` 形态（改 `\w*` 前后缀）。

### 修改文件与边界

- 新增：`scripts/doctor.py`、`config/versions.lock.json`、`services/api/tests/test_doctor.py`、`apps/web/`（6 源文件 + pnpm-lock.yaml）、`.github/workflows/ci.yml`。
- 同步：本文件、`CHANGELOG.md`、`README.md`、`docs/07`、`docs/11`、`config/environment.env.example`（仅注释登记核验事实与密钥隔离语义）、`CHECKSUMS.sha256`（86 项终态）、`docs/handoffs/2026-09-19-m0-04.md`。`docs/09` 经核对无本任务变化，未修改。
- 未动：`api.md`（无变化）、业务 Schema/契约/迁移、既有 smoke 与测试、旧证据。无新增 Python 依赖；前端依赖即架构冻结表所列 React/Vite/TS。
- 密钥边界：probe 全程仅用本地 `.env.local` 0600 文件中的既有网关 key；未读取、未打印、未提交任何密钥值；`.env.local` 未新增 MODEL_* 键（正式接线时按 §11.6 契约补齐；是否允许与 embedding 共用同一网关 key 属负责人决定，见 §3 O04）。

### 下一任务

M1-01：业务表模型、Alembic 迁移与 Operations 持久化（docs/03 §7—§8、api.md §1—§3）。按负责人"推进 M0-M4"指示连续施工；M0-BASE/SPEC-ALIGN 保持 BLOCKED 但不阻塞 M1。

## 20. 2026-09-18T19:22—20:15-07:00｜M1-01 业务表模型、迁移与 Operations 持久化（VERIFIED）

> 负责人指示"推进 M0-M4"后连续施工。VERIFIED = 本地 pytest/迁移真库运行；不代表负责人 ACCEPTED。业务写入方仍唯一：只有 SQLAlchemy/迁移路径持有 SQLite，无 Drizzle/前端双写。

### 交付

- **分层骨架**（docs/02 §4—§5）：`services/api/src/zhijue/{domain,adapters/db}`；domain 纯 stdlib（ids/operations），不 import ORM/FastAPI/SDK；pytest `pythonpath=["src"]`。
- **14 表 ORM + 初版迁移** `18e3af0d1942`（Profile/Document/SourceBlock/Claim/ProfileSnapshot/Interview/Question/Answer/Observation/Decision/Assessment/Report/Operation/OperationEvent；P1 的 TrainingMemory 与 ResumeDraft 有意未建表——后者属 M4-02 契约再核）。关键约束：`(operation_id,seq)` 复合主键、`(scope,idempotency_key)` 唯一、Answer.question_id 唯一（一题一份已接受作答，比部分唯一索引更严且 SQLite 友好）、`(interview_id,client_turn_id)` 唯一、`document.profile_id` 等 FK。`created_at/updated_at` 为 RFC3339 UTC 字符串（docs/03 §2）。
- **Alembic env**：URL 优先级 = 调用方注入 > `ZHIJUE_DATABASE_URL` > `runtime/business.db`，alembic.ini 不硬编码可用 URL；`render_as_batch=True`。
- **engine 工厂**：每连接 `PRAGMA foreign_keys=ON` + `busy_timeout`（默认 5000ms），WAL 显式开关。
- **OperationRepository**：`accept`（幂等：同 key 同 hash 返回原操作/不同 hash 抛 IdempotencyConflict/并发输家撞唯一键后新事务重查返回赢家行，不吞非竞争异常）、`transition`（纯 domain 状态机守卫；RUNNING 进入时 attempts+1）、`append_event`（写入前 jsonschema 校验 `contracts/operation-event.schema.json` 对应分支；终态后拒绝；seq 取 `last_event_seq+1` 单事务原子推进）、`retry`（仅 failed/interrupted；新行 + parent 链接 + attempts 继承，预算不清零）、`mark_interrupted_on_restart`（running→interrupted，queued 仅列出不动作）。

### 实际测试（全部本地真实运行）

- 红→绿链：domain 测试首跑 collection exit 2（无包）→ 实现后 8 passed；仓储测试首跑 exit 2（无仓储）→ 13 项断言逐条修复；迁移测试首跑暴露 `env.py` 无条件覆盖调用方 URL 的真缺陷（会把测试打向真实库！修为优先级链）→ 逐步定位 SQLAlchemy 单事务混合表插入顺序触发 FK（测试改按 `sorted_tables` 拓扑 flush）→ `alembic_version` 保留为预期行为。
- **并发红线（M1-01 通过条件）**：4 线程 Barrier 同时 accept 同 key 命令，首版实现把输家的 IntegrityError 抛给调用方 — 真实缺陷被测试抓住。修复：唯一键冲突 → 新事务重查 → 同输入返回赢家 operation_id；10 连跑全绿，2 行/库（两个 scope 各一），无半行。双 claim queued→running：attempts 恰好 1。
- 迁移可逆：upgrade 建 14 表 → downgrade base 仅剩 `alembic_version` → 再 upgrade 成功；`compare_metadata` 零漂移。
- 全量回归：**93 passed / 1 skipped / 0 failed / 38 warnings**，`runtime/evidence/m1-01/pytest-final.log`；Ruff check + format --check（src/tests/migrations）exit 0。
- 手工验证产生的 `runtime/business.db` 与错位 `services/api/runtime/` 空目录已删除；未 commit/push（基线仍 NO_COMMITS）。

### 修改与未动

- 新增：`services/api/src/zhijue/`（domain ids/operations + adapters/db engine/models/operations）、`migrations/`（env + 18e3af0d1942）、`alembic.ini`、`tests/unit/`（4 文件 41 用例）、`runtime/evidence/m1-01/`。
- 修改：`pyproject.toml`（pythonpath）、本文件、CHANGELOG、README、docs/07、CHECKSUMS、handoff `2026-09-19-m1-01.md`。
- 未动：`api.md`（无 HTTP 实现，契约不变）、业务 Schema/contracts、smoke、前端、旧证据。无新增依赖（sqlalchemy/alembic/jsonschema/pytest 已在锁内）。
- 模型调用：本轮 0 次；token/cost null。

### 遗留与下一任务

- Operation 行与业务资源间暂不做 FK 约束（resource_id 指向多类型，属应用层不变量；HTTP 层接入时补校验）。
- 下一任务 **M1-02**：pypdf 按页提取 → SourceBlock、requires_text/加密/超限受控失败（T02/T04）、原件 hash 追溯；允许本地使用 Demo Resume v1 私有样本，不外发不入 Git。

## 21. 2026-09-18T20:15—20:42-07:00｜M1-02 PDF/文本导入与 SourceBlock 定位（VERIFIED）

> 负责人"推进 M0-M4"连续施工。VERIFIED = 本地 pytest/真实私有 PDF 导入；不代表负责人 ACCEPTED。无网络、无模型调用（0 次，token/cost null）。

### 交付

- **合成 PDF fixture**（`tests/fixtures_pdf.py`）：手工构造最小合法 PDF；文本经 ToUnicode CMap（hex bfchar）还原，中文/ASCII 在锁定 pypdf 6.19.0 上实测正确（首版直接写 UTF-8 字节进 literal 产生 mojibake，被测试当场抓住）。空串页 = 无文字层页模拟扫描件；`encrypt_pdf` 用非空 user 口令（首版空 user 口令导致加密文档仍可读，被红测抓住后修正）。
- **domain**：`errors.DocumentRejected(code, message, retry_hint)` dataclass 异常；`extraction.PageText/ExtractionLimits/decide_status` 纯函数（全空页→requires_text+粘贴文案；部分空→parsed+缺页警告；空页永不静默删除）。
- **adapters/pdf**：`sniff_kind` 按魔数/UTF-8 判型（不信任文件名）；`extract_pdf_pages` 加密→`DOCUMENT_ENCRYPTED/paste_text`（api.md §4 不索取密码）、页数/字符超限、损坏→`DOCUMENT_UNREADABLE`；单页解码异常按缺文字层处理并保留页结构。`extract_text_pages` UTF-8 单块 page=None。
- **adapters/db/documents**：Document+全部 SourceBlock 单事务（失败不留半套）；SourceBlock 无 UPDATE 方法（不可变，docs/03 §5）；`(page null→0, block_index)` 稳定排序；base64 偏移游标 + limit 1—100（api.md §4）。
- **application/documents**：kind 白名单→字节超限 `FILE_TOO_LARGE`（校验先于任何写入）→档案文档数 `DOCUMENT_LIMIT`→profile 存在性→sniff→提取→状态决策→落库。

### 实际测试

- 红→绿：collection exit 2（无实现）→14 项全过；两处真实缺陷由红测抓住（mojibake fixture、空口令加密仍可读）；修 documents.py 时一次编辑错位，整文件重写恢复。
- **全量回归 107 passed / 1 skipped / 38 warnings，exit 0**；Ruff check + format --check（src/tests 25 文件）exit 0（4 处自动修复均为 lint 卫生，未删断言）。
- **真实导入（私有本地，非网络）**：DEMO-INPUT-01 的显式私有文件经 DocumentService 导入并与 ignored 接收登记一致；`extract_status=parsed`、warnings 空。原件、文件名、身份信息、指纹和正文均未写入公开证据；业务库为临时文件且已销毁。
- 边界声明：这只是导入与定位闭环，**不是** Evidence 抽取、不是能力验证、不算 T05 双栏/OCR（P1）、不算 M1-03 确认快照与 Knowledge 激活。

### 修改与未动

- 新增：`domain/{errors,extraction}.py`、`adapters/pdf.py`、`adapters/db/documents.py`、`application/__init__.py`、`application/documents.py`、`tests/{fixtures_pdf.py,unit/test_document_import.py}`、`runtime/evidence/m1-02/`。
- 修改：本文件、CHANGELOG、README、docs/07、CHECKSUMS、`docs/handoffs/2026-09-19-m1-02.md`。
- 未动：`api.md`（无 HTTP 层变化）、contracts/、migrations（14 表已够用，Document/SourceBlock 无新列）、smoke、前端、旧证据。无新依赖（pypdf 已在锁内）。
- 遗留：text/plain 上传暂存内存 bytes（HTTP 流式落盘属接口层施工时决定）；Knowledge 激活与确认快照 = M1-03。

### 下一任务

M1-03：声明确认与 ProfileSnapshot + Knowledge 激活（P-EXTRACT 提议 Claim 的业务 live 接线在 M2+；确认/快照/索引激活链路先行 fixture 级实现与测试）。

## 22. 2026-09-18T20:45—21:20-07:00｜M1-03 声明确认、不可变快照与 Knowledge 激活（VERIFIED）

> 本地 fixture 级 + 真实 openJiuwen live 激活。VERIFIED = 测试与 live 回执通过；不代表负责人 ACCEPTED。LLM 调用 0 次（P-EXTRACT 未接线）；embedding 调用属激活链，见证据。

### 交付（第二批：卡面缺口的 HTTP 与界面）

上一轮我把 M1-03 标 VERIFIED 时**缩了范围**：`docs/12` 的卡面交付是"确认 API、索引激活、确认界面"三件，当时只做了索引激活与服务层确认。本轮补齐，并按下述真实缺陷修根因：

- **HTTP 服务**（`src/zhijue/api/`：`app.py`/`routes.py`/`events.py`/`errors.py`/`schemas.py`）：统一包封与契约错误映射；乐观 revision 409 带 `current_revision`；202 受理 + 后台 operation（`operation.started`→`operation.completed`/`operation.failed` 持久化事件）；SSE 事件流（重放、心跳、终态关闭、游标冲突 400）；`/health/live|ready`（live 缺配置 503 not_ready，不回退 fixture）；multipart 上传 + `/documents/{id}` + `/blocks`。构造收敛在 `build_services`（唯一 Engine/仓储/服务组合），`create_app` 只装配。
- **前台接口**（`src/zhijue/__main__.py`）+ **Makefile**：只登记真实目标（doctor/check/lint/test/test-live/api/web），`docs/11-runbook.md` 的 `make dev` 不再是空话。
- **最小确认界面**（`apps/web/src/{api.ts,App.tsx}`）：真实浏览器跑通；显示"材料中声明"与"已由你确认"的区别、快照 ID、索引状态；错误直接显示契约码，不假成功。
- **提取器注入**：`DocumentService` 的 pdf/text 提取改为构造期注入，测试可替换而不复制业务逻辑。

### 真机缺陷修复（测试/真机发现，非放宽标准）

1. `append_event` 拒绝在终态后追加事件，而 runner 先转终态再写终态事件 → 必然抛 "events closed"。修：终态事件先写、状态后转（顺序即不变量）。
2. 后台任务异常逃逸到已发出的 ASGI 响应（`RuntimeError: Caught handled exception, but response already started`）。修：runner 边界兜住并落 `operation.failed`；连登记都失败则 critical 留痕且不伪造成功。
3. 运行目录不存在时启动即 `unable to open database file`。修：`AppConfig.ensure_directories()` 启动前自建（真机冒烟时我手工建过目录，掩盖了该缺陷；已加回归测试）。
4. `sniff_kind` 只按魔数判定，非 UTF-8 文本未拒绝。修：文本类型补 UTF-8 校验。
5. 前端 `tsconfig` lib 为 ES2022，`Promise.withResolvers` 编译失败 → 提到 ES2024（Node 24 + 现代浏览器目标）。

### 交付（第一批：domain/服务/适配器）

- **domain/claims.py**：`ClaimStatus` 状态机（proposed→confirmed/disputed/retracted；confirmed→retracted；disputed→confirmed/retracted；retracted 终态）与 `validate_exact_quote`（引文必须是来源块子串，AGENTS §2）。
- **adapters/db/profiles.py**：`ProfileRepository`——乐观 `expected_revision`（不一致 `REVISION_CONFLICT`，HTTP 映射 409）、`add_facts`（Document+Block+Claim 单事务并 revision+1）、`confirm`（裁决+快照单事务）、`get_snapshot`、`documents_for_blocks`、`set_index_status`；`ProfileSnapshot` 无任何 UPDATE 方法（不可变由结构保证）。
- **application/profiles.py**：`ProfileService`——校验先于写入（section 白名单、单条 2,000/单次 50 条/合计 30,000 与 api.md §4 一致，失败不推进 revision）；`KnowledgeGateway` 端口 + `activate_knowledge`（indexing→ready/failed，异常必落 failed 再抛）；`snapshot_source_ids` 检索 allowlist；`search_knowledge` 只返回当前快照允许的来源。
- **adapters/knowledge.py**：Knowledge 构造唯一权威（`KnowledgeSettings`/`build_embedding`/`build_knowledge_base`/`SDK_COMPONENTS`）+ `OpenJiuwenKnowledgeGateway`（按 profile 一个 KB、按快照一代文档；写入后用来源文本回查做**索引回执校验**，ID 不一致或回查不到即失败）。`smoke/knowledge.py` 改为复用该权威（探针与应用同一套组件，杜绝两套构造）。
- 语义边界：手填/更正事实没有上传文件，因此每批次生成 `kind=user_input` 的 Document 承载其块（origin=user_input），保持"块必属于文档"外键不变量；更正是**新块+新 Claim（supersedes）**，不篡改原 PDF 来源（docs/03 §5.3）。

### 实际测试

- 单元：`tests/unit/test_profile_confirm.py` 8 passed；`tests/unit/test_knowledge_activation.py` 4 passed + 1 live（默认 skip）；`tests/test_api_contract.py` **22 passed**（含 SSE 与上传）。
- **全量回归 141 passed / 2 skipped / 0 failed / 39 warnings，exit 0**（`runtime/evidence/m1-03/pytest-final.log`）；Ruff check + format --check 全绿（smoke/src/tests 34 文件）。
- **真实 live 激活**（显式私有 env）：`index_status=ready`、来源 ID 与快照绑定、回查命中标记词、`generation` 一致；3 次逻辑 embedding 调用、1024 维、token/cost null（SDK 不暴露）。证据 `runtime/evidence/m1-03/activation-live-summary.json` 与 `activation-live-2-*.log`；`tests/unit/test_knowledge_activation.py -m integration_live` 1 passed。
- 失败保留：① live 首次 `RuntimeError: Event loop is closed`——网关 HTTP 连接池绑定创建它的 loop，测试跨 `asyncio.run` 复用所致；改为**单 loop 驱动整条链**（与 uvicorn 单循环一致）后通过，代码未加任何兜底。② `smoke/knowledge.py` 剥离重复构造后 `urlsplit`/`TxtMdParser` 等引用断裂，被既有 16 项守卫测试当场抓住并修复。
- live 检索隔离：单元层验证"第一代快照检索不到第二代来源"；真实层的跨代隔离在 M2-02 接 JD/五题后复用同一 allowlist 再测。
- **真机 HTTP 闭环（live 单进程 uvicorn）**：新建档案→手填事实→confirm 202→operation `succeeded`→`index_status=ready`、revision 0→1→2；幂等重放返回同一 operation 且 revision 不再推进；私有 Demo Resume v1 经 multipart 上传并与 ignored 接收登记一致，`parsed`；过期 revision 返回 409 + `current_revision`。去敏证据保存在 ignored runtime。
- **真实浏览器闭环（live）**：Chromium 打开前端确认界面，`live / configured` readiness、新建档案、提交事实（索引 `pending`）→ 点击确认 → `succeeded` → 索引 `ready`；截图 `runtime/evidence/m1-03/ui-confirm-flow.png`。
- 前端构建：`tsc --noEmit && vite build` 通过（dist 产物）；`contracts/openapi.json` 由 FastAPI 导出（api.md §10 要求）。

### 修改与未动

- 新增：`domain/claims.py`、`adapters/knowledge.py`、`adapters/db/profiles.py`、`application/{profiles,operations_runner}.py`、`api/{app,routes,events,errors,schemas}.py`、`__main__.py`、`tests/unit/{test_profile_confirm,test_knowledge_activation}.py`、`tests/test_api_contract.py`、`contracts/openapi.json`、`Makefile`、`apps/web/src/{api.ts,App.tsx}`、`runtime/evidence/m1-03/`。
- 修改：`smoke/knowledge.py`（设置类继承生产契约、SDK 组件清单共用、删除重复构造）、`adapters/db/{documents,profiles}.py`（list_documents/documents_for_blocks/set_index_status）、`application/documents.py`（提取器注入、list_documents/get_document）、`adapters/pdf.py`（文本 UTF-8 校验）、`apps/web/tsconfig.json`（lib ES2024）、`config/environment.env.example`（`ZHIJUE_EMBEDDING_ENV_FILE`）、`api.md`（补实现状态，无契约变更）、docs/11、process/CHANGELOG/README/docs/07/CHECKSUMS、`docs/handoffs/2026-09-19-m1-03.md`；`tools/validate_spec.py`（扫描边界与两条过期断言，见 §2 注与 §8 修复记录）、`validation-report.md`（重写）。
- 契约：`api.md` **无契约字段变更**，只补了实现状态说明；新增 `contracts/openapi.json` 为 FastAPI 导出（非手写第二份真源）。migrations 无新列（14 表已能表达 Claim/快照）。
- 未动：面试/报告/简历草稿/DELETE/retry/runtime-info 路径（仍 PLANNED）、旧证据、旧 Next.js 代码。无新第三方依赖（FastAPI/uvicorn/python-multipart 已在锁内）。
- 遗留：`index_status` 记在 Document 上（快照激活态随其来源文档体现）；`/documents` 上传只落材料不产 Claim（自动提议属 M2+）；上传的解析在后台线程内完成，未做 multipart 流式落盘（10 MiB 上限内可接受，接口层需要时再议）；跨进程重启后的索引检索复用 M0-03 结论，未重跑多进程；浏览器验证为手动脚本，未固化为 E2E 用例。

### 下一任务

M2-01：先做 Seed 契约对齐（SPEC-ALIGN），再落 6 条可审核 Seed（两级审核，未获确认只能 draft/reviewed）。

## 23. 2026-09-18T21:45—22:30-07:00｜M2-01 契约对齐与六条可审核种子（IMPLEMENTED）

> 状态为 IMPLEMENTED，不是 VERIFIED：Level 2 技术审核未完成、负责人未确认，按 AGENTS §11.5 不得写 approved，也不得宣称规范已完全一致。无 LLM 调用。

### SPEC-ALIGN 的闭合方式（ADR-013）

三处真实冲突与处理：

| 冲突 | 处理 | 反例说明 |
|---|---|---|
| CHALLENGE 不在 P0 动作集 | **保持四动作**，语义落在 `PROBE + followup_intent=counterfactual`；docs/04 §5 补正式说明。未静默扩枚举 | 不采用"枚举里预留但不启用"（会把特例伪装成通用能力） |
| Seed 缺 reference points / red flags / follow-up strategy | Schema **新增显式字段**并设为必填；`technical` 要点必须带非空 `reference_ids`；`red_flag.requires_followup` 结构上恒为 true；`follow_up_strategy.max_followups ≤ 1` | 不采用"把 reference points 塞进 prerequisites、red flags 塞进 out_of_scope"（语义混用=最小修复） |
| 单级 `review_status` 与两级审核不对应 | 保留枚举，新增 `review_levels`；`approved` 必须两级 passed 且有 review_record_id；`technical_review` 必须 Level 1 passed；不另立 `reviewed` 值 | 不采用"同时存在 reviewed 与 technical_review"两套并行语义 |

### 交付

- `contracts/seed.schema.json`：新增 `reference_points`/`red_flags`/`follow_up_strategy`/`review_levels`（必填）+ 条件约束；三条既有示例同步更新。
- `data/seeds/`：六条种子，覆盖 6 个能力维度、5 种 archetype（queue/period/mutex/uart_dma/spi_i2c/interrupt），全部 `technical_review`（Level 1 自检通过、Level 2 pending）。
- `docs/seeds-review-m2-01.md`：两级审核表（可读视图 + 逐条 Level 2 核对入口）。
- `docs/14-sources-and-rules.md`：新增 S24（FreeRTOS 官方参考手册 V10.0.0）、S25（FreeRTOS 文档站入口）、S26（ST RM0433 Rev 8）、S27（ST AN4031），并给出 `reference_id → S编号` 映射表。
- `zhijue/application/seed_bank.py`：种子加载/校验/live 门槛/版本指纹；缺文件、空目录、坏契约、无达标种子一律显式失败（不把"读不到"当成空题库继续跑）。

### 来源核验方式（不靠模型记忆）

- FreeRTOS：下载官方参考手册 PDF，读到版次（V10.0.0 issue 1，© 2017 Amazon）与章节结构（Ch2 任务/调度、Ch3 Queue、Ch4 Semaphore、Ch7 Kernel Configuration），核对到具体小节号。
- ST：下载 RM0433 Rev 8（40,711,860 字节）并提取正文，实测确认第 15/19/47/48/50/56 章与 19.1（150 通道、16 级优先级）、47.4（100k/400k/1M）、48.5.6/48.5.19、48.7、50.4、56.4（ISO 11898-1:2015、11/29 位标识符）真实存在；页码为手册页码。
- 边界如实登记：RM0433 **只覆盖 STM32H7 系列**；S27 仅确认可下载、未提取正文，因此不作为任何 reference_point 依据；FreeRTOS 在线文档站为客户端渲染，本机只取到标题，故正文细节引用手册版次（S24）。

### 实际测试

- `tools/validate_spec.py`：**37/37 通过**（新增 5 条 Schema 负例 + 1 条种子可追溯性检查）。
- 负向自检：把某条种子的 `reference_ids` 改为不存在的 id 后，校验器 exit 1 并报 `FAIL 种子引用可追溯`——证明该检查不是空断言。
- `tests/unit/test_seed_bank.py`：8 passed（含"全部降级 draft 时 live 加载必须失败"）。
- 全量回归：**149 passed / 2 skipped / 0 failed**；Ruff check + format 全绿。

### 未做与待负责人

- **Level 2 技术审核未做**：需要负责人或独立复核者依据 S24/S26 逐条核对 reference points；在此之前 `review_status` 只能 `technical_review`。
- 未扩到 24 条（AGENTS §11.4：闭环通过前不得批量造题）。
- ADR-013 状态为 PROPOSED，未标记 ACCEPTED。
- 未新增第三方依赖；未调用 LLM；`api.md` 无变化。

### 下一任务

M2-02：JD 输入（正式 JD 未到时用 `SYNTHETIC_DEMO_JD` 并持久化来源状态）、能力覆盖计划与五题计划生成。

## 24. 2026-09-18T22:35-07:00｜仓库落盘（本地提交）

- **提交**：`7ac1b7f`（首个提交；此前 master 无任何 commit，全部文件为 untracked）。
- **内容**：145 文件 / 24,354 行，涵盖规范包、契约、示例、环境锁、M0 探针、M1 业务资料链与 HTTP/最小界面、M2-01 种子与 ADR-013。
- **未包含**（`.gitignore` 已逐项验证）：`runtime/`（113 MB，含私有原件与业务库）、`logs/`、`.env*`（真实密钥只在 `.env.local`，0600，未入库）、`toolchain/`（Node 发行包）、`node_modules/`、`.venv/`、`dist/`。
- **提交前检查**：① `git status --porcelain -uall` 逐条确认 145 项无 runtime/private/env；② 全仓扫描 `sk-*`/`Bearer` 形态密钥，唯一命中位于 **ignored** 的 `.env.local`；③ `config/environment.env.example` 的 `API_KEY`/`EMBEDDING_API_KEY` 确为空；④ 大小写冲突检查 0 命中；⑤ 门禁：doctor 18 pass、`pytest` 149 passed、`validate_spec` 37/37、`sha256sum -c` 144/144。
- **提交信息修正留痕**：首次提交信息误写为"仅规范包"，与实际内容不符，随即 `--amend` 改为如实描述（未 push，无历史污染）。
- **未做**：没有 push（无远端）；没有在提交信息里声称任何未完成的审核或验收；`--amend` 只用于修正本轮的初始提交，未改写更早历史（不存在更早历史）。
- **回滚**：提交本身即回滚点；`git reset --soft` 可退回未提交状态（本轮未使用，亦不推荐在有后续提交后使用）。

## 25. 2026-09-18T23:45-07:00｜M2-02 JD 来源持久化、Requirement 抽取与五题计划生成（VERIFIED）

> 状态为 VERIFIED：在真实 openJiuwen Knowledge + Milvus Lite + SQLite 驱动下，使用私有 Demo Resume v1 与显式标记的 `SYNTHETIC_DEMO_JD` 完成端到端闭环。私有输入指纹和运行存证只保存在 ignored runtime，不随公开仓库发布；不存在可核验企业原公告，因此不再宣称 `REAL_JD_DERIVED`。

### 核心设计与事实性/溯源闭环（M2-02 Closure）

1. **P0 事实性核查：DMA 双缓冲溯源与根除**：
   - 排查确认：`runtime/evidence/m2-02/` 生产存证中绝对不含"双缓冲"；该词来自早期单元测试用例中的 mock 文本，在上一轮人工汇报摘要中不慎残留。
   - 根因闭合：清理单元测试 fixture，新增负向回归测试 `test_negative_regression_ungrounded_fact_rejected`，强制校验 Candidate Claim 必须逐字符属于 SourceBlock；任何擅自扩写的"双缓冲"均被校验器抛出 `ValueError` 彻底拒绝。
2. **P0 中断 Evidence Mapping 纠偏与 EvidenceRelation 体系**：
   - 本地私有证据审查将中断维度保持为 `unknown`，未把 TIM、输入捕获或状态机自动升级成中断直接证据；具体原文和身份信息不进入公开仓库。
   - 建立四级 `EvidenceRelation` 架构：`DIRECT_CLAIM`、`DIRECT_EXPERIENCE`、`RELATED_CONTEXT`、`MODEL_INFERENCE`；
   - 强制不变量：只有直接声明/经历才能赋予 `unverified/claimed` 状态；`RELATED_CONTEXT`（如 TIM/输入捕获）**严禁把 unknown 升级为 unverified**，只能作为 Planner 的信息价值信号。在 Coverage Map 中 `embedded.mcu.interrupt` 严格保持 `status=unknown`、`relation=related_context`、`evidence_ids=[]`。
3. **JD 来源真实性与强制不变量**：
   - 审查发现此前 `demo-jd-v2.md` 使用不可验证的示例域名并写入未经记录的 `confirmed_by`，该工件已删除，相关真实来源宣称已撤回；
   - `POST /interviews` 不再接受客户端自报 `jd_source_type`：无 `jd_text` 时固定加载 `data/jd/preset_embedded_junior.txt` 并标记 `synthetic_demo_jd`；有 `jd_text` 时固定为 `user_provided`；
   - `real_jd_derived` 仅允许受信任内部路径创建，必须同时提供可验证公网 URL、抓取时间、上游 hash、派生工件 hash 与转换说明；本地路径、示例域名或缺字段直接 `JD_PROVENANCE_INVALID`。
4. **Planner 多维度业务优先级（彻底消除单纯字母序 tie）**：
   - 彻底废除仅输出 32 同分依赖字典序的缺陷；优先级公式考量四重业务要素：
     `priority = 岗位重要度(10/20/30) + 验证需求与证据关系分值(2-8) + JD需求覆盖密度(0-6) + 证据丰富度(0-3)`；
   - 产出具有明确业务梯度与区分度的分值：UART/DMA(41) > 软硬件验证(40) > Git(40) > C语言基础(38) > 中断(38，unknown+related_context 高信息价值) > RTOS(31，加分项) > ownership(19，背景项)；
   - 字典序仅作为底层完全并列时的唯一稳定兜底。
5. **Demo Critical Fact Checklist 客观召回率**：
   - 废除无法证伪的主观绝对表述，改为客观可测量的 8 项检查集（STM32、UART错帧排查、FreeRTOS、Queue、CAN、Git、主要负责人、Linux学习边界）；
   - 实测召回率：**8/8（100.0%）**。

### 真实测试与 Live 闭环证据

- **真实 Demo 端到端闭环**（`services/api/smoke/m2_02_live_verification.py`）：
  - 输入：由操作者通过显式环境变量提供的私有 Demo Resume v1；仓库不保存工作站路径、文件名或指纹；
  - 解析：pypdf 文字层非空，通过 `POST /documents` 落库并生成完整 `SourceBlock`；
  - 抽取：提取 21 条结构化事实，逐字符回指私有原文；
  - 确认与索引：写入 proposed claims 并通过 `POST /confirm` 确认；真实 openJiuwen Knowledge 完成 21 块切片与 BAAI/bge-m3 向量化入库；
  - JD 规划：由服务端加载 `data/jd/preset_embedded_junior.txt`，来源为 `synthetic_demo_jd`、`is_synthetic=true`、`derived=false`、所有 URL 为空，抽取 8 条 Requirement；
  - Coverage Map：UART/DMA、ownership、RTOS、verification 证据链完整；中断严格为 `unknown + related_context`（evidence_ids 为空）；
  - 五题规划：生成 5 个槽位（验证 priority=40, UART/DMA=39, ownership=39, 中断=38, C基础=37），`seed_id=None`，无题目文本；
  - 存证：去敏结果位于 ignored `runtime/evidence/m2-02/`，不随公开仓库发布。
- **单元与集成测试**：`tests/unit/test_planning.py` 27 passed；全量 pytest **182 passed / 2 skipped / 0 failed / 39 warnings**，耗时 11.06s。
- **规范校验**：`tools/validate_spec.py` **43/43 passed**。
- **环境与代码质量**：`ruff check` 与 `ruff format --check` 全绿；`scripts/doctor.py` **18 pass / 0 warn / 0 fail**。
### 下一门槛

六条 Seed 的 Level 2 仍待负责人/独立复核者；在通过并明确批准前，M3-01 可以准备纯函数 Analyzer/Policy，但不得进入 live question、不得绑定 `technical_review` Seed。

## 26. 2026-09-19T02:27-07:00｜M2-03 面试准备工作台（VERIFIED）

- **界面范围**：复用 M1 资料确认页面，新增 InterviewView 类型与 `POST/GET /interviews` 客户端；展示已确认资料快照、JD 来源、8 条 Requirement 数量、Coverage Map、5 个验证槽位及首题准备态。
- **事实边界**：synthetic JD 显著显示“不是企业真实招聘公告”；`unknown` 明示“材料未体现，不等于不会”；`related_context` 与直接证据数量分开展示。
- **审核门禁**：所有 Slot 的 `seed_id` 仍为 null；页面明确显示“首题尚未生成”，没有回答框、没有 `/start` 调用、没有 LLM 调用。
- **真实浏览器验证**：在 live API、SQLite、Milvus Lite 与 Vite 代理下打开真实 Profile `profile_927acd8aa5b42614e0d7`；点击“生成五题验证计划”，Operation `operation_a5690d32777560d56c06` succeeded，新 Interview `interview_46d8ee8bc76efccb75df` 返回 5 Slots；URL 写入 profile/interview，刷新后仍恢复 synthetic 来源警示、5 Slots 与首题审核门禁。
- **视觉证据**：`runtime/evidence/m2-03/workbench-live-final.png`；无真实简历正文、密钥或绝对服务器路径。
- **构建与回归**：固定 Node 24 执行 TypeScript `--noEmit` 与 Vite build 通过（29 modules，JS 233.38 kB / gzip 73.91 kB）；后端 pytest 182 passed / 2 skipped；ruff、规范校验均通过。
- **API 变化**：`POST /interviews` 删除不可信的客户端 `jd_source_type`；默认预置为 synthetic，用户文本为 user_provided；`InterviewView.jd_source` 返回完整来源字段。无数据库迁移。
- **下一门槛**：完成 M2-01 Level 2 审核与负责人批准；不得由施工 Agent 自行写 approved。阶段到此停止，不自动进入 M3。

## 27. 2026-09-19｜M2-01 Level 2 官方来源审核准备（READY_FOR_OWNER_REVIEW）

### 实际完成

- 下载并提取五份官方 PDF：FreeRTOS V10.0.0 issue 1、PM0214 Rev 10、RM0090 Rev 22、RM0440 Rev 9、RM0433 Rev 8；URL、字节数、SHA-256、正文定位和六条 Seed finding 记录于 `runtime/evidence/m2-01-level2/source-manifest.json`。
- 逐条核对六条 Seed：Queue 改为手册实际的固定 item-size 复制语义并补 `FromISR` 边界；period 的 tick 分辨率改为带 S24 的技术要点；mutex 删除 S24 未出现的 `"lessen/minimize"` 归因，保留已明确的继承行为、配置和 queue set 边界。
- UART/DMA 与 SPI/I2C 补齐 F4/RM0090、G4/RM0440、H7/RM0433；位名、DMA 映射、错误清除和 I2C 速率按系列隔离。F4 手册列 100/400 kHz，G4/H7 另列 1 MHz，不再把 H7 事实外推到主演示 F407/G431。
- 修复审核门禁根因：`SeedBank` 文档声称遵循 `config/demo.yaml`，旧实现却硬编码 `technical_review` 即 live eligible，且 `live_only=True` 会返回未批准条目。现加载权威配置 `approved` 门槛；无 approved 时显式失败，混合库只返回 approved Seed。
- 六条 Seed 内容版本统一更新为 `0.2.0`；正式审核状态仍为 `technical_review` / Level 2 `pending`。施工 Agent 未写 `passed`、未建 `review_record_id`、未写 `approved`、未扩到 24 条。

### 实际验证

- 官方 PDF SHA-256 复核：5/5 与 manifest 一致。
- `tests/unit/test_seed_bank.py`：12 passed，覆盖 F4/G4/H7 来源、technical_review/draft live 拒绝、approved-only 过滤和版本指纹。
- 后端全量 pytest：186 passed / 2 skipped / 0 failed / 39 warnings（最终复跑 13.96s）。
- `tools/validate_spec.py`：44/44 passed；新增平台来源闭合守卫。
- 标准 Ruff 范围 `src tests smoke`：check 与 format-check 全绿。
- SeedBank 本地 smoke：6 条加载成功，指纹 `865acb58c66a8777`，权威 live 门槛 `approved`，当前 live eligible 数量 0。第一次调用漏传 `PYTHONPATH=src` 因 `ModuleNotFoundError` 退出 1；补正确运行环境后通过，没有向业务代码加导入兜底。
- `scripts/doctor.py`：18 pass / 0 warn / 0 fail；`CHECKSUMS.sha256` 终态覆盖 157 个文件并逐项通过。

### 边界与下一步

- API、DTO、SSE、数据库、迁移、前端、依赖和 `contracts/seed.schema.json` 无变化；`api.md` 已检查无需修改。
- LLM/embedding 调用 0；provider/model/prompt/token/cost 均为 null；没有把本地文档审核冒充模型或业务 live。
- 负责人或指定独立复核者下一步逐条审阅 `docs/level2-review-packet-m2-01.md` 并明确 `passed/failed`。只有 Level 2 通过、建立可追溯 `review_record_id` 且负责人明确批准后，才能改为 `approved` 并进入 M3-01 live question。

## 28. 2026-09-19｜M2-01 Level 2 负责人批准（VERIFIED）

- **负责人决策**：在当前会话中明确选择“六条全部通过并批准”。统一审核记录 `docs/reviews/review_m2_01_level2_owner_20260919.md`，`review_record_id=review_m2_01_level2_owner_20260919`。
- **状态转换**：六条 `review_levels.level2` 均写入 `passed / owner / checked / 2026-09-19`，`review_status=approved`，版本由 0.2.0 升到 0.2.1；批准后未改写题干、reference points、red flags、rubric 或平台边界。
- **门禁实测**：`load_seed_bank(..., live_only=True)` 返回 6 条 approved Seed，门槛来自 `config/demo.yaml=approved`；批准后指纹 `1c6716b90449d375`。降级 technical_review/draft 和混合库过滤由专项测试持续覆盖。
- **验证**：Seed 专项 12 passed；全量 pytest 186 passed / 2 skipped / 39 warnings（11.11s）；规范 44/44；Ruff check/format-check 全绿；doctor 18 pass / 0 warn / 0 fail；完整性 159/159。规范校验曾因错误脚本路径和系统 Python 缺少 PyYAML 各失败一次，改用项目解释器后通过，未修改业务代码兜底。
- **边界**：批准只覆盖首批六条，不授权扩到 24 条；M3 Analyzer/Policy、live question、回答链、评分与业务 LLM 仍 NOT_RUN。API、DTO、SSE、数据库、迁移、前端、依赖、Seed Schema 与配置值无变化。
- **下一任务**：M3-01 Analyzer/Policy。按阶段规则本轮只完成批准记录与回归，不自动开工下一阶段。

## 29. 2026-09-19T06:02:16-07:00｜M3-01 回答分析/Policy（IMPLEMENTED）+ M3-02 后端可靠性（VERIFIED）

> M3-01 的代码、真实 openJiuwen Workflow 与 fixture 业务闭环已通过，但外部文本模型 live 因缺显式私密配置为 `NOT_RUN`，故不写 VERIFIED。M3-02 的本地持久化、幂等、事件、retry 和恢复链已验证。未开始前端答题界面设计。

### 交付与设计边界

- 五个冻结 slot 在 start operation 内实例化为 Question。approved Seed 只做精确 competency 匹配；唯一显式族映射为 `embedded.rtos.fundamentals → embedded.rtos.*`；同场不重复。缺 Seed 时生成 `seed_id=null` 的经历/证据边界题，不伪造技术审核来源。
- 回答分析使用项目锁定 openJiuwen 的真实 Workflow：`Start → Analyzer → SemanticValidation → DeterministicPolicy → End`。Analyzer 只能返回不可信 Observation 候选；服务端强校验 answer/question/root/criterion ID、冻结 kind/weight、回答原文精确子串和已审核 reference。Policy 只产生 `CLARIFY / PROBE / NEXT / END`，每个 root 最多一次 follow-up；PROBE 按选中 criterion 与冻结 Rubric 合格阈值确定性生成聚焦文案，不额外调模型、不显示内部 ID；red flag 只触发追问，不直接扣分。
- Answer、Operation、Interview revision 和 `active_operation_id` 在同一 SQLite 短事务受理；单进程的 start/answer/retry 受理共用短临界区锁，并发相同 idempotency key / `client_turn_id` 只生成一份 Answer/Operation。分析期间不持有锁或写事务；Observation、Decision、下一题/finishing 状态和 durable event 在成功事务提交。
- 失败保留原始 Answer 并显式标 failed；retry 新建 parent-linked operation、复用同一 Answer，父子累计最多三次 transport/business attempt。启动恢复把遗留 running 标 interrupted 并释放 Interview，不静默重放可能已计费的上游调用。
- 隐私收紧：业务启动把 SDK 日志提升到 WARNING 并去掉文件 sink；operation 失败 API 只写固定公开文案，日志只记异常类型。模型配置只允许显式私密 env 文件且权限不得宽于 0600，不读取 ambient environment；API base 限 HTTPS origin。
- API 变化：新增 `POST /interviews/{id}/start`、`POST /interviews/{id}/answers`、`POST /operations/{id}/retry`，扩充 Interview/Operation 视图和 OpenAPI 快照。数据库迁移 `2c8f1d7a90b4` 新增 Answer→accepted Operation 唯一外键并允许 Question.seed_id 为空。闭环复核时同步了前端网络类型和只读状态文案，但没有开始答题界面设计；第三方依赖未改。

### 修改路径

- 领域/应用：`domain/{questions,interview_policy}.py`、`application/{answer_workflow,interviews,operations_runner}.py`。
- 适配/持久化/API：`adapters/model.py`、`adapters/db/{models,operations}.py`、`api/{app,routes,schemas,errors}.py`、迁移 `2c8f1d7a90b4_m3_01_answer_operation_link.py`。
- 测试/契约：`tests/test_interview_runtime.py`、`tests/unit/{test_questions,test_interview_policy,test_answer_workflow,test_operations_repository}.py`、`contracts/openapi.json`、`api.md`。
- 文档/配置：`docs/{02-architecture,03-data-model,04-workflow-policy}.md`、`config/environment.env.example`、`CHANGELOG.md`、本文件、M3 交接与 ignored 运行证据。

### 实际验证

- `uv run ruff format --check src tests migrations && uv run ruff check src tests migrations && uv run python -m pytest tests -q`：exit 0；58 个 Python 文件格式/静态检查通过；**247 passed / 2 skipped / 0 failed / 54 warnings，17.23s**。并发相同回答回归证明一真一重放、数据库各一份 Answer/Operation；429/503 均受三次总 transport attempt 上限约束。warnings 均来自 Starlette/openJiuwen/DashScope/Pydantic 既有弃用提示。
- `.venv/bin/python ../../tools/validate_spec.py`：exit 0，**44/44 passed**。
- `.venv/bin/python ../../scripts/doctor.py --json`：终态 **18 PASS / 0 WARN / 0 FAIL**；`sha256sum -c CHECKSUMS.sha256` 终态 **169/169** 一致。
- fixture FastAPI 冒烟：真实路由完成 plan→start→answer→operation 查询；返回 `202 → succeeded → NEXT`，Interview 保持 active 并进入下一 main question；执行的是正式 openJiuwen Workflow，只有外部 Analyzer 为 ScriptedAnalyzer。专用私人回答标记未出现在 stdout/stderr。
- 失败留痕：早期 runtime 回归暴露缺失 Observation flush 导致 FK 失败和 nullable level fixture 不符合 Schema，均按契约修正；首轮全量另暴露 doctor 对参数名 `file_secret_settings` 的误报及 Workflow 在错误 event loop 构造，修正设置源签名和构造时机后通过。最终 Ruff 前一轮发现 import 顺序及 operation 终端边界的 broad-exception 注释缺失，补明确边界后全绿；未删除断言、未降级真实 SDK、未用 mock 框架替代 openJiuwen。

### 模型、成本、状态与下一步

- SDK：openjiuwen 0.1.18，项目锁定兼容 commit `72c4985111b8`；存储/索引为 SQLite + 既有 Milvus Lite/openJiuwen Knowledge。M3 测试没有调用外部文本模型，实际 provider/model 为 null，外部调用数 0，token/cost 均为 null。
- `.env.local` 权限 0600 且被 Git 忽略，但只有 embedding/Knowledge 键名，没有六个业务模型键。历史 `deepseek-v4-flash` 探针不能替代本业务链；M3-01 live 保持 NOT_RUN。
- 文档已同步 `api.md`、架构、数据模型、Workflow、环境模板、CHANGELOG、process 和 handoff；API 有变化，前端无变化。
- **唯一下一任务**：向负责人提交前端答题界面设计输入并等待评审；当前响应即为设计前通知。未获确认前不开始前端设计/施工。

## 30. 2026-09-19｜M3 后端闭环与文档一致性复核

- 复核结论分层：M3-01/M3-02 **后端实现闭环**；M3-02 仅在本地后端范围 VERIFIED。整体产品闭环未完成，缺业务文本模型 live、前端答题/断流恢复、M3-03 control/end 交互及 M4 评分报告。
- 首轮审计发现五处现行漂移：根 README 保留 186 项旧回归且称首题未实现；服务 README 仍称只有 M0 探针；`docs/07` 没有 M3 测试映射；`docs/13` 把已解决 blocker 写成现行风险；`apps/web/src/api.ts` 把 `current_question` 固定为 null 且缺 start/answer/retry 契约。以上均按历史与当前状态分离后修正，没有改写旧阶段事实。
- `api.md`、导出 OpenAPI、Pydantic API、迁移、数据模型、Workflow 文档、前端网络类型和 M3 handoff 已互相对应；前端仅提供 start/answer/retry 客户端契约并纠正过期门禁文案，未新增答题组件、交互状态机或视觉设计。
- 为闭合 T25 fixture 边界，模型 transport 预算测试补充 429，与既有 503 一样严格最多三次；全量终态 247 passed / 2 skipped。T23 的真实浏览器断线重连和 UTF-8 网络分块、真实模型效果/延迟/成本明确保持 NOT_RUN。
- 前端网络契约在锁定 Node 24 下通过 `tsc --noEmit && vite build`（29 modules）；浏览器用显式 fixture 响应实际渲染工作台，确认 approved Seed、start/answer/retry 后端就绪和“前端待设计”边界可同时读到，页面不再出现过期 `technical_review` 门禁。
- 闭环复核还发现 PROBE 虽已选出最重要 criterion，但候选人文案仍是与缺口无关的意图级通用句。已改为用冻结 Rubric 合格阈值确定性聚焦，且不泄露内部 criterion ID。首个回归断言误以为首题绑定技术 Seed，实际该 fixture 正确走 `seed_id=null` 回退题，首次 1 failed；按真实冻结回退 Rubric 修正预期后 targeted 与全量均通过，未放宽业务断言。
- 同步文件：根/服务 README、`apps/web/src/{api,App}.tsx`、`docs/07-test-and-acceptance.md`、`docs/13-risks-and-decisions.md`、CHANGELOG、process、M3 handoff、ignored verification evidence 与 CHECKSUMS。无 API 语义、数据库或依赖变化；前端改动仅为契约同步和事实文案，不是界面设计。

## 31. 2026-09-19｜PUBLIC-01 分段提交与公开仓库发布（VERIFIED）

- 先将连续工作区按职责整理为 Seed 审核、JD/Planner、M3 回答工作流、前端工作台、文档/隐私五个本地提交；随后为公开发布建立不包含旧本地历史的干净 `main`。
- 公开 `main` 首次 push 为四段：`7d3694a` 工具链/CI、`449375e` 后端/契约/测试、`554b78d` 前端工作台、`a678d6a` 规范/交接。旧 `master` 只保留在本地作为回退点，不得直接推送到公开 remote。
- 发布前清理工作站绝对路径、私有简历文件名/身份标签/内容指纹；`.env.local`、`runtime/`、真实简历、来源 PDF 和运行证据均保持 ignored。M2-02 smoke 改为只接受显式 `ZHIJUE_DEMO_RESUME_*` 私密输入，不再扫描 Downloads。
- 验证：后端 Ruff 覆盖 62 files，全量 247 passed / 2 skipped / 54 warnings；规范 44/44；doctor 18 PASS / 0 WARN / 0 FAIL；前端锁定 Node 24 + pnpm 10.34.5 build 通过，29 modules；最终完整性清单 170/170。
- 前端命令失败留痕：首次 PATH 缺 `pnpm`（exit 127）；其次裸 corepack 选择 pnpm 12.4.2，与锁定 10.34.5 冲突（exit 1）；显式 `corepack pnpm@10.34.5` 后通过，未放宽版本约束。
- GitHub 核验：仓库 `https://github.com/hongyue0721/zhijue_face` 为 `PUBLIC`，默认分支 `main`；`git ls-remote --heads origin` 仅返回 `refs/heads/main`，远端 HEAD 与本地一致。
- 发布动作无业务 API、Schema、数据库迁移或依赖变化；修正前端问题类型为后端真实 `main / probe / clarification`。业务模型 live 和 M3-03/M4 状态保持不变。
- 交接：`docs/handoffs/2026-09-19-publication.md`。唯一下一任务仍为 M3-03 前端答题界面设计评审。

## 32. 2026-09-19T08:13:10-07:00｜M3-03 P0 前端产品化重构领取（IN_PROGRESS）

- 授权：负责人明确要求开始重构，并给出三页信息架构、API 硬约束、AnyUI 使用边界、26 项前端验收和最终纵向链路；不再等待额外设计确认。
- 前置：工作区 `main...origin/main` 干净，基线 `f2f3af2`；M3-02 本地后端 VERIFIED。M3-01 业务文本模型 live 仍 NOT_RUN，不由前端兜底。
- API Truth Audit：已逐项读取 `api.md`、`contracts/openapi.json`、FastAPI routes/events、InterviewService、现有 `api.ts`/`App.tsx`。正式 UI 只消费当前实现的 14 个 route；明确排除 control/report/resume/list/runtime 路径。
- 输入：用户选择的 PDF、手工事实、用户提供 JD 或服务端 synthetic Demo JD、InterviewView/OperationView/SSE；不把 internal ID 推导成展示事实，不使用 mock 数据补业务缺口。
- 输出：`apps/web/src/pages/` 三页、按 profile/prepare/interview 分层的业务组件、统一 API/SSE 客户端与产品视觉；新增 `docs/ui-contract.md`，同步测试记录、CHANGELOG、process 和 handoff。
- 允许修改：`apps/web/`、`docs/ui-contract.md`、`docs/07-test-and-acceptance.md`、`docs/08-ux.md`、README、CHANGELOG、process、handoff、完整性清单；只有真实审计发现契约缺陷才改 `api.md`/后端。本轮不实现评分、报告、简历优化、历史列表、登录或岗位市场。
- 依赖决定：采用包入口 `@any-design/anyui/react` 和正式样式入口；只使用已核实导出的基础组件。AnyUI 0.5.2 的 React 包在运行时直接导入可选 peer `@iconify/react`，因此安装时必须同时锁定该 peer；不引入第二套 UI 框架，不启用 Liquid Glass。
- 计划验收：固定 Node 24/pnpm 10 的 typecheck/build；真实浏览器覆盖 1366×768、1440×900、1920×1080、390px；真实 FastAPI + Vite 完成 PDF→Operation→blocks/facts/confirm→plan→start→answer→Policy→下一题/追问。后端全量回归、规范校验、doctor 和完整性检查在收尾统一运行。
- 回滚：以 `f2f3af2` 为文件级基线；新增路径单独删除，已有文件按交接差异恢复。禁止 destructive Git 操作。

## 33. 2026-09-19T08:13:10-07:00—2026-09-19T09:03:51-07:00｜M3-03 三页 P0 前端（VERIFIED）

### 真实交付

- 把旧单页工作台重构为 `/start`、`/profiles/:profile_id/prepare`、`/interviews/:interview_id` 三页；统一顶部、步骤条、运行模式提示、错误组件和 760px 内容列。AnyUI 只作为直接包依赖使用，视觉由现有 CSS Tokens 控制，没有 Liquid Glass。
- 资料页真实调用 Profile、multipart Document、Document blocks、facts、Claim confirm 与 Operation；空 `proposed_claims` 不造示例事实，扫描 PDF 明示 P0 文本降级。准备页按服务端真相区分 synthetic/user JD，渲染 Requirements/Coverage Map/五 Slots，internal ID 默认折叠。
- 面试页由 Interview/Question/Decision 快照驱动。answer 的 `client_turn_id` 和 `Idempotency-Key` 由调用方生成并在网络不确定性重试时完全复用；202 后立即展示服务端已保存原文。分析失败只走 Operation retry，PROBE/CLARIFY/NEXT/END、revision conflict、capacity limited 和 health readiness 均有明确状态。
- `useOperationMonitor` 以 EventSource 触发 GET Operation，再由 800ms polling 保证收敛；终态只来自 Operation snapshot。页面 unmount 会关闭 EventSource、计时器和 fetch。失败 operation ID 只为同标签页恢复写入 `sessionStorage`，跨新标签页不作虚假承诺。
- API/OpenAPI/Python DTO/数据库/迁移均无变化；新增前端消费契约 `docs/ui-contract.md`。第三方依赖新增 AnyUI 0.5.2、其必需 peer `@iconify/react` 6.0.2 与测试依赖 Vitest 4.0.18；均为锁定版本、本地可运行，无云服务。

### 实际验证

- 前端：`corepack pnpm@10.34.5 test` exit 0，**7 passed**；`corepack pnpm@10.34.5 build` exit 0，TypeScript `--noEmit` + Vite **112 modules**。
- 后端：`.venv/bin/python -m pytest -q` exit 0，**247 passed / 2 skipped / 0 failed / 54 warnings**。
- 浏览器：synthetic 文本 PDF 完成 Profile→upload→blocks→manual fact→confirm snapshot→demo/user JD→5 Slots→start→answer→PROBE/CLARIFY/NEXT/END。分析失败保留原回答，retry 捕获中没有第二次 `/answers`；阻断 SSE 后实际发出 4 次 Operation GET 并推进主问题；390×844、768×900、1366×768、1440×900、1440×1000、1920×1080 六组视口均无横向溢出。去敏证据位于 ignored 的 `runtime/evidence/m3-03/`。
- 规范校验首轮因 README 已链接而 handoff 尚未创建，实际为 43/44、exit 1；创建交接后复跑 **44/44、exit 0**。doctor 首轮为 17 PASS / 1 WARN / 0 FAIL，唯一 WARN 是施工中文件已变化而完整性清单尚未重建；重建后终态 **18 PASS / 0 WARN / 0 FAIL**，`CHECKSUMS.sha256` **202/202** 逐项通过。
- 浏览器自动化一次 helper 等待超时、一次 locator 误用，页面资源状态实际已完成；改为 DOM/网络断言继续。视觉检查发现 AnyUI 全局暗色 `span/textarea/progress` 污染，应用作用域修复后重新截图。没有通过删断言或后端兜底掩盖。

### 边界、成本与下一步

- 浏览器运行模式为 `fixture`：真实 FastAPI、SQLite、正式 Operation/SSE 与 openJiuwen Workflow；只替换外部 Analyzer。外部业务模型调用 0，provider/model/token/cost 均为 null；业务模型效果、延迟、429 和费用仍 `NOT_RUN`。
- 未实现评分、回答优化、报告、历史列表、登录、职位市场、OCR 或 Memory；跨代理 UTF-8 分块、`EVENT_HISTORY_GONE` 与跨新标签页失败 operation 恢复未做浏览器级验证。
- 版本落盘：前端实现 commit `5fe92051c09ef94e0009fc456546e69358905efb`；规范交接与完整性清单由包含本节的后续 docs commit 落盘。
- 文档同步：`docs/{02-architecture,07-test-and-acceptance,08-ux,ui-contract}.md`、README、CHANGELOG、process、handoff；`api.md` 已检查无变化。
- 唯一下一任务：负责人提供 O04 私密业务模型配置和费用上限后执行 M3-01 live 验证；在此之前不启动 M4。

## 34. 2026-09-19T09:32:55-07:00｜M3-03 契约与展示语义漂移修正（VERIFIED）

- 开工基线：公开 `main` 的 `77d703a364cd66529b0e1c92d50116be3272bf98`，工作区干净。重新读取 OpenAPI、后端 errors/routes/InterviewService、前端 API/展示/页面、测试、UI Contract 和 process 后，确认负责人列出的四类偏移全部存在。
- 容量错误真值为后端 `CapacityLimitedError(code=CAPACITY_LIMITED, status=429, retryable=true)`；前端 ErrorNotice、answer retry 分类和 UI Contract 误写 `OPERATION_CAPACITY_LIMITED`，现统一按真实 code 处理。API 客户端仍对 429 reject，不把失败响应当成功。
- start operation 会一次性按冻结的五个 Slot 实例化根问题；Prepare 文案现与此一致，并明确只有后续 PROBE / CLARIFY / NEXT / END 由回答驱动。后端实例化逻辑未改。
- `JDSourceView.source_type` 四类现在逐项映射；不读取 `source_name` 猜官方来源。follow-up intent 补齐 counterfactual、pushback、reflection；pushback 与 counterfactual 不合并，未知值不直接暴露。
- `apps/web/tests/contracts.test.ts` 从 7 项增至 **10 passed**：新增 429 capacity rejection/retry 分支、四类 JD source、三种 intent 与 fallback。`pnpm build` exit 0，TypeScript + Vite **112 modules**。
- 1440×900 实际浏览器 smoke 使用显式 intercepted fixture response：Prepare 显示 official source 与准确 start/Policy 文案；Interview 显示 pushback、`CAPACITY_LIMITED` 和原请求重试，且不存在“回答已保存，正在分析”假成功文案。证据位于 ignored 的 `runtime/evidence/m3-03-semantic-fix/`，不冒充后端或模型 live。
- 规范校验 **44/44**；doctor **18 PASS / 0 WARN / 0 FAIL**；`CHECKSUMS.sha256` **203/203** 逐项通过。
- 本轮没有修改后端、OpenAPI、`api.md`、数据库、迁移、依赖、三页路由、AnyUI、Operation Monitor、SSE/polling 或 retry 状态机。业务文本模型调用 0，provider/model/token/cost 均为 null；M3-03 保持 VERIFIED，M3-01 live 仍 NOT_RUN。
- 版本落盘：前端修复 commit `25fcddef0dae4157898ff2a898e9bc783854666f`；规范交接与完整性清单由包含本节的后续 docs commit 落盘。
- 两次结构化编辑分别残留旧 `else` 和旧 JSX `);`，Edit 解析警告均立即定位；重读局部并修正后，10 项测试、production build 和浏览器 smoke 全部通过，没有放宽断言或增加兜底。
- 审计范围内未发现第五处仍未解决的 UI/API 漂移。M4 API、评分/报告、跨标签页失败 operation 恢复等既有边界不属于本轮，也未增加假入口。

## 35. 2026-09-19T17:38:37-07:00—2026-09-19T17:57:40-07:00｜M3-03 三页 Product Polish（VERIFIED）

- 授权：负责人要求在当前 `main` 已 VERIFIED 的三页前端上做纯 UI / Product Polish，并明确冻结 FastAPI、OpenAPI、`api.md`、数据库 Schema、Interview Policy、Answer Workflow、Operation/SSE、retry 状态机、路由与三页业务流程。
- 开工基线：`8a58d1ac872f9e6c23baa2ea0e203d254870c0c9`，工作区 `main...origin/main` 干净。M3-03 业务链继续保持 VERIFIED；本轮不新增 Report、评分、雷达图、简历优化、历史记录、岗位市场、登录、Skip 或 End Control。
- 输入与输出：只消费现有 Profile/Document/Interview/Operation 响应；输出限于品牌、视觉 Token、信息层级、中文展示文案、Requirement 前端聚合/折叠和响应式样式。Requirement tier 数量只由 `InterviewView.jd_requirements` 派生，不构造业务事实。
- 允许修改：`apps/web` 展示层、`docs/08-ux.md`、`docs/ui-contract.md`、测试记录、README、CHANGELOG、process、handoff 与完整性清单。后端、契约、迁移和依赖不在修改范围。
- 计划验收：保持现有 10 项 contract tests 全通过，production build 通过；真实浏览器检查 1366×768、1440×900、1920×1080、390×844，并覆盖 `/start` 初始态、Prepare 计划完成态、Interview 主问题与 PROBE/CLARIFY 态。
- 回滚：以本节开工基线按文件恢复，不使用 reset、stash 或覆盖用户修改。完成本轮后冻结 M3-03 视觉；项目唯一首要任务仍是 M3-01 业务文本模型 live 验证，不提前启动 M4。

- 实际交付：Header 品牌图形由“知”统一为“职”，品牌显示“职觉 ZhiJue / AI 面试陪练”，步骤和模块 Eyebrow 全部中文化；普通业务卡片阴影归零，问题卡仅保留 `0 6px 18px rgba(32, 48, 74, 0.04)`，主卡片/问题卡 12px、Input/Button 9px、Tag 6px，并补 Linux 中文字体回退。
- `/start` 初始态继续居中；上传完成后的 Document、Claim 确认和资料就绪改为左对齐低密度信息层级，候选原文与资料版本默认折叠。没有生成额外 Claim，也没有改 Profile/Document 门槛。
- Prepare 岗位摘要从真实 `jd_requirements` 派生 required/preferred/responsibility/contextual 四类数量；完整 N 条 Requirement 使用原生 `details/summary` 默认折叠。主 CTA 调整到计划摘要后，使 1366×768 首屏可见；Coverage/Plan 仍双栏，五题主问题与后续动态 Policy 的既有真实文案未改。
- Interview 保持约 65%:35% 双栏与深蓝 Question Card。MAIN 右栏为“面试依据”；PROBE/CLARIFICATION 分别为“为什么继续追问/追问方向”和“为什么需要澄清/澄清方向”，仅消费现有 `question.kind`、`root_results`、`reason_summary`、`followup_intent`。完成态只显示“当前版本尚未生成正式面试报告”。
- 锁定 Node 24.21.0 / pnpm 10.34.5：`pnpm test` **10/10 passed**、`pnpm build` exit 0、TypeScript + Vite **112 modules**。首次命令因 `corepack` 不在默认 PATH 而 exit 127；定位仓库 `toolchain/node24/bin` 后完成最终锁定环境验证，没有修改代码绕过。
- 实际 Chromium + Vite intercepted fixture response 检查：1366×768 Prepare、1440×900 Start/PROBE、1920×1080 MAIN、390×844 Start/CLARIFY 均无横向溢出；390px 顺序为 Question→Answer→Context，按钮与 Textarea 宽度 274/324px 可操作。证据位于 ignored 的 `runtime/evidence/m3-03-product-polish/`，不冒充 FastAPI/openJiuwen/model live。
- 规范校验 **44/44**；doctor **18 PASS / 0 WARN / 0 FAIL**；`CHECKSUMS.sha256` **204/204** 一致。本轮业务模型调用 0，provider/model/token/cost 均为 null；后端全量 247 passed / 2 skipped 为 M3-03 既有基线，本轮因后端/API/OpenAPI 0 变化未重跑。
- 后端、OpenAPI、`api.md`、数据库、迁移、依赖、三页路由、Policy、Answer Workflow、Operation/SSE、retry 状态机和业务流程均为 0 变化。Product Polish 完成时进入视觉冻结；后续小范围契约收尾见 §36。项目唯一首要任务始终是 M3-01 业务文本模型 live 验证，不因前三页完成而跳到 M4。
- 交接：`docs/handoffs/2026-09-19-m3-03-product-polish.md`。Product Polish 已由 commit `bae74d50d8af2821f93501ee700eccc059af5196`（`style(web): polish M3-03 demo UI`）落盘并推送至公开 `main`；原“版本尚未提交”是交接编写时状态，本行补记最终发布事实。

## 36. 2026-09-19T18:34:13-07:00｜M3-03 最终小范围收尾（VERIFIED / FROZEN）

- 开工 HEAD：公开 `main` 的 `bae74d50d8af2821f93501ee700eccc059af5196`，本地 `main...origin/main` 干净。重新读取 Python DTO、`api.md`、OpenAPI、Prepare 实现、前端 API/测试及进度文档后确认：`jd_text.max_length=8000`、`jd_source_name.max_length=200`，后端契约未改变。
- `apps/web/src/api.ts` 以单一常量导出两个上限；`JDInput` 同时复用常量设置 `maxlength`，显示 `当前字符数 / 8000`，并在提交前明确拒绝超限值，不截断后静默提交。契约回归从 10 项增至 **11/11 passed**。
- Prepare ready DOM 固定为 Job Summary → Coverage / 五题 Plan → Start CTA → Technical Details。Coverage、Plan 和 Requirement 仍逐项按 `InterviewView.coverage_map`、`root_plan.slots`、`jd_requirements` 的服务端顺序渲染，没有按 `competency_id` 造名称、改 priority 或生成计划。
- 锁定 Node 24.21.0 / pnpm 10.34.5：`corepack pnpm@10.34.5 test` exit 0，1 file、**11/11 passed**；`corepack pnpm@10.34.5 build` exit 0，TypeScript `--noEmit` + Vite **112 modules**。首次直接调用 `pnpm` 因当前 PATH 不含该命令 exit 127，随后使用仓库锁定的 corepack 工具链完成最终验证，没有修改代码绕过。
- 规范校验前三轮均为 **43/44、exit 1**。根因是任务板状态写成非枚举复合值 `VERIFIED / FROZEN`，校验器没有登记 M3-03，继而报告 M4-01 依赖未知；中途调整依赖文本不能解决状态行未被解析的问题。最终保持机器状态 `VERIFIED`，把 `FROZEN` 作为产物状态写入说明，第四轮 **44/44、exit 0**；这不把 M3-01 从 `IMPLEMENTED / live NOT_RUN` 升级。
- 最终规范校验 **44/44、exit 0**；doctor **18 PASS / 0 WARN / 0 FAIL**；重建 `CHECKSUMS.sha256` 后 **204/204 OK**。后端代码与契约均未改，因此未重复运行后端 pytest；沿用的 247 passed / 2 skipped 仅是 M3-03 既有基线。
- 实际 Chromium + Vite intercepted fixture response 检查 1366×768、1440×900、390×844：三档均无横向溢出，DOM 和视觉顺序均为岗位摘要→Coverage/Plan→开始动作→技术详情；CTA 允许在 Coverage/Plan 后通过纵向滚动到达。另在实际 JD 输入页确认 `maxlength=8000/200`、`最大 8000 字符` 和实时计数。证据位于 ignored 的 `runtime/evidence/m3-03-product-polish/`，不冒充 FastAPI/openJiuwen/model live。
- `/start`、`/interviews/:id`、Stepper、颜色、阴影、圆角、移动布局和业务状态机均未修改；FastAPI、OpenAPI、`api.md`、数据库、Workflow、Policy、Operation/SSE 与 retry 为 0 变化。当前仍是真实 FastAPI/SQLite/openJiuwen Workflow/Operation/SSE + fixture Answer Analyzer；业务模型 live、token、cost、效果与延迟仍 `NOT_RUN` / null。
- M3-03 从本节起正式 `FROZEN`，不再继续修改前三页视觉，也不启动 Report UI、评分、雷达图、improved answer 或 Resume Draft。唯一下一任务：负责人提供 O04 私密业务模型配置和费用上限后执行 M3-01 业务文本模型 live 验证；完成前不启动 M4。

## 37. 2026-09-19T18:52:00-07:00—2026-09-19T19:00:00-07:00｜M3-01 业务文本模型 live（VERIFIED）

- 开工 HEAD：公开 `main` 的 `1077ba3d8429ed96091c39fd612a1f9245a3137e`，工作区干净。负责人提供 `deepseek-flash`、`https://api.deepseek.com` 与私密 API Key，并明确要求开始受控测试；Key 只写入本地 0600、Git ignored 的 `.env.model.local`，不进入代码、文档、证据或命令参数。
- 新增 `services/api/smoke/answer_model.py`。它复用生产 `OpenAICompatibleAnswerAnalyzer`、approved UART/DMA Seed 0.2.1、Observation Schema 和真实 openJiuwen Workflow；输入为 synthetic 问答，Knowledge 检索本轮不重复调用。证据使用独占创建、0600、密钥/绝对路径拒绝检查，且不保存模型原文。
- 第一轮 1 次真实 HTTP 调用在 8.729782 秒返回，但模型把中文解释写进枚举字段 `criteria[0].finding`。服务端按 Schema 明确拒绝，状态 failed，没有修复字段、放宽断言或假装成功；ignored 证据为 `runtime/evidence/m3-01-live/deepseek-flash-20260919T1855.json`。该失败响应的 usage 未穿过 Workflow 失败边界，记为 NOT_MEASURED。
- 根因是 `OBSERVATION_SYSTEM_PROMPT` 只列字段名，没有说明 relevance、knowledge_status、kind、finding、level 的精确枚举和 quote/reference 语义。现补齐结构化输出约束；同时发现 openJiuwen 会把组件异常写入 ERROR 日志，因此 SemanticValidation 对外只抛固定 `analyzer output failed contract validation`，避免不可信模型字段或回答派生文本进入 SDK 日志。领域纯函数仍保留详细校验错误。
- 第二轮 1 次真实 HTTP 调用通过：10.650749 秒；模型 `deepseek-flash`；Observation 为 `relevant / adequate`，唯一 criterion 为 `supported / level=3` 且含一条原文引文与三条冻结 reviewed reference；程序 Policy 输出 `NEXT / ADEQUATE_EVIDENCE`。usage 为 input 1156、output 2544、total 3700；provider 未返回费用，cost 为 null / NOT_MEASURED。证据为 `runtime/evidence/m3-01-live/deepseek-flash-20260919T1858.json`，SHA-256 `239a9a03a51b40a4f9ce8ee4d7f48a20d69240f90ddd30499bca039e6011b78b`。
- 生产装配检查在独立 ignored SQLite 路径构造 `create_default_app()`，readiness 为 `true`，Knowledge/model 均 `configured`，SeedBank 指纹 `1c6716b90449d375`。这证明私密双配置可装配，不额外产生 embedding 或模型请求。
- 最终 Ruff format/check 覆盖 src/tests/smoke/migrations，**63 files / all checks passed**；全量 pytest **248 passed / 2 skipped / 0 failed / 55 warnings**；规范校验 **44/44**；doctor **18 PASS / 0 WARN / 0 FAIL**；`CHECKSUMS.sha256` **206/206 OK**；`git diff --check` 无输出。API、OpenAPI、数据库 Schema、迁移、前端、依赖、动作枚举和 Policy 决策规则均无变化。
- 状态：M3-01 从 `IMPLEMENTED / live NOT_RUN` 升为 `VERIFIED`，不写 ACCEPTED。两次真实业务模型 HTTP 调用中一失败、一成功；只登记成功样本的 provider usage，不把一次成功扩张为模型效果、p95、429/超时恢复或成本结论。
- 唯一下一任务：M4-01 评分与报告。先同步 `api.md`，再实现后端契约、持久化、评分/UNKNOWN 边界和报告；前三页视觉继续冻结，不先造 Report UI。

## 38. 2026-09-19｜M4-01 确定性评分与报告（VERIFIED）

- 开工 HEAD：公开 `main` 的 `a74b6a37e99bf7850b7b5dabbbcafc31096739e0`，工作区干净。按 API-first 先同步 `api.md`，冻结 control、ReportView、null/UNKNOWN、coverage、score、幂等、事件与恢复语义，再修改实现；前三页视觉继续冻结。
- 新增 `domain/scoring.py` 与 `application/reporting.py`。每根题从冻结 Rubric 取 criterion/kind/weight，主答与追问按 criterion 合并且单次计权；supported+contradicted 保留 disputed，coverage<60%、未测或跳过均不造 0。至少三根 scored 后才按根题等权和 decimal ROUND_HALF_UP 生成 overall_score。
- `POST /interviews/{id}/control` 支持 skip/end，`GET /interviews/{id}/report` 只读唯一持久化 Report。自然 END 或 control END 在短事务写五个 Assessment、Report、`report.ready` 与 completed；`improved_answers=[]` 明确保留给 M4-02。重复 end 返回同一 operation，skip/end 不调用模型。
- 回答进行中 end 会先记录 `stop_requested` 并停止暴露当前题，当前回答仍可安全提交 validated Observation，随后由串行 runner 汇总。Observation 已成功而报告写入失败时，retry 只重跑确定性报告，不再次调用 Analyzer。重启恢复把 queued/running 都标 interrupted，因为两者的内存 callable 均未持久化。
- 数据迁移新增 `7f1b9c4d2a60_m4_01_report_uniqueness.py`：Assessment `(interview_id,root_question_id)` 唯一，Report `interview_id` 唯一。OpenAPI 更新为 18 paths；Python DTO、FastAPI routes/error/retry 分发、`apps/web/src/api.ts` 的 control/report 类型与客户端方法同步。冻结三页没有 Report UI 或控制按钮。
- 先写的 `tests/unit/test_scoring.py` 首次真实红灯为 `ModuleNotFoundError: zhijue.domain.scoring`；实现后 5 passed。新增/扩展回归覆盖 60% 边界、half-up、冲突/null、主答/追问合并、自然五题、main/followup skip、回答中 end、重复 end、报告失败后无模型重调、迁移唯一约束与 OpenAPI 快照。
- 后端全量命令 `.venv/bin/ruff format --check src tests smoke migrations && .venv/bin/ruff check src tests smoke migrations && .venv/bin/python -m pytest tests -q` exit 0：67 files formatted，Ruff all checks passed，**261 passed / 2 skipped / 0 failed / 63 warnings**。专项评分/API/runtime/migration 回归 **52 passed / 21 warnings**；规范校验 **44/44**。
- 临时 TestClient 烟测运行真实 FastAPI、真实 openJiuwen Workflow、SQLite 和 ScriptedAnalyzer fixture，连续五个回答后得到 `completion=complete / scored_root_count=5 / overall_score=67 / status=completed`；临时脚本已删除。该结果证明程序闭环，不证明真实模型质量。
- 前端最终以仓库锁定 Node 24.21.0 / pnpm 10.34.5 运行：`pnpm test` **11/11 passed**，`pnpm build` exit 0、112 modules，无 engine warning。此前默认 shell 的 Node 26.8.1 也通过但产生版本警告；最终结论只采用锁定工具链结果。
- 本轮外部模型和 embedding 网络调用均为 0，新增费用未发生；fixture 的 `model_calls=5` 不是付费调用。Report UI、真实模型浏览器五题整场、429/timeout、p95 和成本仍 NOT_RUN。M4-01 只写 VERIFIED，不写 ACCEPTED。
- 最终完整性：doctor **18 PASS / 0 WARN / 0 FAIL**，密钥扫描 212 个 Git 跟踪文件 0 命中；`CHECKSUMS.sha256` **211/211 OK**；`git diff --check` 无输出。
- 修改范围：`api.md`、OpenAPI、后端 scoring/reporting/interview/API/operation recovery、SQLAlchemy/Alembic、前端网络类型、评分/API/runtime/migration tests，以及 README、架构/数据/Workflow/评分/验收/UI/risk 文档、CHANGELOG、process、handoff 和完整性清单。交接：`docs/handoffs/2026-09-19-m4-01.md`；唯一下一任务为 M4-02。

## 39. 2026-09-19｜M4-02 事实约束回答优化与简历草稿（IMPLEMENTED）

- 开工 HEAD：公开 `main` 的 `4e4e7b43332c7d4e964d58ece3854275ef689a72`，工作区干净。先在 `api.md` 冻结 Report 改写状态、ResumeDraft、Operation/event、retry 与确认打印契约，再修改实现；M3-03 三页视觉保持冻结。
- 新增 `domain/grounded_content.py`、两个 JSON Schema 与 `application/content_workflow.py`。回答优化片段只能绑定允许的 `answer_id + exact_quote` 或当前快照 Claim；简历每个正文条目至少绑定一个允许 Claim。未知 ID、非逐字引文、无来源片段、输入没有的新数字、从参与升级为主导/负责，以及未确认占位符均确定性拒绝。
- `ContentGenerationService` 是生成内容唯一写入方。`report.coach` 与 `resume.compose` 先短事务受理 Operation，再在真实 openJiuwen `Start → Generator → SemanticValidation → End` 外部执行，最后短事务写 Report/ResumeDraft 与 `coaching.ready` / `resume_draft.ready`。失败不改变原回答、评分、Claim 或原简历资料；retry 复用同一资源和冻结输入。闭环审计同时消除了原先“每个业务 retry 内再做 transport retry”的放大风险：一个模型 Operation 只发一次 HTTP 请求，transport/Schema/语义失败共同消耗 `MODEL_MAX_RETRIES + 1` 的 parent-linked 累计预算，硬上限三次。
- 迁移 `b4d7c2e91f30` 新增 Report 改写状态/操作字段和 ResumeDraft 表，并以 `(profile_snapshot_id,target_hash)` 防止同一事实快照/目标重复草稿。新增生成/读取/确认 API、OpenAPI、Python DTO 和前端类型；`InterviewView.profile_id` 让报告页从服务端关系取得 Profile，不从 URL 或浏览器猜测。
- 新增 `/interviews/:interview_id/report` 与 `/resume-drafts/:draft_id` 功能页面。报告直接读取持久化评分，null 保持“未形成总分”，显式触发回答优化并展示原答/改写/待补事实；简历草稿展示 Claim 来源与差异，确认前不显示打印动作，打印媒体只保留已确认正文。未做视觉 Product Polish。
- 回归覆盖 Schema/来源绑定/数字、未绑定英文技术词和责任升级拒绝、生成成功、失败保留、parent-linked retry 与累计预算耗尽、迁移 up/down/metadata、OpenAPI 和前端路由/API。后端全量 **272 passed / 2 skipped / 0 failed / 73 warnings**；Ruff check/format 检查 73 个 Python 文件全绿。锁定 Node 24 下前端 **12/12 passed**，TypeScript 通过，Vite **114 modules**。
- 最终 Chromium + Vite + FastAPI fixture 纵切面得到 Report `report_314761ef679b674e30d0`、ResumeDraft `resume_b59b46840872313e84f3`；页面实际显示 `original_answers[].raw_text` 与 `{id,text}` Claim 来源。确认后打印动作调用成功，print media 的 header/actions/audit 为 `display:none`、正文为 `display:block`，1440 宽视口无横向溢出。证据汇总写入 ignored 的 `runtime/evidence/m4-02/verification.json`。
- 本轮外部模型和 embedding 网络调用均为 0，usage/cost 为 null；浏览器使用 `ScriptedContentGenerator` 替换模型边界，但编排为真实 openJiuwen Workflow。生产内容模型 live、质量/延迟/成本、独立验收和新页面 Product Polish 均 NOT_RUN，因此状态保守记为 IMPLEMENTED，不写 VERIFIED/ACCEPTED。
- 最终完整性：规范校验 **46/46**；doctor **18 PASS / 0 WARN / 0 FAIL**，223 个 Git 跟踪/待跟踪文件密钥扫描 0 命中；`CHECKSUMS.sha256` **222/222 OK**；`git diff --check` 无输出。
- 接口、数据模型、架构、Prompt/事实约束、验收、UI Contract、README、CHANGELOG、process 与 handoff 已同步。交接：`docs/handoffs/2026-09-19-m4-02.md`；唯一下一任务为两个新页面 Product Polish 与独立验收。

## 40. 2026-09-19｜五页首屏收口与展示语义修正（IMPLEMENTED）

- 授权与基线：负责人明确要求在 `59e509e30291e284c5bfd2f2796b294171f5504a` 上收口五页首屏、响应式、展示语义、Operation 终态和 lost-202 恢复，并要求四组提交和推送。该明确指令解除 §36 的旧视觉冻结；不授权改 FastAPI、OpenAPI、数据库、Workflow、Policy 或事实边界。
- 可靠性：`useOperationMonitor` 以首个 terminal snapshot 单调收敛，观察终态时同步停止 interval、EventSource 和 in-flight fetch。Report improvements、ResumeDraft 创建、Report retry、Resume retry 使用 operation-scope recoverable command，在未取得明确响应时保留原 body 与 `Idempotency-Key`，显式重试逐字段复用。
- 展示：四步导航统一为资料/准备/面试/复盘；用户可见状态、criterion kind/finding/level 均使用中文映射，未知内部值走中性文案。null 分数保持“未形成总分/未评分”，真实 0 分保持“0 分”；Report/Resume 不显示裸 assessment、criterion、status、Claim ID。
- 页面：Start 为材料摘要/五条分页事实双栏；Prepare 为要求覆盖/五题计划双栏并只对已登记 competency 映射中文；Interview 保持完整题面、回答框局部滚动与首屏提交；Report 左侧五题导航、右侧单题评分/优化页签；Resume 左侧正文、右侧按 `item_id/claim_id` 的当前条目来源审计。分页、页签、题目和条目选择均为零写请求。
- 响应式：修复 AnyUI 全局 `html/body height:100vh` 造成的移动端根滚动锁死；桌面工作区优先内部滚动，移动端解除固定高度。打印态解除 Resume 工作区高度、overflow 和 max-height，只输出 accepted 完整正文。
- 浏览器证据：实际 Vite + 显式 synthetic fixture API 完成两轮五页视觉检查。1366×768 五个主 CTA 坐标为 `189–241 / 189–241 / 647–699 / 685–727 / 194–236`；1440×900 与 1920×1080 全部首屏可见。390×844 全部无横向溢出且 Interview/Report 动作可经根页面滚动到达；1093×614、683×384 等效布局视口覆盖 125%/200%。ignored 截图位于 `runtime/evidence/ui-first-screen-closure/`。
- 压力输入：21 条候选事实、17 条 JD、五题报告、20 条简历正文均由指定工作区滚动；6,000 字回答 textarea 为 `108/3184`，提交动作底部 `698.77`。accepted 打印正文在 1366px print emulation 下为单栏、无裁剪、无横向溢出。
- 语义注入：Report null 显示“未形成总分/本次回答信息不足”，另一根题 score=0 显示“0 分”；优化失败与简历生成失败保持 failed 并显示错误，不伪装 ready/accepted。只读交互网络捕获的写请求数组均为空。
- 回归：Node 24.21.0 下 Vitest **16/16 passed**、TypeScript `--noEmit` exit 0、Vite build exit 0（112 modules）；后端 **272 passed / 2 skipped / 0 failed / 73 warnings**；Ruff format/check 73 files 全绿；规范 **46/46**；doctor **18 PASS / 0 WARN / 0 FAIL**；完整性清单 **221/221 OK**；`git diff --check` 无输出。
- 提交分组：`9778e32` 可靠性，`9909f40` Report/Resume，`f64ee1d` Start/Prepare/Interview，本节、测试、验证报告、CHANGELOG、handoff 与完整性清单归入最终证据/文档提交。HTTP API、`api.md`、OpenAPI、Python DTO、数据库、迁移、依赖与配置均核对无变化。
- 模型与状态：浏览器数据为显式 synthetic fixture；外部模型和 embedding 调用 0，provider/model/usage/cost 均为 null。生产 Content Generator live、负责人独立验收仍 `NOT_RUN`，故 M4-02 保持 `IMPLEMENTED`，不写 `VERIFIED/ACCEPTED`。
