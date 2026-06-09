from __future__ import annotations

from agent.discovery_v2.gap_analysis import (
    _rule_based_analysis,
    reorder_queue_for_gaps,
)
from agent.discovery_v2.models import GapAnalysisSnapshot
from agent.discovery_v2.state_ops import init_session_state


def test_rule_based_gap_analysis_empty_discovered():
    state = init_session_state("gap-1")
    analysis = _rule_based_analysis(state)
    assert analysis.completeness_score < 80
    assert analysis.missing_required
    assert len(analysis.missing_keys) == len(state.queue)


def test_reorder_queue_puts_priority_missing_first():
    state = init_session_state("gap-2")
    first_key = state.queue[0].key
    last_key = state.queue[-1].key
    analysis = GapAnalysisSnapshot(
        missing_keys=[last_key, first_key],
        missing_required=[last_key],
        priority_missing=[last_key],
        completeness_score=40.0,
    )
    reorder_queue_for_gaps(state, analysis)
    assert state.queue[0].key == last_key


def test_gap_analysis_stored_on_state():
    from agent.discovery_v2.gap_analysis import apply_gap_analysis_to_state

    state = init_session_state("gap-3")
    analysis = apply_gap_analysis_to_state(state)
    assert state.gap_analysis is not None
    assert state.gap_analysis.completeness_score == analysis.completeness_score
    assert state.completion_criteria.llm_completeness_score == analysis.completeness_score
