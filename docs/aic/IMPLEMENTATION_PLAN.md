# AIC 参赛收口与岗位知识包｜实施计划与接手审计

状态：IN_PROGRESS。规格权威版本为 `ZhiJue_AIC_AGENT_MASTER.md`（2026-09-25）。
本文件只登记实际基线、核对结论、修改范围与阶段门槛，不替代 `api.md` 作为接口语义真源。

## 1. 实际接手基线（2026-09-25 实测）

- HEAD：`d91023ac10cd50a766284f05300b2e817b120`（与文档审查基线一致，main...origin/main 同步）。
- 接手时工作区干净，无用户未提交修改；本轮所有变更均为本任务实施内容。
- 审查基线后无新提交，因此 R01–R10 按原基线核对全部适用，不存在“已修复问题被再次改坏”的回避项。
- 接手实测（修复前）：
  - `pytest tests -q -m 'not integration_live'`：**324 passed / 2 failed / 2 deselected**。
  - 两个失败项即 R01 复现：`test_doctor_real_workspace_passes_and_leaks_no_secret` 直接读真实 `.env.local`（干净 checkout 必然 FileNotFoundError）；`test_real_run_details_have_no_absolute_paths` 因 doctor 对缺失 `toolchain/VERSIONS.txt` 判 FAIL 而返回 1。本机确实无 `.env.local`、无 `toolchain/`。
  - `ruff check src tests smoke migrations`：接手即通过（业务 `src` 本身无 lint 债务，问题只在 CI 未覆盖 `src`）。
  - CI（`.github/workflows/ci.yml`）：Ruff 只查 `smoke tests`；`pytest tests -q` 未按 marker 显式排除 live；顶部“尚未推送 / NOT_RUN”注释过时。
- 修复后基线（Phase 1，2026-09-25 实测）：
  - `pytest tests -q -m 'not integration_live'`：**329 passed / 2 deselected / 0 failed**。
  - `ruff check / format --check src tests smoke migrations`：通过（80 files）。
  - `tools/validate_spec.py`：47/47。
  - `scripts/doctor.py`（offline 档）：exit 0，10 PASS / 5 WARN / 0 FAIL（WARN 均为本工作区事实：无 .env.local、无 runtime/、Node/pnpm 版本漂移、清单待收尾重建）。
  - `pnpm install --frozen-lockfile`、`pnpm test`（25/25）、`pnpm build`：通过。
  - `sha256sum -c CHECKSUMS.sha256`：246/246（收尾重建后）。
- 远端 CI：本轮未获推送授权，状态为 **本地基线通过 / REMOTE_CI_PENDING**，不写远端已绿。

## 2. R01–R10 核对结论（对照实际代码）

| ID | 结论 | 代码证据 |
|---|---|---|
| R01 | 成立，Phase 1 已修复 | `services/api/tests/test_doctor.py`（原 L31–46 读真实 env）；`scripts/doctor.py` toolchain FAIL 分支；`ci.yml` lint 范围 |
| R02 | 成立，作为设计约束 | `docs/05-knowledge-and-bank.md §4`；`SeedBank` 为 JSON 校验加载（`seed_bank.py:156–194`），无向量路径。岗位包导入零模型/embedding 调用 |
| R03 | 成立 | `domain/requisition.py:223–236` `_COMPETENCY_RULES`；`application/requisition.py:47–114` 直接/相关证据关键词；`domain/questions.py:24–25,66–86` RTOS 家族映射 → 封装为显式 `CompetencyProfile=embedded-junior-v1`，未知 profile 明确拒绝 |
| R04 | 成立 | `seed_bank.py:108–122` `version_fingerprint()` 仅覆盖 id/version → 新增服务端 canonical `content_digest` |
| R05 | 成立 | `api/app.py` 装配唯一 `SeedBank`（live_only=True）；`interviews.py:427–430` `start_interview` 消费 `self._seed_bank` → 最迟在 POST /interviews 受理时冻结 `pack_release_id + content_digest`，plan/start/retry/重启/报告同源解析 |
| R06 | 成立 | `seed_bank.py:92–98` `live_eligible()` 信任包内 `review_status` → 服务端审核记录表绑定 digest；上传包默认 unreviewed；内置六条经迁移只继承原审批范围 |
| R07 | 成立 | React/Vite/自研 `routing.ts`，`workspace.css` 白底蓝操作；仅新增 `/knowledge-packs` 与准备页选择区，不换框架不重做五页 |
| R08 | 成立 | `api.md §3` 候选人视图裁剪已有约定；新 DTO 必须服务端裁剪 rubric/reference_points/参考答案 |
| R09 | 成立 | `process.md §60`：openEuler 证据仅 24.03-LTS-SP2 x86_64 容器用户空间 fixture 启动+最小写入；不外推；新增代码后需复验才更新日期/状态 |
| R10 | 成立 | `build_services` 启动即装载 SeedBank；知识页列表/详情/导入/操作恢复不依赖模型与候选人 embedding，无可用包只阻断面试创建 |

## 3. 修改范围（按阶段）

- Phase 1（已完成）：`scripts/doctor.py`、`services/api/tests/test_doctor.py`、`.github/workflows/ci.yml`、`Makefile`、`CHECKSUMS.sha256`。
- Phase 2–3：`services/api/src/zhijue/domain/knowledge_packs.py`、`application/knowledge_packs.py`、`adapters/db/knowledge_packs.py`、`contracts/knowledge_pack.schema.json`、`knowledge_packs/embedded_software_junior/`、Alembic 新 revision、`seed_bank.py`/`questions.py`/`requisition.py` 的 profile 封装与包解析接入。
- Phase 4：`api/routes.py`/`schemas.py`/新增 `api/knowledge_packs.py`、Operation kind 联合与 runner 分发、`api.md`、`contracts/openapi.json`。
- Phase 5：`apps/web/src/routing.ts`、新增 `pages/KnowledgePacksPage.tsx` 与组件、`PreparePage` 包选择区、`api.ts`、`storage.ts`（导入命令恢复键）、`styles.css/workspace.css` 作用域扩展、`docs/ui-contract.md`。
- Phase 6：Makefile 启动/打包目标、README、bundle 脚本与解包复验。

## 4. 迁移与回滚策略

- 新表/新列全部 nullable 或带默认，旧记录允许 `pack_release_id IS NULL` → 读取路径标 `legacy_unresolved`，保留原报告/冻结题目，不重算旧分数、不删会话。
- Alembic 单向 upgrade；downgrade 仅删新表/新列，不触碰既有业务行。先在旧库副本验证（副本文件 + `sqlite3 .backup`），真实业务库迁移未获授权 = NOT_RUN。
- 回滚点：每阶段一个可独立 revert 的提交集合；Phase 3 绑定字段为增量列，回滚代码但保留 schema 不破坏旧读取路径。

## 5. 阶段门槛（与主文件 Gate 对齐）

1. Gate 1 离线基线可复现、既有断言不被削弱 —— 已达成（本地）。
2. Gate 2 包契约/安全/审核/digest/能力边界测试通过。
3. Gate 3 API、面试绑定、迁移、重启、retry 通过。
4. Gate 4 新页与原五页真实浏览器通过。
5. Gate 5 独立发行包解压复验通过。
6. Gate 6 live/OS 复验：无授权则单列 NOT_RUN，不阻塞其余交付。
7. Gate 7 负责人验收：由负责人执行，Agent 不得自标 ACCEPTED。

## 6. 权限边界（本轮适用）

不执行：付费模型调用、真实业务库迁移、批准新知识、公网发布、git push/远端发布。
允许：隔离 runtime 下的离线/fixture 测试、构建、bundle 解包验证、合成数据端到端。
有 API key ≠ 有授权；上述未执行项一律 NOT_RUN 单列。
