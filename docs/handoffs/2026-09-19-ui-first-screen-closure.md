# AI 施工交接：2026-09-19 五页首屏收口与展示语义修正

## 当前状态

工作目录/分支：`zhijue-demo-spec-v1.0` / `main`  
基线 commit：`59e509e30291e284c5bfd2f2796b294171f5504a`  
提交分组：`9778e32` 可靠性；`9909f40` Report/Resume；`f64ee1d` Start/Prepare/Interview；本交接、验证报告、测试和完整性清单进入最终证据/文档提交  
应用版本 / 规范版本：Demo / 1.0.0  
任务状态：M4-01 `VERIFIED`；M4-02 功能与五页 Product Polish `IMPLEMENTED`；生产 Content Generator live、负责人独立验收 `NOT_RUN`  
运行模式：浏览器为实际 Vite UI + 显式 synthetic fixture API；未调用 FastAPI 业务写链、外部 LLM 或 embedding

## 本次真实完成

### Operation 与幂等恢复

- `preferObservedOperation` 只允许未观察终态时用新 snapshot 更新；首个 `succeeded / failed / interrupted / canceled` 保持单调，不被迟到 `queued/running` 覆盖。
- `stopOperationTransport` 在终态或页面卸载时同步清理 interval、EventSource 和 in-flight fetch。
- Report improvements、ResumeDraft 创建、Report retry、Resume retry 在请求前持久化 operation-scope recoverable command。网络未得到明确响应时，显式重试复用同一 body、resource ID 和 `Idempotency-Key`；得到 202 或确定不可重试错误才清理。
- 页签、问题、候选事实分页和简历正文选择均为浏览器只读状态。网络捕获中 POST/PUT/PATCH/DELETE 数组为空。

### 五页信息架构

- 共用四步导航“资料 / 准备 / 面试 / 复盘”。Report 激活复盘；Resume 四步全部完成。
- Start：顶部资料计数和“进入面试准备”；左侧材料摘要，右侧按服务端顺序每页 5 条候选事实。手工补充入口始终可用，空候选事实不造示例。
- Prepare：顶部真实岗位/Requirement/五题计数和开始动作；左侧要求与资料覆盖，右侧五题计划。已登记 competency 映射中文，未知值显示“验证方向 N”。
- Interview：完整题面、不用固定高度裁剪；回答 textarea 内部滚动，右侧依据独立滚动，桌面提交动作首屏可见。
- Report：顶部只读服务端总分与计数；左侧五题导航，右侧单题“评分依据 / 回答优化”。Assessment 和改善稿按 `root_question_id` 显式关联；null 不变成 0。
- Resume：左侧可滚动正文，右侧按 `item_id` 显示来源原文、简历表达和改写原因；`claim_id` 只用于映射 `source_claims[].text`，不展示裸 Claim ID。待补/注意先显示计数、详情可展开。
- 用户可见 operation/status、criterion kind/finding/level 全部通过中文展示映射；未知内部值使用中性文案，不原样暴露。
- accepted print media 隐藏页头、操作和审计区，解除屏幕态 height/max-height/overflow，只输出完整正文。

### 修改路径

- 可靠性与契约：`apps/web/src/{api,storage,presentation}.ts`、`apps/web/src/hooks/useOperationMonitor.ts`、`apps/web/tests/contracts.test.ts`。
- 五页：`apps/web/src/pages/{StartPage,PreparePage,InterviewPage,ReportPage,ResumeDraftPage}.tsx`。
- 组件与样式：`apps/web/src/components/{AppShell,profile/ClaimConfirmList}.tsx`、`apps/web/src/styles.css`；删除已失去职责的 `ProfileReadyCard.tsx`、`CoverageMap.tsx`。
- 文档：`docs/{ui-contract,08-ux,07-test-and-acceptance}.md`、`CHANGELOG.md`、`process.md`、`validation-report.md`、本交接和 `CHECKSUMS.sha256`。

HTTP API 已核对无变化：`api.md`、`contracts/openapi.json`、Python DTO、FastAPI routes、数据库 Schema、迁移、依赖和配置均未修改。

## 验证证据

### 回归命令

| 命令/场景 | 环境 | 退出码 | 结果 |
|---|---|---:|---|
| Node 24.21.0 执行 `node_modules/vitest/vitest.mjs run` | 锁定前端依赖 | 0 | 16/16 passed |
| Node 24.21.0 执行 `node_modules/typescript/bin/tsc --noEmit` | 锁定前端依赖 | 0 | TypeScript 通过 |
| Node 24.21.0 执行 `node_modules/vite/bin/vite.js build` | 锁定前端依赖 | 0 | 112 modules transformed |
| `cd services/api && .venv/bin/python -m pytest tests -q` | Python 3.11 项目 venv | 0 | 272 passed / 2 skipped / 0 failed / 73 warnings |
| Ruff format/check | Python 3.11 项目 venv | 0 | 73 files already formatted；All checks passed |
| `services/api/.venv/bin/python tools/validate_spec.py` | Python 3.11 项目 venv | 0 | 46/46 passed |
| `scripts/doctor.py --json`、`sha256sum -c CHECKSUMS.sha256`、`git diff --check` | 项目根目录 | 0 | doctor 18 PASS / 0 WARN / 0 FAIL；221/221 OK；无空白错误 |

### 两轮浏览器视觉

最终截图位于 ignored 的 `runtime/evidence/ui-first-screen-closure/`，五页各有 1366×768 与 390×844，共 10 张。全部数据为 synthetic，不含真实简历、真实回答、密钥或服务器绝对路径。

| 视口 | 结果 |
|---|---|
| 1366×768 | Start `189–241`、Prepare `189–241`、Interview `647–699`、Report `685–727`、Resume `194–236`；五个主 CTA 均在初始视口；横向溢出 0 |
| 1440×900 | CTA 依次为 `189–241 / 189–241 / 845–897 / 807–849 / 194–236`；全部初始可见；横向溢出 0 |
| 1920×1080 | CTA 依次为 `189–241 / 189–241 / 845–897 / 807–849 / 194–236`；全部初始可见；横向溢出 0 |
| 390×844 | 五页横向溢出 0；Start/Prepare/Resume CTA 初始可见；Interview/Report CTA 分别位于页面 `1093–1145`、`1219–1261`，根页面可滚动到达 |
| 125% / 200% | 以 1093×614、683×384 等效布局视口验证；五页横向溢出 0，主 CTA 均可通过页面滚动到达 |

第一轮发现并修复 AnyUI 全局 `html/body height:100vh` 导致移动端根页面不能滚动，以及 Resume print 仍继承屏幕高度/overflow 会裁剪正文。修复后执行第二轮最终截图、坐标和滚动检查。

### 压力输入与语义状态

- 21 条事实：Start 列表 `clientHeight=550 / scrollHeight=764`。
- 17 条 JD：Prepare 展开后 `540/1334`。
- 6,000 字回答：textarea `108/3184`，计数 `6000 / 6000`，提交按钮底部 `698.77`。
- 五题报告：改善详情 `386/446`；切换问题和页签零写入。
- 20 条简历正文：预览 `560/1570`；条目切换零写入。
- Report 响应注入：null 显示“未形成总分/本次回答信息不足”，score=0 显示“0 分”。改善稿 failed 保持失败并显示错误。
- Resume 响应注入：generation failed 显示“草稿生成失败”，不出现可确认/可打印假状态。
- accepted print emulation：heading/audit `display:none`；正文 `display:block`、宽 1366、height auto、overflow visible、无横向溢出。

## 模型、成本与边界

外部 LLM 调用 0，embedding 调用 0，provider/model/usage/cost 均为 null。fixture 证明前端状态、布局、关联和浏览器网络行为，不证明生产 Content Generator 的质量、延迟、429/timeout、usage/cost 或负责人验收。

M4-02 因此保持 `IMPLEMENTED`，不写 `VERIFIED/ACCEPTED`。下一任务只有生产 Content Generator 的受控 live 与负责人独立验收；开始前仍需明确 O04 持续费用上限。不自动扩展 M5。

回滚以 `59e509e30291e284c5bfd2f2796b294171f5504a` 为文件级基线，按四个职责提交逆序恢复；不使用 destructive reset/stash，不覆盖后续用户修改。
