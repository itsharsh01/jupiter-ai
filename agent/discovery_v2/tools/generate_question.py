from __future__ import annotations

import json
from collections.abc import Iterator

from agent.discovery_v2.llm import (
    discovery_llm_available,
    generate_text,
    reset_llm_status,
    stream_generate_text,
)
from agent.discovery_v2.models import RiskQueueItem, SessionState
from agent.discovery_v2.state_ops import already_known_summary

_POLICY_DETAIL_INSTRUCTION = (
    "Ask one friendly but thorough question (2–3 sentences). "
    "Request scope, who it applies to, obligations, prohibitions, exceptions, "
    "and how the policy is enforced. Do not ask yes/no only."
)

_TONE_INSTRUCTION = (
    "You are a warm, helpful AI governance guide. "
    "Use a sweet, encouraging tone — professional but kind, never robotic. "
    "Generate exactly ONE concise question (1–2 short sentences). "
    "Gently invite a specific, detailed answer (concrete examples, names, processes) "
    "— not vague replies like 'yes', 'standard', or 'we comply'. "
    "Do not reveal schema field names or internal keys. "
    "Reference what the customer already shared when relevant. "
)


def _build_prompt(
    target_item: RiskQueueItem,
    state: SessionState,
    *,
    is_cross_question: bool = False,
    section_intro_needed: str | None = None,
) -> str:
    history = state.turn_history[-state.max_history_turns :]
    known = already_known_summary(state)
    intro = ""
    if section_intro_needed:
        intro = (
            f"Briefly introduce the new topic ({section_intro_needed}) in a friendly phrase, "
            "then ask the question. "
        )

    instruction = _TONE_INSTRUCTION
    if is_cross_question:
        instruction += (
            "The prior answer was too brief or vague — kindly ask a focused follow-up "
            "on the same topic and explain what detail would help. "
        )
    elif target_item.key.startswith("policies."):
        instruction += _POLICY_DETAIL_INSTRUCTION
    elif target_item.answer_type == "tool_registry":
        instruction += (
            "Direct the user to the tool registration form below in a friendly way. "
            "Ask them to add each agent tool with its exact name, what it does, "
            "access required, and access currently granted. "
        )

    gap = state.gap_analysis
    gap_context = ""
    if gap:
        if target_item.key in gap.missing_required:
            gap_context = (
                f"Priority: this REQUIRED topic is still missing ({target_item.label}). "
                "Focus the question here. "
            )
        elif target_item.key in gap.missing_keys:
            gap_context = f"This topic is still needed for a complete profile ({target_item.label}). "

    if target_item.context_hint:
        instruction += f"Guidance: {target_item.context_hint} "
    instruction += intro + gap_context

    missing_hint = ""
    if gap and gap.priority_missing:
        missing_hint = f"Top missing topics: {', '.join(gap.priority_missing[:3])}\n"

    return (
        f"{instruction}\n\n"
        f"{missing_hint}"
        f"Target topic: {target_item.label}\n"
        f"Risk level: {target_item.risk_level}\n"
        f"Expected answer type: {target_item.answer_type}\n"
        f"Already known: {json.dumps(known, default=str)}\n"
        f"Recent turns: {json.dumps([h.model_dump() for h in history], default=str)}\n"
    )


def fallback_question(item: RiskQueueItem, *, is_cross_question: bool = False) -> str:
    label = item.label
    prefix = "Just to make sure I capture this well — " if is_cross_question else ""
    if item.answer_type == "tool_registry":
        return (
            f"{prefix}When you have a moment, please use the tool registration form below to add "
            "each agent tool or API integration: exact tool name, what it does, access required, "
            "and access your system currently has."
        )
    if item.answer_type == "document_upload":
        return (
            f"{prefix}Could you upload governance documents for {label} using the panel below "
            "(PDF, JSON, or YAML)? You can also describe references in text."
        )
    if item.answer_type == "boolean":
        return f"{prefix}Does your system involve {label}? A quick yes or no is perfect."
    if item.allowed_values:
        return f"{prefix}Regarding {label}, which option best describes your setup?"
    if item.key.startswith("policies."):
        return (
            f"{prefix}Could you walk me through your {label}? "
            "Scope, who it applies to, key rules, exceptions, and how it's enforced would be wonderful."
        )
    return (
        f"{prefix}Could you tell me about {label} for your AI system? "
        "Specific examples or how it works day-to-day would really help."
    )


def generate_question_tool(
    target_item: RiskQueueItem,
    state: SessionState,
    *,
    is_cross_question: bool = False,
    section_intro_needed: str | None = None,
) -> str:
    """ADK tool: natural language question for target queue item."""
    preview = fallback_question(target_item, is_cross_question=is_cross_question)
    if not discovery_llm_available():
        return preview
    prompt = _build_prompt(
        target_item,
        state,
        is_cross_question=is_cross_question,
        section_intro_needed=section_intro_needed,
    )
    text = generate_text(prompt)
    return text or preview


def stream_generate_question(
    target_item: RiskQueueItem,
    state: SessionState,
    *,
    is_cross_question: bool = False,
    section_intro_needed: str | None = None,
) -> Iterator[tuple[str, str]]:
    """
    Yield (phase, content) for SSE: delta chunks while generating, then final.
    Template fallback is only sent on final when LLM is off or fails (never as preview).
    """
    preview = fallback_question(target_item, is_cross_question=is_cross_question)
    reset_llm_status()

    if not discovery_llm_available():
        yield ("final", preview)
        return

    prompt = _build_prompt(
        target_item,
        state,
        is_cross_question=is_cross_question,
        section_intro_needed=section_intro_needed,
    )
    parts: list[str] = []
    for chunk in stream_generate_text(prompt):
        parts.append(chunk)
        yield ("delta", chunk)

    full = "".join(parts).strip() or preview
    yield ("final", full)
