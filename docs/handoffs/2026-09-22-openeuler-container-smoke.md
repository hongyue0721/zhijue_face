# AI 施工交接：2026-09-22 / OS-SMOKE

## 当前状态

工作目录/分支：仓库根目录 / `main`  
基线 commit：`1c6a519`（`origin/main`）  
本次 commit 或尚未提交的文件：本文件所在提交；修改 `process.md`、`docs/07-test-and-acceptance.md`、`CHANGELOG.md`、`validation-report.md`、`CHECKSUMS.sha256`  
应用版本 / 规范版本：Demo / 1.0.0  
当前阶段和任务状态：`OS-SMOKE`，`VERIFIED`（仅 openEuler 容器用户空间范围）  
运行模式：`fixture / synthetic`

## 本次真实完成

解决的问题及关联 R 编号：执行 T33 / R19 的国产系统环境冒烟；确认项目能在 openEuler 24.03 LTS-SP2 x86_64 容器用户空间安装锁定依赖、迁移、启动并完成最小前后端写入。  
修改文件：仅文档、静态校验报告与完整性清单；没有修改业务代码。  
接口/字段/状态/迁移变化：无。应用启动时实际执行既有 Alembic migration 到 `e62a9f8c10bd`，没有新增或修改 migration。  
有意未修改的内容：业务源码、OpenAPI、依赖锁、配置、数据库 Schema、模型/Knowledge 接线。

实际镜像：官方 `openeuler/openeuler:24.03-lts-sp2`，拉取摘要 `sha256:990f5a8528dc3375a358629bcb5500351f433a49922dca3588bcf32ecc5b7022`。容器共享 Arch Linux 宿主内核，因此本结果不能称为统信 UOS、麒麟、鸿蒙或国产 CPU 原生适配。

## 验证证据

| 命令/用例 | 环境 | 退出码 | 通过/失败/未运行 | 证据路径 |
|---|---|---:|---|---|
| `docker manifest inspect openeuler/openeuler:24.03-lts-sp2` | Docker 29.8.1 / 29.7.2 | 0 | 官方 manifest 含 amd64/arm64/loong64；本轮选择 amd64 | 本文件、`process.md §60` |
| `docker pull openeuler/openeuler:24.03-lts-sp2` | linux/amd64 | 0 | 拉取摘要 `990f5a...` | 本文件、`process.md §60` |
| 临时 Dockerfile `docker build --network host` | openEuler 24.03 LTS-SP2 | 0 | Python/uv/Node/pnpm 工具链镜像构建成功 | 本文件、`process.md §60` |
| `uv sync --locked --no-dev --python python3` | Python 3.11.6 / uv 0.12.10 | 0 | 194 项解析；175 个运行包检查通过；openJiuwen 锁定 commit 构建成功 | 本文件、`process.md §60` |
| `pnpm install --frozen-lockfile` | Node 24.21.0 / pnpm 10.34.5 | 0 | 133 项安装成功 | 本文件、`process.md §60` |
| 容器启动 `python -m zhijue` | fixture / 临时 SQLite | 0（服务 ready 后受控停止） | 五段 migration；FastAPI ready | 本文件、`process.md §60` |
| 容器启动 Vite | 真实项目 cwd，代理到同容器 API | 0（服务 ready 后受控停止） | `/start` 与代理 readiness 可访问 | 本文件、`docs/07-test-and-acceptance.md` T33 |
| Chromium `/start` | 1440×900 | 0 | 标题、上传和手工填写入口可见 | 本文件、`process.md §60` |
| 页面提交 synthetic 手工经历 | React → Vite proxy → FastAPI → SQLite | 0 | 新 Profile；页面显示待确认 1 / 已确认 0 | 本文件、`process.md §60` |
| 清理临时资源 | Docker + 仓库外 `/tmp` | 0 | 容器、临时/基础镜像、5 个数据/缓存卷、构建目录已删除 | 本文件、`process.md §60` |

实际模型/提示词/题库版本：未调用模型；seed bank `1c6716b90449d375`。  
实际调用数/token/费用：模型 0 次；embedding 0 次；usage/cost 为 `null`。  
是否有隐式 mock/回放：无回放；运行模式显式为 fixture，Knowledge/Analyzer/Generator 未作为 live 证明。  
仍然失败的样本与最小复现：统信 UOS、麒麟、鸿蒙、国产 CPU、完整桌面/打印和 live Knowledge/模型均 `NOT_RUN`。

失败尝试：宿主 bridge veth 不可用，改用 host network；PyPI/GitHub 下载中断，经持久缓存、低并发与 Git HTTP/1.1 后成功；临时脚本只读 pnpm 工作区和错误 Vite cwd 分别造成 EROFS 与监控 `/proc` 导致 OOM，修正验证脚本后未改项目源码即通过；一次测试端口占用后改用隔离高位端口。

## 同步与继续

api.md：已检查无变化；HTTP/API 契约未改。  
process.md：已更新 §1、任务板、O03 和 §60。  
架构/数据/测试/配置/CHANGELOG：`docs/07-test-and-acceptance.md` T33 与 `CHANGELOG.md` 已更新；架构、数据和配置无变化。  
新风险、待负责人事项：赛事国产 OS 具体版本、CPU 架构、应用形态和证明材料仍未确认。禁止把本轮 openEuler 容器结果表述为“统信 UOS 验证完成”。  
唯一下一任务：取得正式目标环境口径；若指定统信 UOS，在对应版本和架构上复跑启动与纵切面。  
继续时先运行的命令：`git status --short --branch`，然后确认目标 OS 的 `/etc/os-release`、CPU 架构、容器/原生要求与网络条件。  
回滚方式：回退本文件所在文档提交；没有业务代码、数据库或配置需要回滚。
