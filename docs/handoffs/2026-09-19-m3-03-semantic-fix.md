# AI 施工交接：2026-09-19 / M3-03 semantic-contract-fix

## 当前状态

工作目录/分支：公开仓库工作区 / `main`  
基线 commit：`77d703a364cd66529b0e1c92d50116be3272bf98`  
本次 commit 或尚未提交的文件：前端修复 `25fcddef0dae4157898ff2a898e9bc783854666f`；本交接、规范同步与完整性清单由包含本文件的后续 docs commit 落盘  
应用版本 / 规范版本：Demo / 1.0.0  
当前阶段和任务状态：M3-03 semantic/contract drift fix `VERIFIED`；M3-03 原三页主流程继续 `VERIFIED`  
运行模式：单元/契约测试；浏览器为 Vite 实际 UI + 显式 intercepted fixture HTTP response，不证明后端或业务模型 live

## 本次真实完成

解决的问题及关联 R 编号：修复 M3-03 已确认的错误码、start 语义、JD 来源和 follow-up intent 展示漂移；未增加需求或 M4 能力。  
修改文件：

- 前端：`apps/web/src/api.ts`、`components/common/ErrorNotice.tsx`、`components/prepare/JDSourceBadge.tsx`、`pages/{PreparePage,InterviewPage}.tsx`、`presentation.ts`。
- 测试：`apps/web/tests/contracts.test.ts`。
- 记录：`docs/ui-contract.md`、`docs/07-test-and-acceptance.md`、`README.md`、`CHANGELOG.md`、`process.md`、本交接、`CHECKSUMS.sha256`、`validation-report.md`。

接口/字段/状态/迁移变化：无。后端真实 code 仍为 `CAPACITY_LIMITED`；OpenAPI、`api.md`、Python DTO、数据库和迁移未修改。  
有意未修改的内容：三页路由、App 架构、AnyUI、Upload/Claim/Coverage/Plan/Answer、Operation Monitor、SSE/polling、retry 状态机，以及全部 M4/列表/登录能力。

### 偏移审计结论

1. **确认存在**：后端 `CapacityLimitedError` 和 routes 返回 `CAPACITY_LIMITED` / 429 / retryable；前端 ErrorNotice、answer retry 分类和 UI Contract 写成了不存在的 `OPERATION_CAPACITY_LIMITED`。
2. **确认存在**：Prepare 文案把 start 的五个根问题实例化概括为“动态生成题目”，没有区分后续 Policy 动态决策。
3. **确认存在**：`jdSourceText` 把三类非 synthetic 来源全部标成用户材料；现只按四类 `source_type` 映射。用户提供来源的 Tag 不再使用 success tone。
4. **确认存在**：前端缺 `counterfactual`、`pushback`、`reflection`，而后端 Policy、Question wording 与 JSON Schema 均允许三者。
5. **仓库提前修复项**：无；四项在基线 HEAD 均仍存在。审计范围内没有发现第五项未闭合 UI/API 漂移。

## 验证证据

| 命令/用例 | 环境 | 退出码 | 通过/失败/未运行 | 证据路径 |
|---|---|---:|---|---|
| `corepack pnpm@10.34.5 test` | Node 24 / pnpm 10.34.5 | 0 | 1 file，10 passed | `apps/web/tests/contracts.test.ts` |
| `corepack pnpm@10.34.5 build` | Node 24 / pnpm 10.34.5 | 0 | TypeScript `--noEmit` + Vite，112 modules | 本轮命令输出 |
| 本地浏览器语义 smoke | Chromium 1440×900 | 0 | official source、start/Policy 文案、pushback、429 capacity/retry 均显示正确；没有“回答已保存”假成功 | `runtime/evidence/m3-03-semantic-fix/`（ignored） |
| 后端 pytest | Python 3.11 | — | NOT_RUN：后端/API/OpenAPI 无改动，本轮不为形式重复全量测试 | 既有 M3-03 247 passed / 2 skipped 记录未改写 |
| `tools/validate_spec.py` | Python 3.11 | 0 | 44/44 passed | `validation-report.md` |
| `scripts/doctor.py --json` | Python 3.11 | 0 | 18 PASS / 0 WARN / 0 FAIL | 本轮命令输出 |
| `sha256sum -c CHECKSUMS.sha256` | coreutils | 0 | 203/203 一致 | `CHECKSUMS.sha256` |

新增测试：

- 真实 429 error envelope 会让 `api.submitAnswer` reject 为 `ApiError(status=429, code=CAPACITY_LIMITED, retryable=true)`，并分类为 `capacity` 而不是 `service`。
- 四种 `source_type` 精确映射；相同 `source_name` 不改变来源类型。
- counterfactual、pushback、reflection 三者显示独立；未知 intent 使用安全 fallback。

实际模型/提示词/题库版本：本轮未调用模型；沿用 SeedBank 0.2.1 事实边界。  
实际调用数/token/费用：业务文本模型调用 0；provider/model/token/cost 均为 null。  
是否有隐式 mock/回放：无隐式 mock。浏览器 smoke 明确使用本地 intercepted fixture response，只验证实际渲染与交互，不冒充 FastAPI 或模型 live。  
仍然失败的样本与最小复现：终态无失败。两次结构化编辑分别残留重复 `else` 和旧 JSX `);`，均由 Edit 解析警告当场定位、重读局部后修正；随后 10 项测试、production build 和浏览器 smoke 均通过。

## 同步与继续

api.md：已检查无变更；本轮是前端对齐既有真实契约。  
process.md：已更新。  
架构/数据/测试/配置/CHANGELOG：测试、UI Contract、验收矩阵、README、CHANGELOG 与 process 已同步；架构、数据、配置均无变化。  
新风险、待负责人事项：无新增 UI/API 漂移；O04 业务文本模型私密配置与费用上限仍未提供，模型 live 继续 NOT_RUN。  
唯一下一任务：负责人提供 O04 后执行 M3-01 业务文本模型 live 验证；本轮不启动 M4。  
继续时先运行的命令：`corepack pnpm@10.34.5 test && corepack pnpm@10.34.5 build`。  
回滚方式：以 `77d703a364cd66529b0e1c92d50116be3272bf98` 为文件级基线，只恢复本交接列出的文件；不得使用 destructive reset/stash。
