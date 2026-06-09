from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from agent.discovery_v2.config import (
    CONFIDENCE_POP_THRESHOLD,
    DISCOVERY_JUDGE_THRESHOLD,
    MIN_AVG_CONFIDENCE_COMPLETE,
)
from agent.discovery_v2.models import (
    CheckConfidenceResult,
    DiscoveredEntry,
    FactPatch,
    PeekQueueResult,
    RiskQueueItem,
    SessionState,
    UIHint,
)
from agent.discovery_v2.priority_queue import (
    INTERNAL_FLAG_PREFIX,
    INTERNAL_UNLOCK_FLAGS,
    PRIORITY_QUEUE_TEMPLATE,
    clone_session_queue,
    queue_item_by_key,
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def init_session_state(session_id: str) -> SessionState:
    queue = clone_session_queue()
    now = _now_iso()
    total = len(queue)
    return SessionState(
        session_id=session_id,
        started_at=now,
        last_updated_at=now,
        queue=queue,
        total_keys=total,
        remaining_keys=total,
        current_key=queue[0].key if queue else None,
    )


_TEMPLATE_INDEX: dict[str, RiskQueueItem] | None = None


def _unlock_key_to_item(key: str) -> RiskQueueItem | None:
    global _TEMPLATE_INDEX
    if _TEMPLATE_INDEX is None:
        from agent.discovery_v2.priority_queue import build_queue_from_template

        _TEMPLATE_INDEX = {i.key: i for i in build_queue_from_template()}
    return _TEMPLATE_INDEX.get(key)


def _insert_unlocked_items(state: SessionState, keys: list[str]) -> None:
    existing = {item.key for item in state.queue}
    discovered = set(state.discovered.keys())
    for key in keys:
        if key.startswith(INTERNAL_FLAG_PREFIX):
            flag = key.replace(INTERNAL_FLAG_PREFIX, "")
            if flag not in state.high_risk_flags_triggered:
                state.high_risk_flags_triggered.append(flag)
            continue
        if key in existing or key in discovered:
            continue
        item = _unlock_key_to_item(key)
        if item is None:
            continue
        state.queue.append(item)
        state.queue.sort(key=lambda x: x.priority_score, reverse=True)
        state.total_keys += 1
        state.remaining_keys = len(state.queue)
        existing.add(key)


def _apply_unlocks(state: SessionState, patch: FactPatch, item: RiskQueueItem | None) -> None:
    if item is None or not item.unlocks_on:
        return
    trigger = str(patch.value).lower() if isinstance(patch.value, bool) else str(patch.value)
    if isinstance(patch.value, bool):
        trigger = "true" if patch.value else "false"
    keys = item.unlocks_on.get(trigger) or item.unlocks_on.get(str(patch.value))
    if keys:
        _insert_unlocked_items(state, keys)


def apply_patches(state: SessionState, patches: list[FactPatch]) -> list[str]:
    filled: list[str] = []
    turn = state.conversation_turns

    for patch in patches:
        state.discovered[patch.key] = DiscoveredEntry(
            value=patch.value,
            confidence=patch.confidence,
            source=patch.source,
            turn_discovered=turn,
        )
        item = queue_item_by_key(state.queue, patch.key)
        _apply_unlocks(state, patch, item)

        if patch.confidence >= CONFIDENCE_POP_THRESHOLD:
            before = len(state.queue)
            state.queue = [q for q in state.queue if q.key != patch.key]
            if len(state.queue) < before:
                state.filled_keys += 1
                filled.append(patch.key)

    state.remaining_keys = len(state.queue)
    if state.total_keys:
        state.completion_pct = round(state.filled_keys / state.total_keys, 4)
    state.last_updated_at = _now_iso()
    return filled


def peek_queue(state: SessionState, previous_section: str | None = None) -> PeekQueueResult:
    if not state.queue:
        return PeekQueueResult(next_item=None, remaining_count=0, section_changed=False)

    from agent.discovery_v2.gap_analysis import gap_focus_item

    next_item = gap_focus_item(state) or state.queue[0]
    section_changed = bool(previous_section and previous_section != next_item.section)
    return PeekQueueResult(
        next_item=next_item,
        remaining_count=len(state.queue),
        section_changed=section_changed,
        section_intro_needed=next_item.section if section_changed else None,
    )


def check_confidence(state: SessionState) -> CheckConfidenceResult:
    current = state.current_key
    should_pop = False
    if current and current in state.discovered:
        should_pop = state.discovered[current].confidence >= CONFIDENCE_POP_THRESHOLD

    confidences = [e.confidence for e in state.discovered.values()]
    avg_conf = sum(confidences) / len(confidences) if confidences else 0.0
    state.completion_criteria.confidence_met = avg_conf >= MIN_AVG_CONFIDENCE_COMPLETE

    required_remaining = [q for q in state.queue if q.required]
    critical_remaining = [q for q in state.queue if q.risk_level == "CRITICAL"]
    state.completion_criteria.all_required_filled = len(required_remaining) == 0
    state.completion_criteria.all_critical_gaps_resolved = len(critical_remaining) == 0

    gap = state.gap_analysis
    llm_judge_complete = bool(
        gap
        and gap.completeness_score >= DISCOVERY_JUDGE_THRESHOLD
        and len(gap.missing_required) == 0
        and state.completion_criteria.confidence_met
        and len(state.discovered) > 0
    )
    if gap:
        state.completion_criteria.llm_completeness_score = gap.completeness_score
        state.completion_criteria.llm_judge_met = llm_judge_complete

    queue_empty = len(state.queue) == 0
    rule_complete = (
        state.completion_criteria.all_required_filled
        and state.completion_criteria.confidence_met
        and queue_empty
    )

    complete = llm_judge_complete or (
        rule_complete and state.completion_criteria.all_critical_gaps_resolved
    )

    state.discovery_complete = complete
    return CheckConfidenceResult(
        should_pop=should_pop,
        should_cross_question=False,
        discovery_complete=complete,
        completion_pct=state.completion_pct,
    )


def build_ui_hint(item: RiskQueueItem | None) -> UIHint | None:
    if item is None:
        return None
    if item.answer_type == "boolean":
        return UIHint(
            interaction_type="boolean",
            field_key=item.key,
            label=item.label,
        )
    if item.answer_type in ("enum",):
        return UIHint(
            interaction_type="single_select",
            field_key=item.key,
            label=item.label,
            allowed_values=item.allowed_values,
            min_selections=1,
            max_selections=1,
        )
    if item.answer_type == "multi_enum":
        return UIHint(
            interaction_type="multi_select",
            field_key=item.key,
            label=item.label,
            allowed_values=item.allowed_values,
            min_selections=1,
        )
    if item.answer_type == "tool_registry":
        return UIHint(
            interaction_type="tool_registry",
            field_key=item.key,
            label=item.label,
            min_selections=1,
        )
    if item.answer_type == "document_upload":
        return UIHint(
            interaction_type="document_upload",
            field_key=item.key,
            label=item.label,
            max_selections=5,
        )
    return UIHint(
        interaction_type="text",
        field_key=item.key,
        label=item.label,
    )


def patches_from_structured_answers(
    answers: dict[str, Any],
    turn: int,
) -> list[FactPatch]:
    patches: list[FactPatch] = []
    for key, value in answers.items():
        patches.append(
            FactPatch(
                key=key,
                value=value,
                confidence=0.95,
                source="structured",
            )
        )
    return patches


def already_known_summary(state: SessionState, limit: int = 12) -> dict[str, Any]:
    items = list(state.discovered.items())[-limit:]
    return {k: v.value for k, v in items}
