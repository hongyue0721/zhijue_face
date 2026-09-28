"""Model output fence handling: outer wrapper tolerated, content still strict."""

import pytest

from zhijue.application.answer_workflow import AnswerWorkflowError, _parse_json_object
from zhijue.application.model_output import unwrap_code_fence


def test_unwrap_only_removes_a_full_outer_fence():
    assert unwrap_code_fence('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert unwrap_code_fence('```\n{"a": 1}\n```') == '{"a": 1}'
    # 正文不是整体栅栏时保持原样，交给严格解析失败，不做“尽力抽取”。
    assert unwrap_code_fence('结果如下：\n{"a": 1}') == '结果如下：\n{"a": 1}'
    assert (
        unwrap_code_fence('```json\n{"a": 1}\n```\n补充说明')
        == '```json\n{"a": 1}\n```\n补充说明'
    )


def test_parser_accepts_fenced_object_and_rejects_fenced_garbage():
    assert _parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    with pytest.raises(AnswerWorkflowError, match="invalid JSON"):
        _parse_json_object('```json\n{"a": 1,,}\n```')
    with pytest.raises(AnswerWorkflowError, match="one JSON object"):
        _parse_json_object("```json\n[1, 2]\n```")
