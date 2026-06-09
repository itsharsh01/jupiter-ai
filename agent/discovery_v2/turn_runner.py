from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from agent.discovery_v2.completion import generate_completion
from agent.discovery_v2.copy import LLM_UNAVAILABLE_NOTICE
from agent.discovery_v2.intent import build_clarification
from agent.discovery_v2.llm import llm_was_degraded
from agent.discovery_v2.models import ParseAnswerResult, SessionState, TurnHistoryEntry, TurnResponse
from agent.discovery_v2.session_store import SessionStore
from agent.discovery_v2.state_ops import (
    apply_patches,
    build_ui_hint,
    patches_from_structured_answers,
)
from agent.discovery_v2.gap_analysis import apply_gap_analysis_to_state
from agent.discovery_v2.tools.check_confidence import check_confidence_tool
from agent.discovery_v2.tools.generate_question import generate_question_tool, stream_generate_question
from agent.discovery_v2.tools.parse_answer import parse_answer_tool
from agent.discovery_v2.tools.peek_queue import peek_queue_tool

_store = SessionStore()


def _event(name: str, data: dict[str, Any]) -> dict[str, Any]:
    return {"event": name, "data": data}


def _progress_payload(state: SessionState) -> dict[str, Any]:
    return {
        "completion_pct": state.completion_pct,
        "remaining_keys": state.remaining_keys,
        "conversation_turns": state.conversation_turns,
    }


def _stream_question_events(
    target,
    state: SessionState,
    *,
    is_cross_question: bool = False,
    section_intro_needed: str | None = None,
) -> Iterator[dict[str, Any]]:
    """Stream assistant_message (and optional notice) SSE events for one question."""
    for phase, content in stream_generate_question(
        target,
        state,
        is_cross_question=is_cross_question,
        section_intro_needed=section_intro_needed,
    ):
        yield _event("assistant_message", {"content": content, "phase": phase})
    if llm_was_degraded():
        yield _event(
            "notice",
            {"content": LLM_UNAVAILABLE_NOTICE, "kind": "llm_unavailable"},
        )


def _append_history(
    state: SessionState,
    question: str,
    answer: str,
    keys_filled: list[str],
) -> None:
    state.turn_history.append(
        TurnHistoryEntry(
            turn=state.conversation_turns,
            question_asked=question,
            user_answer=answer,
            keys_filled=keys_filled,
        )
    )
    if len(state.turn_history) > state.max_history_turns:
        state.turn_history = state.turn_history[-state.max_history_turns :]


def iter_turn_events(
    session_id: str,
    *,
    message: str | None = None,
    answers: dict[str, Any] | None = None,
) -> Iterator[dict[str, Any]]:
    session = _store.load_session(session_id)
    state = _store.get_state(session)
    user_text = message or ""
    if answers:
        user_text = ", ".join(f"{k}={v}" for k, v in answers.items())

    session["conversation"].append({"role": "user", "content": user_text})
    state.conversation_turns += 1

    yield _event("status", {"phase": "processing", "message": "Processing your response..."})

    previous_section = None
    if state.current_key:
        from agent.discovery_v2.priority_queue import queue_item_by_key

        item = queue_item_by_key(state.queue, state.current_key)
        previous_section = item.section if item else None

    last_question = state.turn_history[-1].question_asked if state.turn_history else ""

    if message and not answers:
        clarification = build_clarification(state.current_key, message)
        if clarification:
            session["conversation"].append({"role": "assistant", "content": clarification})
            _store.set_state(session, state)
            _store.save_session(session)
            yield _event("clarification", {"content": clarification})
            response = TurnResponse(
                session_id=session_id,
                assistant_message=clarification,
                current_key=state.current_key,
                completion_pct=state.completion_pct,
                remaining_keys=state.remaining_keys,
                discovery_complete=False,
                ui_hint=build_ui_hint(state.queue[0] if state.queue else None),
                response_type="clarification",
            )
            yield _event("done", response.model_dump(mode="json"))
            return

    yield _event("status", {"phase": "parsing", "message": "Extracting facts from your answer..."})

    if answers:
        parse_result = ParseAnswerResult(
            patches=patches_from_structured_answers(answers, state.conversation_turns)
        )
    else:
        parse_result = parse_answer_tool(user_text, state)

    for flag in parse_result.risk_flags_detected:
        if flag not in state.high_risk_flags_triggered:
            state.high_risk_flags_triggered.append(flag)

    keys_filled = apply_patches(state, parse_result.patches)
    yield _event("progress", _progress_payload(state))

    yield _event("status", {"phase": "analyzing", "message": "Reviewing what we still need..."})
    gap = apply_gap_analysis_to_state(state)
    yield _event(
        "gap_analysis",
        {
            "completeness_score": gap.completeness_score,
            "missing_count": len(gap.missing_keys),
            "missing_required_count": len(gap.missing_required),
            "priority_missing": gap.priority_missing[:3],
        },
    )
    yield _event("progress", _progress_payload(state))

    if (
        parse_result.needs_cross_question
        and state.cross_question_count < state.max_cross_questions
        and state.queue
    ):
        state.cross_question_count += 1
        target = state.queue[0]
        from agent.discovery_v2.gap_analysis import gap_focus_item

        focus = gap_focus_item(state)
        if focus is not None:
            target = focus
            state.current_key = focus.key
        yield _event("status", {"phase": "generating", "message": "Preparing a follow-up question..."})
        question = ""
        for ev in _stream_question_events(target, state, is_cross_question=True):
            if ev["event"] == "assistant_message":
                phase = ev["data"].get("phase")
                if phase == "final":
                    question = ev["data"]["content"]
            yield ev
        if not question:
            question = generate_question_tool(target, state, is_cross_question=True)
        notices = []
        if llm_was_degraded():
            notices.append(LLM_UNAVAILABLE_NOTICE)
            session["conversation"].append(
                {"role": "assistant", "content": LLM_UNAVAILABLE_NOTICE}
            )
        _append_history(state, last_question or target.label, user_text, keys_filled)
        session["conversation"].append({"role": "assistant", "content": question})
        _store.set_state(session, state)
        _store.save_session(session)
        response = TurnResponse(
            session_id=session_id,
            assistant_message=question,
            current_key=state.current_key,
            completion_pct=state.completion_pct,
            remaining_keys=state.remaining_keys,
            discovery_complete=False,
            ui_hint=build_ui_hint(target),
            notices=notices,
        )
        yield _event("done", response.model_dump(mode="json"))
        return

    state.cross_question_count = 0
    peek = peek_queue_tool(state, previous_section=previous_section)
    check = check_confidence_tool(state)

    if check.discovery_complete or not state.queue:
        outputs = generate_completion(state)
        state.discovery_complete = True
        summary = (
            f"{outputs.system_summary}\n\n"
            "Discovery is complete. Retrieve the full report from GET .../completion."
        )
        session["completion_outputs"] = outputs.model_dump(mode="json")
        session["conversation"].append({"role": "assistant", "content": summary})
        _append_history(state, last_question, user_text, keys_filled)
        _store.set_state(session, state)
        _store.save_session(session)
        yield _event("assistant_message", {"content": summary, "phase": "final"})
        response = TurnResponse(
            session_id=session_id,
            assistant_message=summary,
            current_key=None,
            completion_pct=1.0,
            remaining_keys=0,
            discovery_complete=True,
            ui_hint=None,
            response_type="complete",
        )
        yield _event("done", response.model_dump(mode="json"))
        return

    if peek.next_item is None:
        assistant_message = "Thank you — your governance profile is nearly complete."
        session["conversation"].append({"role": "assistant", "content": assistant_message})
        _store.set_state(session, state)
        _store.save_session(session)
        yield _event("assistant_message", {"content": assistant_message, "phase": "final"})
        response = TurnResponse(
            session_id=session_id,
            assistant_message=assistant_message,
            current_key=None,
            completion_pct=state.completion_pct,
            remaining_keys=0,
            discovery_complete=state.discovery_complete,
        )
        yield _event("done", response.model_dump(mode="json"))
        return

    state.current_key = peek.next_item.key
    yield _event("status", {"phase": "generating", "message": "Composing your next question..."})

    question = ""
    for ev in _stream_question_events(
        peek.next_item,
        state,
        is_cross_question=False,
        section_intro_needed=peek.section_intro_needed,
    ):
        if ev["event"] == "assistant_message":
            phase = ev["data"].get("phase")
            if phase == "final":
                question = ev["data"]["content"]
        yield ev

    if not question:
        question = generate_question_tool(
            peek.next_item, state, section_intro_needed=peek.section_intro_needed
        )

    notices = []
    if llm_was_degraded():
        notices.append(LLM_UNAVAILABLE_NOTICE)
        session["conversation"].append(
            {"role": "assistant", "content": LLM_UNAVAILABLE_NOTICE}
        )

    _append_history(state, last_question or peek.next_item.label, user_text, keys_filled)
    session["conversation"].append({"role": "assistant", "content": question})
    _store.set_state(session, state)
    _store.save_session(session)

    response = TurnResponse(
        session_id=session_id,
        assistant_message=question,
        current_key=state.current_key,
        completion_pct=state.completion_pct,
        remaining_keys=state.remaining_keys,
        discovery_complete=False,
        ui_hint=build_ui_hint(peek.next_item),
        notices=notices,
    )
    yield _event("done", response.model_dump(mode="json"))


def run_turn(
    session_id: str,
    *,
    message: str | None = None,
    answers: dict[str, Any] | None = None,
) -> TurnResponse:
    final: TurnResponse | None = None
    for event in iter_turn_events(session_id, message=message, answers=answers):
        if event["event"] == "done":
            final = TurnResponse.model_validate(event["data"])
    assert final is not None
    return final
