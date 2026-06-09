from __future__ import annotations

from unittest.mock import patch

from agent.audit.orchestrator import GenerationResult, generate_all_strategies


@patch("agent.audit.orchestrator._generate_strategy")
def test_generate_all_strategies_aggregates(mock_gen):
    mock_gen.side_effect = [
        ([{"test_case_id": "1", "strategy": "governance", "user_prompt": "a", "title": "t"}], None, 0.82, 1),
        ([], "No graph context for strategy 'ai_risk'", 0.0, 0),
        ([{"test_case_id": "2", "strategy": "tool_abuse", "user_prompt": "b", "title": "t2"}], None, 0.78, 2),
        ([], "No graph context", 0.0, 0),
        ([], "No graph context", 0.0, 0),
    ]
    result = generate_all_strategies("cust-1")
    assert len(result.test_cases) == 2
    assert result.strategies_generated == ["governance", "tool_abuse"]
    assert len(result.strategies_skipped) == 3
