# AI 施工交接：2026-09-19 PUBLIC-01

## 当前状态

工作目录/分支：仓库根 / `main`  
基线 commit：公开历史根提交 `7d3694a`  
本次 commit 或尚未提交的文件：首次公开 push 为 `7d3694a → 449375e → 554b78d → a678d6a`；本交接与同步记录随后单独提交  
应用版本 / 规范版本：Demo / 1.0.0  
当前阶段和任务状态：PUBLIC-01 `VERIFIED`；业务阶段仍为 M3 `IN_PROGRESS`  
运行模式：本地验证 + GitHub public repository；业务文本模型 live `NOT_RUN`

## 本次真实完成

解决的问题及关联 R 编号：将连续 M2/M3 工作区整理为可审阅提交，并以不包含旧本地历史的干净 `main` 发布公开仓库。  
修改文件：公开分支最终覆盖 170 个受完整性清单管理的工程资产；新增本交接并同步 process/CHANGELOG/CHECKSUMS。  
接口/字段/状态/迁移变化：发布动作没有新增业务 API、Schema 或迁移；发布前纠正前端 Question.kind 为后端真实的 `main / probe / clarification`。  
有意未修改的内容：未设计 M3-03 答题界面；未运行业务文本模型 live；未推送本地 `master` 历史。

公开仓库：<https://github.com/hongyue0721/zhijue_face>。GitHub 返回 `visibility=PUBLIC`、默认分支 `main`；远端只有 `refs/heads/main`。

隐私边界：`.env.local`、`runtime/`、真实简历原件、官方资料 PDF 和运行证据继续 Git ignored。公开历史中不含工作站绝对路径、私有简历文件名、身份标签或内容指纹。M2-02 私有输入 smoke 改为强制显式 `ZHIJUE_DEMO_RESUME_*` 配置，不扫描 Downloads 或硬编码本地文件。

本地 `master` 作为发布前回退点保留但**未推送**；其中包含发布前的历史记录，不得直接推到公开 remote。公开协作只使用 `main`。

## 验证证据

| 命令/用例 | 环境 | 退出码 | 通过/失败/未运行 | 证据路径 |
|---|---|---:|---|---|
| `.venv/bin/ruff format --check smoke src tests migrations && .venv/bin/ruff check smoke src tests migrations && .venv/bin/python -m pytest tests -q` | Python 3.11.16 | 0 | 62 files；247 passed / 2 skipped / 0 failed / 54 warnings | 控制台输出、`services/api/tests/` |
| `.venv/bin/python ../../tools/validate_spec.py` | 项目 venv | 0 | 44/44 passed | `validation-report.md` |
| `corepack pnpm@10.34.5 --dir apps/web run build` | Node 24 / pnpm 10.34.5 | 0 | TypeScript `--noEmit` + Vite build；29 modules | `apps/web/` |
| `.venv/bin/python ../../scripts/doctor.py --json` | 项目 venv | 0 | 18 PASS / 0 WARN / 0 FAIL | 控制台输出 |
| `sha256sum -c CHECKSUMS.sha256` | Linux | 0 | 170/170 matched | `CHECKSUMS.sha256` |
| `gh repo view hongyue0721/zhijue_face --json ...` | GitHub CLI | 0 | PUBLIC；default branch `main` | GitHub API |
| `git ls-remote --heads origin` | HTTPS remote | 0 | 仅 `refs/heads/main`，HEAD 与本地一致 | Git remote |
| `git log main -S<private marker>` 三组历史扫描 | clean public history | 0 | 工作站路径、私有简历标签、私有指纹均 0 命中 | 本地 Git 历史 |

前端构建失败尝试保留：第一次 PATH 中没有 `pnpm`，exit 127；第二次裸 `corepack pnpm` 选择 pnpm 12.4.2，与项目锁定 10.34.5 冲突，exit 1；显式 `corepack pnpm@10.34.5` 后通过。没有放宽版本约束。

实际模型/提示词/题库版本：发布任务没有模型调用；业务现状仍为 Seed 0.2.1、Policy 1.0.0、外部回答模型 `NOT_RUN`。  
实际调用数/token/费用：外部模型调用 0；token/cost 为 null。  
是否有隐式 mock/回放：发布验证无 mock/replay；既有 M3 fixture 边界见 M3 handoff。  
仍然失败的样本与最小复现：最终验证无失败；两次前端命令配置失败如上，均已用锁定版本闭合。

## 同步与继续

api.md：已检查，发布动作无 API 变化。  
process.md：已更新公开仓库、分支、提交和验证事实。  
架构/数据/测试/配置/CHANGELOG：CHANGELOG、环境模板、隐私说明、交接和 CHECKSUMS 已同步；无依赖变化。  
新风险、待负责人事项：业务模型六个显式私密配置仍缺；M3-03 前端答题、control/end、T23 浏览器断流恢复和 M4 报告仍未完成。  
唯一下一任务：M3-03 前端答题界面设计评审。  
继续时先运行的命令：`git switch main && git pull --ff-only && cd services/api && .venv/bin/python -m pytest tests/test_interview_runtime.py -q`。  
回滚方式：本地 `master` 保留发布前完整回退点；公开 `main` 使用 `git revert` 新提交回滚，不 force-push、不重写已发布历史。仓库删除属于负责人显式 GitHub 管理动作，本轮不执行。
