# AI 施工交接：2026-09-20 M4-02 PDF 上传待确认事实缺口修复

## 当前状态

工作目录/分支：仓库根目录 / `main`  
基线 commit：`0628aafa18cc0496a6120d1a5a4218e2e55fe878`  
本次 commit：`fix(api): propose source-bound facts on upload`（本文件随最终提交落盘）  
应用版本 / 规范版本：M4-02 / 1.0.0  
当前阶段和任务状态：缺口修复已验证；M4-02 仍为 IMPLEMENTED，负责人独立复验待完成  
运行模式：live；data_mode=synthetic；API 与 Vite 保持 ready

## 本次真实完成

解决的问题及关联 R 编号：负责人在 `/start` 上传真实 PDF 后 Document/SourceBlock 已成功，但待确认事实为 0。根因是 `document.import` 没有 P-EXTRACT，且忽略 `expected_revision`。修复对应既有材料确认、来源可追溯、并发 revision 和真实 openJiuwen Workflow 要求。  
修改文件：`api.md`；`contracts/{README.md,claim-extraction-result.schema.json}`；后端 document repository/service/routes/app、content workflow/model/grounded validation；上传/API/Workflow/model 单测；Start 文案；根/服务 README、架构、数据、Prompt、UX、UI Contract、验收、风险、CHANGELOG、process、validation report 与本交接。  
接口/字段/状态/迁移变化：`POST /profiles/{id}/documents` 路由与 202 envelope 不变；现在强制消费 `expected_revision`。成功 Operation result 增加并冻结 `resource_revision/document_id/extract_status/index_status/proposed_claim_count/extraction_metadata`。新增内部 claim-extraction JSON Schema；服务端拒绝来源不一致及电子邮箱、URL、手机号等联系方式。数据库 Schema、Alembic、OpenAPI 路径/DTO、依赖均无变化。  
有意未修改的内容：不实现 OCR、Memory、批量 Seed、自动确认或评分；扫描 PDF 继续 `requires_text`；上传后 Knowledge 索引仍等待资料确认；不保留原始 PDF 字节。

## 验证证据

| 命令/用例 | 环境 | 退出码 | 通过/失败/未运行 | 证据路径 |
|---|---|---:|---|---|
| 初始两个上传回归 | Python 3.11 / SQLite | 1 | 2 failed：revision 不增长、stale revision 被接受 | `services/api/tests/test_api_contract.py` |
| 专项上传/文档/Workflow/model 回归 | Python 3.11 | 0 | 79 passed / 12 warnings | 对应 tests 文件 |
| Ruff format/check + 全量 pytest | Python 3.11 | 0 | 74 files；281 passed / 2 skipped / 74 warnings | 本交接与 `docs/07-test-and-acceptance.md` |
| Vitest + TypeScript + Vite build | Node 24.21.0 | 0 | 16/16；typecheck 通过；112 modules | `apps/web/tests/contracts.test.ts` |
| `tools/validate_spec.py` | Python 3.11 | 0 | 47/47 passed | `validation-report.md` |
| `scripts/doctor.py --json` | Python 3.11 | 0 | 18 PASS / 0 WARN / 0 FAIL | doctor JSON 输出 |
| `sha256sum -c CHECKSUMS.sha256` + `git diff --check` | GNU coreutils / Git | 0 | 225/225 OK；无空白错误 | `CHECKSUMS.sha256` |
| synthetic 两页 PDF live 上传 | Vite + FastAPI + SQLite + production model + openJiuwen | 0 | revision=1；4 个 proposed Claim；页面显示 4 条待确认事实 | ignored `runtime/acceptance-upload-fix-smoke-20260920T100007Z/business.db`；本次浏览器检查 |
| 重启 owner runtime 并检查 `/start` | live API `:8000` + Vite `:5199` | 0 | 两服务 ready；文件选择控件可用 | ignored `runtime/acceptance-m4-02-owner-fixed-20260920T102600Z/` |

实际模型/提示词/题库版本：`deepseek-flash`；P-EXTRACT `p-extract.1`；claim extraction schema `1.0.0`；SeedBank fingerprint `1c6716b90449d375`；openJiuwen 0.1.18 / compatibility commit `72c4985111b8`。  
实际调用数/token/费用：P-EXTRACT 1 次 HTTP；input 461 / output 658 / total 1119；约 2.86 秒；cost=null。Knowledge/embedding 调用 0。  
是否有隐式 mock/回放：live 证明没有 Mock SDK、Mock model、fixture 或 replay；单元/API 测试中的确定性 generator 均为显式 fixture。  
仍然失败的样本与最小复现：原用户上传不能服务端重放，因为原始 PDF 字节按隐私策略未保留；负责人需在当前空白 runtime 重新上传一次。单个 synthetic 样本不证明真实简历召回率、批量稳定性、p95 或价格。

## 同步与继续

api.md：已先行更新上传、并发、原子提交和 Operation result 语义。  
process.md：已更新 §42。  
架构/数据/测试/配置/CHANGELOG：架构、数据、Prompt、UX、UI Contract、验收、风险、README、CHANGELOG、validation report 与交接已同步；配置、迁移和依赖无变化。  
新风险、待负责人事项：模型只能选择逐字候选，仍可能漏选；空结果会显示 warning，不会技术兜底造事实。需负责人重新上传原 PDF，逐条检查候选与材料是否一致。  
唯一下一任务：在当前 `http://127.0.0.1:5199/start` 重新上传原 PDF，完成独立验收；未通过时保留具体缺失/错误候选再定位，不启动 OCR 或下一阶段。  
继续时先运行的命令：浏览器打开 `http://127.0.0.1:5199/start`；后端 readiness 为 `http://127.0.0.1:8000/api/v1/health/ready`。  
回滚方式：revert 本次 `fix(api): propose source-bound facts on upload` 提交；不执行 reset/stash，不删除 owner runtime。
