# AI 施工交接：2026-09-22 前端重构迁移包接入

## 当前状态

工作目录/分支：`/home/hongyue/Projects/ZhiJue_Demo_Engineering_Spec_v1.0/zhijue-demo-spec-v1.0` / `migration/frontend-refactor-package-20260922`
基线 commit：包基线 `85d4b1f5630be12af798f0aad3da3052baec91dc`；目标施工前 HEAD `f09feb4840db68cbee2f35e1f85efc70dd598dc7`（前者为后者祖先）
本次实现 commit：`b3a7bdf`、`d6497ff`、`4f93832`；文档同步见其后提交
应用版本 / 规范版本：Demo P0；契约 1.0.0；openJiuwen 0.1.18
当前阶段和任务状态：迁移实现与本地验证完成，`IMPLEMENTED`；负责人独立验收 `NOT_RUN`
运行模式：`fixture / synthetic`；生产模型 `NOT_RUN`

## 本次真实完成

解决的问题及关联 R 编号：迁移包没有源码、测试或 evidence，仅有一份交接 overlay。本轮在目标仓库审计后落实交互方向：独立上传 modal、真实等待骨架、正式页面只收用户 JD、常见显式 JD 标题解析，以及完整浏览器恢复验证。未新增 PRD R 编号。
修改文件：

- 包原样迁入：`docs/handoffs/frontend-redesign-migration.md`，SHA-256 `39234f798bce3e0d784df6329a61693a39a8f24be43e1fea54f306adec3ad708`；
- 前端新增：`apps/web/src/components/common/ModalDialog.tsx`、`apps/web/src/components/profile/UploadModal.tsx`；
- 前端修改：`apps/web/src/components/profile/DocumentUpload.tsx`、`DocumentStatus.tsx`、`FactModal.tsx`、`apps/web/src/components/prepare/JDInput.tsx`、`apps/web/src/pages/StartPage.tsx`、`PreparePage.tsx`、`apps/web/src/styles.css`；
- 后端与测试：`services/api/src/zhijue/domain/requisition.py`、`services/api/tests/unit/test_planning.py`；
- 文档：`api.md`、`process.md`、`docs/08-ux.md`、`docs/ui-contract.md`、`docs/07-test-and-acceptance.md`、`CHANGELOG.md`、本交接、`CHECKSUMS.sha256`、`validation-report.md`。

接口/字段/状态/迁移变化：HTTP 路径、snake_case 字段、错误码、SSE、OpenAPI、数据库 Schema、Alembic revision 与依赖均未变化。`Operation.error.retryable` 仍是原字段，但读取与执行统一按当前受限预算判断；正式 Prepare 页面不再暴露演示 JD 按钮，省略 JD 的 `SYNTHETIC_DEMO_JD` API 语义仍保留给显式 fixture/直接客户端。
有意未修改的内容：Operation/revision/幂等/恢复协议、四步面试导航、后端单写入方、生产模型配置、Knowledge 生产适配器、Seed/Prompt/Rubric/Policy、移动端产品范围。

## 验证证据

| 命令/用例 | 环境 | 退出码 | 通过/失败/未运行 | 证据路径 |
|---|---|---:|---|---|
| 包 manifest SHA-256 校验与 `apply_overlay.py --dry-run` | Linux；随附包 | 0 | 13/13 匹配；拟合并 1、删除 0 | 包 `FILE_MANIFEST.json`、`status.json`、`DELIVERY_SUMMARY.md` |
| `.venv/bin/python -m pytest tests -q -m 'not integration_live'` | Python 3.11.16 | 0 | 326 passed / 2 deselected / 96 warnings | `docs/07-test-and-acceptance.md` |
| `.venv/bin/ruff check src tests smoke migrations && .venv/bin/ruff format --check src tests smoke migrations` | Ruff / 80 files | 0 | All checks passed | 同上 |
| `pnpm --config.use-node-version=24.21.0 test && pnpm --config.use-node-version=24.21.0 build` | Node 24.21.0 / pnpm 10.34.5 | 0 | 25/25；TypeScript；Vite 118 modules | 同上 |
| PDF→事实→用户 JD→五题/追问→报告优化→简历确认/打印媒体 | Chromium 受控浏览器；Vite→真实 FastAPI/SQLite/openJiuwen Workflow | 0 | 通过 | `runtime/frontend-refactor-migration/verification.json`、9 张 synthetic 截图 |
| 后端接受后丢响应、选择保留、原命令重试、处理中刷新 | 同上；仅在响应阶段用 CDP 主动断开 | 0 | 通过；同一 operation 恢复并 ready | 同上 |
| modal / 1,367 字 / null 与真 0 / 响应式 | 1366×768、1440×900、1366×600、200% 缩放等效 683×384 | 0 | 无横向溢出；焦点/关闭路径通过；null 与 0 分开 | `runtime/frontend-refactor-migration/02-upload-modal.png`、`11-long-text-dialog.png`、`12-15` 截图 |
| `tools/validate_spec.py` / `scripts/doctor.py --json` | Python 3.11.16 | 0 | 47/47；18 PASS / 0 WARN / 0 FAIL | `validation-report.md`、控制台 |
| `sha256sum -c CHECKSUMS.sha256` / `git diff --check` | GNU coreutils / Git | 0 | 245/245；无空白错误 | `CHECKSUMS.sha256` |

实际模型/提示词/题库版本：未调用生产 provider/model；Analyzer 与 Content Generator 为显式 scripted fixture；Seed bank health 版本 `1c6716b90449d375`；Prompt/Seed/Rubric/Policy 未修改。
实际调用数/token/费用：外部模型 HTTP 调用 0；token usage `null`；cost `null`。
是否有隐式 mock/回放：没有前端模拟成功响应；后端明确为 fixture/synthetic，Knowledge 为 InMemory adapter。lost-response 场景只丢弃真实 FastAPI 已接受命令的响应，不伪造成功响应。
仍然失败的样本与最小复现：无已知回归失败。headless Chromium 无法观察原生系统打印对话框；已验证 accepted 门禁、打印动作存在及 print media 隐藏页头/解除 overflow。生产模型/Knowledge、真实简历、真实 JD、费用/延迟与负责人独立验收均 `NOT_RUN`。

## 同步与继续

api.md：已更新；明确正式 UI、受控 `SYNTHETIC_DEMO_JD` API 边界及当前重试语义。
process.md：已更新 §58—§59。
架构/数据/测试/配置/CHANGELOG：架构与数据无变化；UX/UI Contract、测试记录、CHANGELOG、完整性清单和 validation report 已同步。
新风险、待负责人事项：迁移包不是源码交付，实际实现由本轮在目标仓库完成；生产模型与真实材料仍需负责人独立复验，不能从 fixture 分数推断效果。
唯一下一任务：负责人在隔离 live 配置中使用确认 JD 与 Demo Resume v1 复验同一纵切面，再决定是否 `ACCEPTED`。
继续时先运行的命令：`cd apps/web && pnpm --config.use-node-version=24.21.0 test && pnpm --config.use-node-version=24.21.0 build`。
回滚方式：回退本分支尚未提交的上述文件；保留目标施工前 HEAD `f09feb4840db68cbee2f35e1f85efc70dd598dc7`。不得 reset/stash/覆盖其他工作。
