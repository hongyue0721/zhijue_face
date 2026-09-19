# services/api｜职觉 Demo Python 业务后端与框架探针

**当前状态：M0 Workflow/WorkflowAgent 与 Knowledge 探针保留；M1/M2 资料和计划链已落地；M3-01 回答后端 IMPLEMENTED、M3-02 本地可靠性 VERIFIED。外部业务文本模型 live 与前端答题界面仍 NOT_RUN。**

`pyproject.toml` / `uv.lock` 锁定 Python 3.11.16 与 openJiuwen 0.1.18 兼容源码 commit `72c4985111b835530ec616f70dd67117eb2e015c`。该 commit 基于官方 v0.1.18，仅包含官方 PR #1344 的 Knowledge 删除返回值修复与测试；正式 0.1.18 wheel 本身仍有该缺陷。业务后端使用 FastAPI、SQLAlchemy/Alembic、SQLite 和真实 openJiuwen Workflow/Knowledge；没有新增平行 Agent 或第二数据库写入方。

## 可复现命令

从本目录执行；依赖尚未安装时先 `uv sync --frozen --python 3.11`。常规回归脱网运行，不调用外部业务模型；`integration_live` 和独立 Knowledge smoke 只有显式选择私密配置时才产生网络调用。

```bash
.venv/bin/python -m pytest tests -q
.venv/bin/ruff check src tests smoke migrations
.venv/bin/ruff format --check src tests smoke migrations
.venv/bin/python -m smoke.workflow --output ../../runtime/evidence/m0-02/manual-01.json
# live 会产生 embedding 调用；仅在明确验证需要时使用新的 runtime/output 名运行：
.venv/bin/python -m smoke.knowledge \
  --env-file ../../.env.local \
  --runtime-dir ../../runtime/m0-03-manual-01 \
  --output ../../runtime/evidence/m0-03/manual-01.json
```

输出证据必须写到 ignored 的 `runtime/` 且不得覆盖旧证据。独立 smoke 使用官方日志配置 API；业务应用额外把 openJiuwen 日志提升到 WARNING 并移除 SDK 文件 sink，避免回答或简历进入日志。

## 验证了什么

- 真正调用 `openjiuwen.core.workflow.Workflow` 和 `openjiuwen.core.application.workflow_agent.WorkflowAgent`。
- 两条入口均运行 Start → 自定义纯文本 TransformText 节点 → End；自定义的是节点，不是替代 Agent/Workflow/模型。
- 合成输入 `hello` 必须返回 `{"response":"R=HELLO|tagged"}`，检查状态及完整结果；不接受 COMPLETED + null。
- 非法输入/超时配置、真实节点抛错、超时取消、失败后新执行、重复执行、证据 hash 与拒绝覆盖均有测试。
- JSON 记录时间、版本、平台、官方源码路径/hash、Agent MRO、实际输出/hash。不同进程的输出 hash 可比；这不代表跨进程会话恢复。

`run_mode=live` 只表示相应框架/模型入口真实运行，输入仍需明确标记。M0 Workflow smoke 无模型；Knowledge 使用 BGE-M3 的历史累计调用见根目录 process。M3 测试运行真实 openJiuwen handle-answer Workflow，但 ScriptedAnalyzer 显式替代外部文本模型，因此业务文本模型 live 仍 `NOT_RUN`，token/费用为 null。PROBE 的候选人文案由已验证的 criterion 与冻结 Rubric 确定性聚焦，不为措辞新增模型调用。

## 未解决事项

官方基座/补充规则核验仍有阻塞；当前 WorkflowAgent 继承官方 legacy ControllerAgent/BaseAgent，弃用警告未隐藏。Knowledge 全生命周期已在锁定兼容 commit 上 VERIFIED，但正式 openJiuwen 0.1.18 发布包仍未包含删除修复。M3 后端已完成首题、回答、Policy、事件、retry 与恢复；尚缺显式业务模型配置的 live 验收、前端答题界面、评分与报告。完整进度以根目录 `process.md` 和最新 handoff 为准。

## 私密 live 配置边界

从仓库根目录复制 `config/environment.env.example` 为权限不宽于 0600 的私密文件。真实 key 不进入命令参数、文档、日志、证据 JSON 或浏览器配置。Knowledge 使用 `EMBEDDING_*`；业务回答模型适配读取 `MODEL_PROVIDER / MODEL_NAME / API_BASE / API_KEY / MODEL_TIMEOUT / MODEL_MAX_RETRIES`，只在显式设置 `ZHIJUE_MODEL_ENV_FILE` 时启用，不读取 ambient environment，也不默认与 embedding 共用 key。

当前删除 blocker 已通过固定兼容 commit 解除；该来源与官方 openJiuwen PR #1344 对应。仍不得修改 site-packages，也不要为重复证明反复消耗 embedding 额度。官方发布包含修复后，应切回正式发布并重跑 M0-02/M0-03。

