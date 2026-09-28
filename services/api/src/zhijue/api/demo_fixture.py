"""fixture 演示实例入口（make demo-fixture）：隔离合成环境，零模型调用。

- Knowledge 端口 = 内存合成回执；不连 Milvus/embedding，不读任何私密 env。
- 回答分析 = 脚本化 analyzer，只产出受约束 Observation 候选，编排仍走安装版
  openJiuwen Workflow —— 与离线契约测试同一语义，页面状态全部来自真实服务。
- 内容生成（回答优化/简历草稿）不提供：相应流程按契约显式 SERVICE_NOT_READY，
  不预录成功结果。
- run_mode=fixture、data_mode=synthetic 在 readiness/runtime info 中如实报告；
  演示数据是合成事实，不是真实候选人。
"""

from __future__ import annotations

import json
from typing import Any

from zhijue.application.answer_workflow import AnalysisResult
from zhijue.application.profiles import ActivationReceipt


class SyntheticKnowledgeGateway:
    """确定性内存 Knowledge：索引即回执，检索返回空（合成环境无真实语料）。"""

    async def index_snapshot(self, *, profile_id, generation, sources):
        return ActivationReceipt(
            generation=generation,
            source_ids=[source.source_id for source in sources],
            document_ids=[source.source_id for source in sources],
            embedding_logical_calls=0,
        )

    async def search(self, **kwargs: Any) -> list[dict[str, Any]]:
        return []

    async def drop_profile(self, *, profile_id: str, source_ids: list[str]) -> int:
        return len(source_ids)


class ScriptedDemoAnalyzer:
    """fixture 分析端口：按冻结 Rubric 生成合格 Observation 候选（合成回答路径）。"""

    max_total_attempts = 3

    async def analyze(self, **inputs: Any) -> AnalysisResult:
        rubric_snapshot = inputs["rubric_snapshot"]
        answer_text = str(inputs["answer_text"])
        reference_ids = list(rubric_snapshot.get("reference_ids") or ())
        criteria = []
        for frozen in rubric_snapshot["rubric"]:
            technical = frozen["kind"] == "technical"
            criteria.append(
                {
                    "criterion_id": frozen["criterion_id"],
                    "kind": frozen["kind"],
                    "weight": frozen["weight"],
                    "level": 2,
                    "finding": "supported",
                    "answer_quotes": [
                        {"answer_id": inputs["answer_id"], "exact_quote": answer_text}
                    ],
                    "knowledge_refs": reference_ids if technical else [],
                    "explanation": "fixture 合成环境：仅基于本轮回答与冻结评价快照。",
                }
            )
        observation = {
            "schema_version": "1.0.0",
            "id": inputs["observation_id"],
            "answer_id": inputs["answer_id"],
            "question_id": inputs["question_id"],
            "root_question_id": inputs["root_question_id"],
            "relevance": "relevant",
            "knowledge_status": "adequate",
            "criteria": criteria,
            "clarification_needed": False,
            "validation_flags": [],
        }
        return AnalysisResult(content=json.dumps(observation, ensure_ascii=False))


def build_demo_app():
    """显式合成环境：即使宿主 shell 里有私密 env 也一律不读取。"""
    from zhijue.api.app import AppConfig, create_app

    config = AppConfig.from_env()
    config = AppConfig(
        **{
            **config.__dict__,
            "run_mode": "fixture",
            "data_mode": "synthetic",
            "embedding_env_file": None,
            "model_env_file": None,
        }
    )
    return create_app(
        config,
        knowledge=SyntheticKnowledgeGateway(),
        analyzer=ScriptedDemoAnalyzer(),
        generator=None,
    )


def main() -> None:
    import os

    import uvicorn

    host = os.environ.get("ZHIJUE_API_HOST", "127.0.0.1")
    port = int(os.environ.get("ZHIJUE_API_PORT", "8000"))
    uvicorn.run(build_demo_app(), host=host, port=port, workers=1, log_level="info")


if __name__ == "__main__":
    main()
