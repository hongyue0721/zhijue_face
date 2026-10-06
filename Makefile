# 职觉 ZhiJue Demo｜本地命令入口
#
# 只登记**真实存在**的目标（docs/11-runbook.md 要求：命令行为必须真实，
# 不把"建议手动做的步骤"包装成一键启动）。未实现的目标一律不写在这里。

SHELL := /bin/bash
API_DIR := services/api
WEB_DIR := apps/web
# 前端使用 PATH 中真实可用的 node/pnpm（版本由 doctor toolchain 画像核对）；
# 不硬编码仓库里不存在的 toolchain/ 目录。
NODE ?= node
PY := $(API_DIR)/.venv/bin/python

.PHONY: help doctor check test test-live lint spec integrity api web dev setup demo-fixture demo-live competition-bundle verify-bundle checksums openapi

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'

doctor: ## 检查环境、锁、校验和与工具链
	cd $(API_DIR) && .venv/bin/python ../../scripts/doctor.py

check: lint test spec integrity doctor ## 本地默认检查（与 CI 语义一致，不花模型费用）

lint: ## Ruff 检查与格式校验（src tests smoke migrations，与 CI 相同范围）
	cd $(API_DIR) && .venv/bin/ruff check src tests smoke migrations
	cd $(API_DIR) && .venv/bin/ruff format --check src tests smoke migrations

test: ## 后端离线回归（显式排除 integration_live，与 CI 一致）
	cd $(API_DIR) && .venv/bin/python -m pytest tests -q -m 'not integration_live'

spec: ## 根规范一致性校验（api.md / OpenAPI / Schema）
	cd $(API_DIR) && .venv/bin/python ../../tools/validate_spec.py

integrity: ## 完整性清单校验
	sha256sum -c CHECKSUMS.sha256

test-live: ## 显式真实 SDK/embedding smoke；需要私密 env 与预算
	@test -n "$${ZHIJUE_KNOWLEDGE_LIVE_ENV_FILE}" || { echo "需要 ZHIJUE_KNOWLEDGE_LIVE_ENV_FILE=<私密 env 路径>"; exit 1; }
	cd $(API_DIR) && ZHIJUE_KNOWLEDGE_LIVE_ENV_FILE=$${ZHIJUE_KNOWLEDGE_LIVE_ENV_FILE} .venv/bin/python -m pytest tests -q -m integration_live

api: ## 启动后端（本机 127.0.0.1:8000，单 worker）
	cd $(API_DIR) && PYTHONPATH=src .venv/bin/python -m zhijue

web: ## 启动前端开发服务器（Vite，/api 代理到 127.0.0.1:8000）
	cd $(WEB_DIR) && $(NODE) node_modules/vite/bin/vite.js --port 5199

dev: ## 提示：分别启动 api 与 web 两个前台进程
	@echo "请分别运行：make api  与  make web（两个前台进程，互不代理启动）"

setup: ## 安装锁定依赖（后端 uv --frozen + 前端 pnpm --frozen-lockfile；零模型调用）
	cd $(API_DIR) && uv sync --frozen --python 3.11
	cd $(WEB_DIR) && pnpm install --frozen-lockfile

demo-fixture: ## 隔离合成环境启动（fixture runtime，剥离模型 env）
	./scripts/demo.sh fixture

demo-live: ## 显式受控 live 配置启动（需私密 env 文件；不自动发送测试请求）
	./scripts/demo.sh live

openapi: ## 重新导出 contracts/openapi.json（路由/DTO 变更后必须执行）
	$(PY) scripts/export_openapi.py

checksums: ## 重新生成 CHECKSUMS.sha256（与 doctor 口径一致）
	$(PY) scripts/write_checksums.py

competition-bundle: ## 生成参赛源码发行包（zip + sha256）
	$(PY) scripts/build_bundle.py

verify-bundle: ## 在干净临时目录复验最新发行包
	./scripts/verify_bundle.sh "$$(ls -t dist/bundles/zhijue-aic-source-*.zip | head -1)"
