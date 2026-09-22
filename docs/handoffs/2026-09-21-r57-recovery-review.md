# AI 施工交接：2026-09-21 / §57

## 当前状态

工作目录/分支：`zhijue-demo-spec-v1.0` / `feature/web-ui-redesign`  
基线 commit：`85d4b1f5630be12af798f0aad3da3052baec91dc`  
本次 commit 或尚未提交的文件：负责人 2026-09-21 授权提交后，本轮改动已落盘为 `321e079`（fix(api)）、`2a86fc7`（fix(web)）及 docs 提交（见 `git log`）；提交前保留负责人原有工作区，未做 reset/stash。主要改动见 `apps/web/src`、`services/api/src`、`services/api/migrations/versions`、前后端测试及本交接列出的契约文档。
应用版本 / 规范版本：Demo / 契约 1.0.0  
当前阶段和任务状态：`process.md §57` IMPLEMENTED；负责人独立验收 NOT_RUN  
运行模式：live

## 本次真实完成

解决的问题及关联 R 编号：`process.md §57` 的 R57-01—R57-15：无版本历史库迁移、计划/start 终态循环、删除/control 失败锁死、Operation 404 永久轮询、服务端恢复权威、动态 path 编码与坏路由、Drawer 分页/焦点、重复 JD、失败详情、readiness 重检、错误呈现、键盘/reduced-motion、契约真值和回归缺口。  
修改文件：

- 后端启动/迁移：`services/api/src/zhijue/api/app.py`、`routes.py`、`application/interviews.py`、`adapters/db/migrations.py`、五个 Alembic revision；
- 前端恢复/交互：`apps/web/src/App.tsx`、`api.ts`、`routing.ts`、`presentation.ts`、`jdSections.ts`、`storage.ts`、`hooks/useOperationMonitor.ts`、五个页面及 ErrorNotice/ServiceNotice/DocumentBlocksDrawer/FactModal/ClaimConfirmList/DocumentStatus/JDInput；
- 回归：`services/api/tests/unit/test_migrations.py`、`test_api_contract.py`、`test_interview_runtime.py`、`apps/web/tests/*.test.ts`；
- 契约/证据：`api.md`、`contracts/README.md`、`docs/03-data-model.md`、`docs/07-test-and-acceptance.md`、`docs/08-ux.md`、`docs/ui-contract.md`、`docs/10-doc-sync.md`、`process.md`、`CHANGELOG.md`、`tools/validate_spec.py`、本交接。

接口/字段/状态/迁移变化：HTTP path、字段、错误码、SSE 事件和业务枚举无变化；客户端对不透明 path segment 统一 percent-encode。应用启动改为业务仓储打开前执行 Alembic；历史无版本完整初始 Schema 可接管，部分 Schema 拒绝。live 库已迁到 `e62a9f8c10bd`。  
有意未修改的内容：模型/embedding provider、Prompt、Seed/Rubric/Policy、Knowledge 链路、移动端、外部响应 type generation；后者已把文档改成当前真值，继续由精确 shape/OpenAPI snapshot 测试与 TypeScript 编译守卫，不冒称已生成。

## 验证证据

| 命令/用例 | 环境 | 退出码 | 通过/失败/未运行 | 证据路径 |
|---|---|---:|---|---|
| `.venv/bin/python -m pytest tests -q -m 'not integration_live'` | Python 3.11 / SQLite | 0 | 321 passed，2 deselected，96 warnings | `runtime/evidence/r57-recovery-review/verification.json` |
| `.venv/bin/ruff check src tests smoke migrations && .venv/bin/ruff format --check src tests smoke migrations` | services/api venv | 0 | 79 files | 同上 |
| `pnpm test && pnpm build` | Node 24.21.0 / pnpm 10.34.5 | 0 | 25/25；TypeScript；Vite 116 modules | 同上 |
| `tools/validate_spec.py` | Python 3.11 | 0 | 47/47 | `validation-report.md` |
| `scripts/doctor.py --json` | Python 3.11 | 0 | 18 PASS / 0 WARN / 0 FAIL | 命令输出、`process.md §57` |
| `sha256sum -c CHECKSUMS.sha256` | Linux | 0 | 237/237 OK | `CHECKSUMS.sha256` |
| `git diff --check` | Git worktree | 0 | 无空白错误 | 命令输出 |
| live 历史库迁移 + start | API 8000 / Vite 5180 | 0 | 迁移 head；5 Question；3 个 null seed；面试 active | `runtime/evidence/r57-recovery-review/verification.json` |
| Chromium 13 条恢复/失败/键盘场景 | 1365×768 managed Chromium | 0 | 全部观察项通过 | 同上、`process.md §57` |

实际模型/提示词/题库版本：本轮未调用模型；既有版本未改。  
实际调用数/token/费用：0 / null / null  
是否有隐式 mock/回放：无隐式回放。live 迁移/start 使用真实 API/SQLite；不可重试、404、readiness、分页和焦点边界使用浏览器 request interception 显式注入受控响应，不证明模型效果。  
仍然失败的样本与最小复现：无已知未修复样本。移动端/缩放、生产模型质量/延迟/费用和负责人独立验收 NOT_RUN。

## 同步与继续

api.md：已更新；无 HTTP 字段变化，修正“生成类型”失实声明。  
process.md：已更新 §57，状态 IMPLEMENTED。  
架构/数据/测试/配置/CHANGELOG：`docs/03-data-model.md`、`docs/07-test-and-acceptance.md`、`docs/08-ux.md`、`docs/ui-contract.md`、`docs/10-doc-sync.md`、`contracts/README.md`、`CHANGELOG.md` 已同步；配置与依赖无变化。  
新风险、待负责人事项：负责人独立体验尚未执行；前端响应类型仍手工维护，但当前文档和守卫已如实反映，不把未建立的 codegen 当完成。  
唯一下一任务：负责人在当前 live 页面独立执行“修改/生成岗位计划 → 开始模拟面试”，确认错误恢复和交互体验后决定是否 ACCEPTED。  
继续时先运行的命令：`cd services/api && .venv/bin/python -m pytest tests -q -m 'not integration_live'`，然后在 `apps/web` 用锁定 Node 24 执行 `pnpm test && pnpm build`。  
回滚方式：本轮以三个独立提交落盘，可分别 `git revert`；live 数据库需要回退时先停止 API，保留当前库，再使用 0600 备份 `services/api/runtime/backups/business-pre-r57-20260921.db`。不得在服务运行中覆盖数据库。
