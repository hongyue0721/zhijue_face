# 职觉 ZhiJue Demo｜本地命令入口
#
# 只登记**真实存在**的目标（docs/11-runbook.md 要求：命令行为必须真实，
# 不把"建议手动做的步骤"包装成一键启动）。未实现的目标一律不写在这里。

SHELL := /bin/bash
API_DIR := services/api
WEB_DIR := apps/web
NODE_BIN := $(CURDIR)/toolchain/node24/bin
PY := $(API_DIR)/.venv/bin/python

.PHONY: help doctor check test test-live lint api web dev

help:
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN{FS=":.*?## "}{printf "  %-12s %s\n", $$1, $$2}'

doctor: ## 检查环境、锁、校验和与工具链
	cd $(API_DIR) && .venv/bin/python ../../scripts/doctor.py

check: lint test ## 本地默认检查（不花模型费用）

lint: ## Ruff 检查与格式校验
	cd $(API_DIR) && .venv/bin/ruff check src tests smoke
	cd $(API_DIR) && .venv/bin/ruff format --check src tests smoke

test: ## 后端全量测试（不含显式 live）
	cd $(API_DIR) && .venv/bin/python -m pytest tests -q

test-live: ## 显式真实 SDK/embedding smoke；需要私密 env 与预算
	@test -n "$${ZHIJUE_KNOWLEDGE_LIVE_ENV_FILE}" || { echo "需要 ZHIJUE_KNOWLEDGE_LIVE_ENV_FILE=<私密 env 路径>"; exit 1; }
	cd $(API_DIR) && ZHIJUE_KNOWLEDGE_LIVE_ENV_FILE=$${ZHIJUE_KNOWLEDGE_LIVE_ENV_FILE} .venv/bin/python -m pytest tests -q -m integration_live

api: ## 启动后端（本机 127.0.0.1:8000，单 worker）
	cd $(API_DIR) && PYTHONPATH=src .venv/bin/python -m zhijue

web: ## 启动前端开发服务器（Vite，/api 代理到 127.0.0.1:8000）
	cd $(WEB_DIR) && $(NODE_BIN)/node node_modules/vite/bin/vite.js --port 5199

dev: ## 提示：分别启动 api 与 web 两个前台进程
	@echo "请分别运行：make api  与  make web（两个前台进程，互不代理启动）"
