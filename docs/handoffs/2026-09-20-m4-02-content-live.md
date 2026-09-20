# AI 施工交接：2026-09-20 M4-02 生产 Content Generator synthetic live

## 当前状态

工作目录/分支：`zhijue-demo-spec-v1.0` / `main`  
开工基线：`7c9ca81799fbd8a9183820fae6962069094cdf66`  
应用版本 / 规范版本：Demo / 1.0.0  
任务状态：M4-01 `VERIFIED`；M4-02 功能、五页 Product Polish 与生产 Content Generator synthetic live 已完成，负责人独立验收 `NOT_RUN`，因此仍为 `IMPLEMENTED`  
运行模式：真实 `deepseek-flash` + 真实 openJiuwen Workflow；输入全部 synthetic；Knowledge/embedding 本轮 `NOT_RUN`

## 本次真实完成

- 新增 `services/api/smoke/content_model.py`，从显式 0600 私密文件加载生产 `OpenAICompatibleContentGenerator`，依次执行 `coach_answers` 和 `compose_resume`。
- 每项通过真实 openJiuwen `Start → Generator → SemanticValidation → End`；没有 Mock SDK、Mock 模型、自动 retry、模型输出字段修复或失败降级。
- live smoke 记录模型公开配置、prompt/schema/source hash、每项 HTTP 次数、真实 duration/usage、候选、诊断和证据 hash；输出独占写入 ignored `runtime/`，并拒绝 API Key 与绝对路径。
- 首轮证明旧 Prompt 有根因缺陷：`response_format=json_object` 只保证 JSON 对象，远端模型无法读取 Prompt 所说的本地 Schema 文件。原有 Schema 正确拒绝两项输出。
- 诊断轮定位具体偏差：coaching 使用 `citations/quote`，增加 item-level `answer_id`，遗漏 `schema_version/changes`，并把 missing facts 写成字符串；resume 遗漏 `schema_version`、section `title`、item `item_id/reason`。
- P-COACH/P-RESUME system prompt 现逐项声明精确顶层/嵌套字段、`source_refs` union、`exact_quote`、对象形态 missing facts、section/item 必填字段及禁止别名。Schema、领域校验和业务 API 均未放宽。
- 新增 transport 回归，直接检查真实发往模型的 system message 包含上述结构；避免再次出现“仓库有 Schema、模型没收到”的假契约。
- 修复后同一模型的 coaching/resume 均通过原 Schema、资源 ID、逐字回答引文、Claim allowlist、数字、责任升级、技术词和占位符边界。

修改路径：

- 生产 Prompt：`services/api/src/zhijue/adapters/model.py`。
- live smoke：`services/api/smoke/content_model.py`。
- 回归：`services/api/tests/unit/test_answer_workflow.py`。
- 进度与交接：`README.md`、`services/api/README.md`、`docs/{06-prompts-and-factuality,07-test-and-acceptance,13-risks-and-decisions}.md`、`CHANGELOG.md`、`process.md`、`validation-report.md`、本交接、`CHECKSUMS.sha256`。

HTTP API 已核对无变化：`api.md`、OpenAPI、Python DTO、FastAPI routes、数据库 Schema、迁移、依赖、前端和配置模板均未修改。

## 三轮真实模型证据

| 轮次 | 请求与结果 | usage / duration | ignored 证据 |
|---|---|---|---|
| 初始 live | coaching/resume 各 1 次 HTTP；均被原 Schema 正确拒绝 | usage NOT_MEASURED；34.313690 / 10.935794 秒 | `runtime/evidence/m4-02-content-live/deepseek-flash-20260920T070339Z.json`；文件 SHA-256 `f36a08de8b73d1f29abb988946095e2851c038a34d93e1bc2a353322c81b188b` |
| 诊断 live | coaching/resume 各 1 次 HTTP；复现并记录上述精确字段偏差 | 474/6438/6912、393/3537/3930；25.636871 / 15.302955 秒 | `...T070539Z.json`；文件 SHA-256 `facffe4b45136e29056b402a47343af94a9904ba63e04233029c6802ccbc77cb` |
| Prompt 修复后 | coaching/resume 各 1 次 HTTP；两项均通过真实 Workflow 与原语义校验 | 669/6377/7046、535/2325/2860；27.727351 / 10.839200 秒 | `...T070818Z.json`；文件 SHA-256 `44fcf75775a945ce1c7dde78ea64086201fd74a17c482bc392380dad2724fdab`；内部 evidence hash `efd58c1c298cd318696b5f233d1dc4810a60ab6c9257e85d4dd9b0a4ecef3af4` |

三轮合计 6 次真实 HTTP / 6 次 logical model call。诊断轮与成功轮已测累计 input 2071、output 18677、total 20748；初始失败轮 usage 未穿过失败边界，保持 NOT_MEASURED，因此不能把 20748 写成全部调用总消耗。provider 未返回价格，所有 cost 为 null / NOT_MEASURED。

## 验证结果

| 命令/场景 | 环境 | 退出码 | 结果 |
|---|---|---:|---|
| `.venv/bin/python -m pytest tests/unit/test_answer_workflow.py -q` | Python 3.11.16 | 0 | 22 passed / 10 warnings |
| Ruff format/check + 全量 pytest | Python 3.11.16 | 0 | 74 files；273 passed / 2 skipped / 0 failed / 73 warnings |
| 锁定 Node 24 Vitest、`tsc --noEmit`、Vite build | Node 24.21.0 | 0 | 16/16 passed；TypeScript 通过；112 modules transformed |
| `services/api/.venv/bin/python tools/validate_spec.py` | Python 3.11 项目 venv | 0 | 46/46 passed |
| doctor、完整性、空白检查 | 项目根目录 | 0 | doctor 18 PASS / 0 WARN / 0 FAIL；223/223 OK；`git diff --check` 无输出 |

## 安全、成本与剩余边界

负责人明确自有 Key 可无限授权，但程序 `MODEL_MAX_RETRIES + 1` 的每个业务 Operation 三次硬上限不变；本 smoke 进一步固定为每任务一次 HTTP、无自动 retry。无限授权不是取消程序预算、编造费用或重复消耗的理由。

施工中私密 env 被错误读取到会话工具输出。该 Key 没有进入 Git、runtime 证据或本文档；负责人获知后明确选择继续当前 Key 完成本轮。这个选择不消除泄露风险，后续仍建议轮换；任何新 Key 都不得发送到聊天。

本轮只证明一组 synthetic coaching/resume 输入能在当前模型上通过真实 Workflow 和确定性边界。真实材料、批量稳定性、p95、真实 429/timeout、浏览器生产模型五题整场和负责人独立验收仍未证明。

M4-02 保持 `IMPLEMENTED`，不写 `VERIFIED/ACCEPTED`。唯一下一任务是负责人独立验收五页纵向链路；不自动启动 M5-01。
