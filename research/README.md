# research/｜Candidate Evidence Fidelity 研究基础设施

分支：`research/candidate-evidence-fidelity-v1`。上游基线 `d91023a`（比赛 Demo main）。

这里是论文《面向大语言模型面试回答优化的证据约束生成方法研究》的实验平台，
**不是**比赛 Demo 的一部分，也**不得**把研究代码回写 `main`。

## 硬边界

- 研究输出只写 `research/runtime/`（已 Git 忽略）。不写 `business.db`、`Report`、
  `ResumeDraft`、`Operation`，不碰生产 `runtime/`。
- 不加业务数据库 migration，不改 OpenAPI，不改前端，不改面试 Policy/评分/Seed Bank。
- `ground_truth.json` 与 case 的 `evaluator_only` 区块永不进入模型输入；
  `tests/test_no_ground_truth_leakage.py` 扫描最终发出的 model input。
- 没有真实模型实验，任何文档都不得写"方法有效"；状态只用
  `IMPLEMENTED / VERIFIED / NOT_RUN`。

## 目录

| 路径 | 职责 |
|---|---|
| `DESIGN.md` | 当前能力 / 缺失能力 / 改造边界 / 方法定义 / 防污染措施（唯一设计真源） |
| `contracts/` | `candidate-ground-truth`、`interview-case`、`research-trace` 三份 JSON Schema |
| `config/experiment.yaml` | 实验配置（不含密钥；密钥仍走仓库外 0600 私密文件） |
| `config/prompts/` | 按版本冻结的 Prompt；一次修改一个新版本 |
| `data/candidates/candidate_xxx/` | `ground_truth.json` + `private_kb/*.md` + `interview_cases/*.json` |
| `splits/` | `pilot / dev / test` 成员清单（冻结后不得按结果回改） |
| `src/zhijue_research/` | 研究代码：dataset、methods、runner、trace、retrieval、evaluators、guard |
| `tests/` | 研究专项 pytest（默认全离线、零模型费用） |
| `runtime/` | 运行产物：trace JSONL、隔离 Milvus 文件、证据快照（忽略） |

## 怎么跑

以下命令都是本轮实际跑过的形态（`research/` 不安装进业务环境，靠 `PYTHONPATH` 复用
`services/api/src` 的业务模块）。

```bash
cd research

# 研究测试（默认全离线：不碰业务库、不调模型、不建生产 KB）
../services/api/.venv/bin/python -m pytest tests -q

# 只校验数据集与 split（零模型调用）
PYTHONPATH=src:../services/api/src ../services/api/.venv/bin/python -m zhijue_research.cli verify-dataset

# 全链路 dry run（scripted 模型 + scripted 证据，零费用）
PYTHONPATH=src:../services/api/src ../services/api/.venv/bin/python -m zhijue_research.cli run \
  --model-driver scripted --evidence scripted --tag dryrun

# 漂移注入自检：指定方法故意产出捏造内容，验证检测器与硬校验真的会响
PYTHONPATH=src:../services/api/src ../services/api/.venv/bin/python -m zhijue_research.cli run \
  --model-driver scripted --evidence scripted \
  --drift-method vanilla --drift-method evidence_bound --tag drift

# 离线聚合双轨指标（trace × evaluator 标签）
PYTHONPATH=src:../services/api/src ../services/api/.venv/bin/python -m zhijue_research.cli report \
  --trace runtime/traces/pilot_dryrun.jsonl --out runtime/reports/dryrun.json

# 真实 KB 检索（openJiuwen + Milvus Lite；embedding 可为 fixture 或 live）
PYTHONPATH=src:../services/api/src ../services/api/.venv/bin/python -m zhijue_research.cli run \
  --model-driver scripted --evidence knowledge --tag knowledge
```

真实模型调用必须显式给 `--model-driver live` 与私密 env 文件路径，且默认拒绝
（`live` 需要配置里 `allow_paid_calls: true`）。第一阶段该开关保持 `false`。

live embedding 单点探测（只调 embedding，不调对话模型；计费未知字段保持 null）：

```bash
cd research && ../services/api/.venv/bin/python scripts/live_embedding_probe.py --i-accept-embedding-cost
```

它只在内存里翻 `embed_mode=live` / `allow_paid_calls=true`，仓库配置不变；证据落在
`runtime/embedding-probe/`（Git 忽略）。
