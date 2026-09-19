"""Alembic 运行环境。

数据库 URL 来自 ZHIJUE_DATABASE_URL（默认 runtime/business.db）；alembic.ini 不
硬编码可用 URL，防止误连真实数据。业务库与测试库必须使用不同文件/内存库。
"""

import os
import sys
from logging.config import fileConfig
from pathlib import Path

from alembic import context
from sqlalchemy import engine_from_config, pool

API_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(API_ROOT / "src"))

from zhijue.adapters.db.models import Base

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

DEFAULT_URL = f"sqlite:///{API_ROOT.parent.parent / 'runtime' / 'business.db'}"
# 优先级：调用方已设置的 sqlalchemy.url（测试程序化注入）> ZHIJUE_DATABASE_URL > runtime 默认。
# 绝不覆盖已有 URL，否则测试会误伤真实库。
url = (
    config.get_main_option("sqlalchemy.url")
    or os.environ.get("ZHIJUE_DATABASE_URL")
    or DEFAULT_URL
)
config.set_main_option("sqlalchemy.url", url)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,  # SQLite ALTER 限制走 batch 模式
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
