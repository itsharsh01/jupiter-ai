from __future__ import annotations

import json
import logging
from typing import Any

from agent.discovery_v2.config import DISCOVERY_JUDGE_THRESHOLD
from agent.discovery_v2.llm import discovery_llm_available, generate_json
from agent.discovery_v2.models import GapAnalysisSnapshot, RiskQueueItem, SessionState
from agent.discovery_v2.priority_queue import queue_item_by_key

logger = logging.getLogger(__name__)

_MAX_WANT_ITEMS = 40
_MAX_HAVE_ITEMS = 30


def _queue_want_list(state: SessionState) -> list[dict[str, Any]]:
    """Fields still open in the priority queue."""
    items: list[dict[str, Any]] = []
    for item in state.queue[:_MAX_WANT_ITEMS]:
        items.append(
            {
                "key": item.key,
                "label": item.label,
                "section": item.section,
                "required": item.required,
                "risk_level": item.risk_level,
                "priority_score": item.priority_score,
                "answer_type": item.answer_type,
            }
        )
    return items


def _collected_have_list(state: SessionState) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for key, entry in list(state.discovered.items())[: _MAX_HAVE_ITEMS]:
        items.append(
            {
                "key": key,
                "value": entry.value,
                "confidence": entry.confidence,
                "source": entry.source,
            }
        )
    return items


def _rule_based_analysis(state: SessionState) -> GapAnalysisSnapshot:
    missing_keys = [item.key for item in state.queue]
    missing_required = [item.key for item in state.queue if item.required]
    filled = state.filled_keys
    total = max(state.total_keys, 1)
    score = round((filled / total) * 100, 1)
    if missing_required:
        score = min(score, 79.0)
    return GapAnalysisSnapshot(
        analyzed_at_turn=state.conversation_turns,
        completeness_score=score,
        missing_keys=missing_keys,
        missing_required=missing_required,
        priority_missing=missing_keys[:3],
        judge_reasoning="Rule-based estimate from queue progress.",
    )


def analyze_discovery_gaps(state: SessionState) -> GapAnalysisSnapshot:
    """
    Compare required discovery fields vs collected facts.
    Returns missing keys and an LLM completeness score (0–100).
    """
    if not state.queue and state.discovered:
        return GapAnalysisSnapshot(
            analyzed_at_turn=state.conversation_turns,
            completeness_score=100.0,
            missing_keys=[],
            missing_required=[],
            priority_missing=[],
            judge_reasoning="All queued fields collected.",
        )

    want = _queue_want_list(state)
    have = _collected_have_list(state)

    if not discovery_llm_available():
        return _rule_based_analysis(state)

    prompt = f"""You are the discovery completeness analyst for an AI governance platform.

Compare what we STILL NEED vs what the customer has ALREADY PROVIDED.

STILL NEEDED (priority queue — ask about these first):
{json.dumps(want, indent=2, default=str)}

ALREADY COLLECTED (stored in database):
{json.dumps(have, indent=2, default=str)}

Tasks:
1. Score overall completeness from 0–100 (80+ means governance discovery is sufficient to proceed).
2. List missing field keys that still need clear, specific answers (not vague).
3. List missing REQUIRED keys only.
4. Pick up to 3 highest-priority missing keys to focus the next question on.

Penalize vague or incomplete collected values (e.g. "yes", "maybe", one-word answers).
Reward concrete, actionable detail.

Return JSON only:
{{
  "completeness_score": 0,
  "missing_keys": ["field.key"],
  "missing_required": ["field.key"],
  "priority_missing": ["field.key"],
  "reasoning": "one or two sentences"
}}"""

    raw = generate_json(
        prompt,
        system=(
            "You judge AI governance discovery completeness. "
            "Be strict about vague answers; prefer specific operational detail."
        ),
    )
    if not isinstance(raw, dict):
        return _rule_based_analysis(state)

    try:
        score = float(raw.get("completeness_score", 0))
    except (TypeError, ValueError):
        score = 0.0
    score = max(0.0, min(100.0, score))

    queue_keys = {item.key for item in state.queue}
    missing_keys = [k for k in (raw.get("missing_keys") or []) if k in queue_keys]
    missing_required = [
        k for k in (raw.get("missing_required") or []) if k in queue_keys and _is_required(state, k)
    ]
    priority_missing = [k for k in (raw.get("priority_missing") or []) if k in queue_keys]

    if not missing_keys:
        missing_keys = list(queue_keys)
    if not missing_required:
        missing_required = [item.key for item in state.queue if item.required]
    if not priority_missing:
        priority_missing = missing_keys[:3]

    return GapAnalysisSnapshot(
        analyzed_at_turn=state.conversation_turns,
        completeness_score=score,
        missing_keys=missing_keys,
        missing_required=missing_required,
        priority_missing=priority_missing,
        judge_reasoning=str(raw.get("reasoning") or "").strip(),
        raw=raw,
    )


def _is_required(state: SessionState, key: str) -> bool:
    item = queue_item_by_key(state.queue, key)
    return bool(item and item.required)


def reorder_queue_for_gaps(state: SessionState, analysis: GapAnalysisSnapshot) -> None:
    """Move missing high-priority keys to the front; keep existing priority scores."""
    if not state.queue or not analysis.priority_missing:
        return

    priority_order = {key: idx for idx, key in enumerate(analysis.priority_missing)}
    missing_set = set(analysis.missing_keys)

    def sort_key(item: RiskQueueItem) -> tuple[int, int, int]:
        if item.key in priority_order:
            tier = 0
            focus_rank = priority_order[item.key]
        elif item.key in missing_set:
            tier = 1
            focus_rank = 999
        else:
            tier = 2
            focus_rank = 999
        return (tier, focus_rank, -item.priority_score)

    state.queue.sort(key=sort_key)
    state.remaining_keys = len(state.queue)
    if state.queue:
        state.current_key = state.queue[0].key


def apply_gap_analysis_to_state(state: SessionState) -> GapAnalysisSnapshot:
    analysis = analyze_discovery_gaps(state)
    state.gap_analysis = analysis
    state.completion_criteria.llm_completeness_score = analysis.completeness_score
    state.completion_criteria.llm_judge_met = (
        analysis.completeness_score >= DISCOVERY_JUDGE_THRESHOLD
        and len(analysis.missing_required) == 0
    )
    reorder_queue_for_gaps(state, analysis)
    return analysis


def gap_focus_item(state: SessionState) -> RiskQueueItem | None:
    """Next queue item after gap-driven reorder."""
    if not state.queue:
        return None
    if state.gap_analysis and state.gap_analysis.priority_missing:
        for key in state.gap_analysis.priority_missing:
            item = queue_item_by_key(state.queue, key)
            if item is not None:
                return item
    return state.queue[0]
