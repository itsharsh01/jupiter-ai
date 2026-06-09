from __future__ import annotations

from agent.discovery_v2.models import FactPatch
from agent.discovery_v2.state_ops import check_confidence, init_session_state
from agent.discovery_v2.tools.parse_answer import _is_vague_answer


def test_vague_answer_detection():
    from agent.discovery_v2.priority_queue import queue_item_by_key

    state = init_session_state("vague-1")
    item = queue_item_by_key(state.queue, state.current_key)
    assert _is_vague_answer("yes", item) is True
    assert _is_vague_answer("maybe", item) is True
    assert (
        _is_vague_answer(
            "We use LangGraph with human approval on all payment tools in production.",
            item,
        )
        is False
    )


def test_llm_judge_completes_discovery():
    from agent.discovery_v2.models import DiscoveredEntry, GapAnalysisSnapshot

    state = init_session_state("judge-1")
    state.queue = []
    state.remaining_keys = 0
    state.discovered["system_profile.business_purpose"] = DiscoveredEntry(
        value="Customer support chatbot for retail banking.",
        confidence=0.92,
        source="customer_stated",
    )
    state.gap_analysis = GapAnalysisSnapshot(
        completeness_score=85.0,
        missing_keys=[],
        missing_required=[],
        priority_missing=[],
    )
    result = check_confidence(state)
    assert result.discovery_complete is True
    assert state.completion_criteria.llm_judge_met is True
