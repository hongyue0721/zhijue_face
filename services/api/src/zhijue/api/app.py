"""应用装配：配置加载 → 依赖构造 → 路由挂载（唯一进程内服务容器）。

docs/02 §7 与 AGENTS §13：业务状态只有一个权威写入路径。本模块构造**唯一的**
Engine / Repository / Service 组合；测试通过 `create_app(overrides=...)` 注入
临时库与内存 Knowledge 端口，不复制一套并行构造逻辑。

run_mode 契约（config/demo.yaml + api.md §7）：live 模式下 embedding 配置缺失
时 readiness 必须 not_ready，不得自动回退 fixture。
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from openjiuwen.core.common.logging.log_config import (
    configure_log_config,
    get_log_config_snapshot,
)
from sqlalchemy import Engine

from zhijue.adapters.db.documents import DocumentRepository
from zhijue.adapters.db.engine import make_engine
from zhijue.adapters.db.models import Base
from zhijue.adapters.db.operations import OperationRepository
from zhijue.adapters.db.profiles import ProfileRepository
from zhijue.adapters.model import (
    OpenAICompatibleAnswerAnalyzer,
    load_model_settings,
)
from zhijue.api.errors import RequestContext, install_error_handlers
from zhijue.api.events import router as events_router
from zhijue.api.routes import router
from zhijue.application.answer_workflow import AnswerAnalyzer
from zhijue.application.documents import DocumentService
from zhijue.application.interviews import InterviewService
from zhijue.application.operations_runner import OperationRunner
from zhijue.application.profiles import KnowledgeGateway, ProfileService
from zhijue.application.reporting import ReportingService
from zhijue.application.requisition import JDPlanningService
from zhijue.application.seed_bank import load_seed_bank
from zhijue.domain.extraction import ExtractionLimits

REPO_ROOT = next(
    (
        parent
        for parent in Path(__file__).resolve().parents
        if (parent / "config").is_dir()
    ),
    None,
)


@dataclass
class AppConfig:
    """应用配置：来自 config/demo.yaml 与显式环境变量，缺失不猜。"""

    run_mode: str = "fixture"
    database_url: str = "sqlite:///./runtime/business.db"
    runtime_dir: Path = Path("runtime")
    milvus_uri: Path = Path("runtime/knowledge.db")
    embedding_env_file: Path | None = None
    model_env_file: Path | None = None
    retrieval_top_k: int = 4
    api_workers: int = 1
    limits: ExtractionLimits = field(default_factory=ExtractionLimits)
    max_queued_operations: int = 8
    answer_workflow_timeout_seconds: float = 60
    data_mode: str = "synthetic"

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> AppConfig:
        env = dict(os.environ if env is None else env)
        runtime_dir = Path(env.get("ZHIJUE_RUNTIME_DIR", "./runtime"))
        embedding_env = env.get("ZHIJUE_EMBEDDING_ENV_FILE")
        model_env = env.get("ZHIJUE_MODEL_ENV_FILE")
        return cls(
            run_mode=env.get("ZHIJUE_RUN_MODE", "fixture"),
            database_url=env.get(
                "ZHIJUE_DATABASE_URL", f"sqlite:///{runtime_dir}/business.db"
            ),
            runtime_dir=runtime_dir,
            milvus_uri=Path(
                env.get("ZHIJUE_MILVUS_URI", str(runtime_dir / "knowledge.db"))
            ),
            embedding_env_file=Path(embedding_env) if embedding_env else None,
            model_env_file=Path(model_env) if model_env else None,
            api_workers=int(env.get("ZHIJUE_API_WORKERS", "1")),
            data_mode=env.get("ZHIJUE_DATA_MODE", "synthetic"),
        )

    def ensure_directories(self) -> None:
        """启动前建立运行目录：SQLite 与 Milvus Lite 都要求父目录已存在。

        缺失时直接失败而非静默换路径——数据库位置属于部署事实，不能猜。
        """
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        if self.database_url.startswith("sqlite:///"):
            database_path = Path(self.database_url.removeprefix("sqlite:///"))
            if database_path.parent != Path(""):
                database_path.parent.mkdir(parents=True, exist_ok=True)
        self.milvus_uri.parent.mkdir(parents=True, exist_ok=True)


@dataclass
class Services:
    """进程内唯一服务容器；HTTP 层只从这里取依赖。"""

    config: AppConfig
    engine: Engine
    documents: DocumentService
    profiles: ProfileService
    interviews: InterviewService
    reports: ReportingService
    operations: OperationRepository
    runner: OperationRunner
    _ready: bool = False
    _readiness: dict[str, Any] = field(default_factory=dict)

    @property
    def ready(self) -> bool:
        return self._ready

    def readiness_details(self) -> dict[str, Any]:
        return dict(self._readiness)


def _configure_private_sdk_logging() -> None:
    """Keep answer/resume payloads out of SDK INFO logs and local log files."""
    sdk_logging = get_log_config_snapshot()
    sdk_logging["level"] = "WARNING"
    for output_key in ("output", "interface_output", "performance_output"):
        sdk_logging[output_key] = ["console"]
    configure_log_config(sdk_logging)


def build_services(
    config: AppConfig,
    *,
    knowledge: KnowledgeGateway | None = None,
    analyzer: AnswerAnalyzer | None = None,
) -> Services:
    _configure_private_sdk_logging()
    config.ensure_directories()
    engine = make_engine(config.database_url, wal=False)
    Base.metadata.create_all(engine)
    document_repo = DocumentRepository(engine)
    profile_repo = ProfileRepository(engine)
    operation_repo = OperationRepository(engine)
    readiness: dict[str, Any] = {
        "run_mode": config.run_mode,
        "data_mode": config.data_mode,
        "database": "sqlite",
        "knowledge": "configured" if knowledge is not None else "absent",
        "model": "configured" if analyzer is not None else "absent",
    }
    if config.run_mode == "live":
        # live 缺少真实配置必须 not_ready；不自动回退 fixture（environment.env.example 首行约定）。
        ready = knowledge is not None and analyzer is not None
        if not ready:
            readiness["reason"] = "live 模式缺少 Knowledge/embedding 或模型配置"
    else:
        ready = True
    planner = JDPlanningService(engine=engine)
    seed_bank = load_seed_bank(
        (REPO_ROOT or Path(".")) / "data" / "seeds",
        live_only=True,
    )
    readiness["seed_bank_version"] = seed_bank.version_fingerprint()
    reporting = ReportingService(engine=engine, operations=operation_repo)
    return Services(
        config=config,
        engine=engine,
        interviews=InterviewService(
            engine=engine,
            planner=planner,
            operations=operation_repo,
            reporting=reporting,
            seed_bank=seed_bank,
            analyzer=analyzer,
            workflow_timeout_seconds=config.answer_workflow_timeout_seconds,
        ),
        documents=DocumentService(
            engine=engine, repo=document_repo, limits=config.limits
        ),
        profiles=ProfileService(repo=profile_repo, knowledge=knowledge),
        operations=operation_repo,
        reports=reporting,
        runner=OperationRunner(
            engine=engine,
            repo=operation_repo,
            max_queued=config.max_queued_operations,
        ),
        _ready=ready,
        _readiness=readiness,
    )


def build_knowledge_gateway(config: AppConfig) -> KnowledgeGateway | None:
    """只有显式给出私密 env 文件时才构造真实 Knowledge；否则返回 None（readiness 自会体现）。"""
    if config.embedding_env_file is None:
        return None
    from zhijue.adapters.knowledge import OpenJiuwenKnowledgeGateway, load_settings

    settings = load_settings(config.embedding_env_file)
    return OpenJiuwenKnowledgeGateway(
        settings=settings, milvus_uri=config.milvus_uri, top_k=config.retrieval_top_k
    )


def build_model_analyzer(
    config: AppConfig,
) -> OpenAICompatibleAnswerAnalyzer | None:
    """Only an explicitly selected private env file enables the business model."""
    if config.model_env_file is None:
        return None
    settings = load_model_settings(config.model_env_file)
    return OpenAICompatibleAnswerAnalyzer(settings)


def create_app(
    config: AppConfig | None = None,
    *,
    knowledge: KnowledgeGateway | None = None,
    analyzer: AnswerAnalyzer | None = None,
) -> FastAPI:
    resolved = config or AppConfig.from_env()
    services = build_services(resolved, knowledge=knowledge, analyzer=analyzer)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        interrupted = services.operations.mark_interrupted_on_restart()
        services.interviews.recover_interrupted_operations(interrupted)
        yield
        gateway = app.state.knowledge
        if gateway is not None and hasattr(gateway, "close"):
            await gateway.close()

    app = FastAPI(title="ZhiJue Demo API", version="1.0.0", lifespan=lifespan)
    app.state.services = services
    app.state.knowledge = knowledge

    @app.middleware("http")
    async def _attach_context(request: Request, call_next):
        request.state.context = RequestContext()
        return await call_next(request)

    install_error_handlers(app)
    app.include_router(router)
    app.include_router(events_router)
    return app


def create_default_app() -> FastAPI:
    """Production entry reads only explicitly selected private configuration files."""
    config = AppConfig.from_env()
    knowledge = build_knowledge_gateway(config)
    analyzer = build_model_analyzer(config)
    return create_app(config, knowledge=knowledge, analyzer=analyzer)
