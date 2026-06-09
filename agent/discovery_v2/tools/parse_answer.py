from __future__ import annotations

import re
from typing import Any

from agent.discovery_v2.config import VAGUE_ANSWER_MIN_CHARS
from agent.discovery_v2.copy import VAGUE_ANSWER_NUDGE
from agent.discovery_v2.llm import discovery_llm_available, generate_json
from agent.discovery_v2.models import FactPatch, ParseAnswerResult, SessionState
from agent.discovery_v2.priority_queue import queue_item_by_key
from agent.discovery_v2.state_ops import already_known_summary

_YES = frozenset({"yes", "y", "yeah", "yep", "sure", "true", "correct", "affirmative", "we do", "it does"})
_NO = frozenset({"no", "n", "nope", "nah", "false", "negative", "we don't", "we do not"})

_PAYMENT_KW = ("payment", "wire", "transfer", "card")
_PII_KW = ("pii", "personal data", "customer data", "ssn", "national id")

POLICY_MIN_DETAIL_CHARS = 120
TOOL_REGISTRY_KEY = "tooling.tools"

_VAGUE_PHRASES = frozenset(
    {
        "yes",
        "no",
        "maybe",
        "not sure",
        "i think so",
        "standard",
        "normal",
        "typical",
        "n/a",
        "none",
        "nothing",
        "same as before",
        "as usual",
    }
)


def _is_vague_answer(text: str, item) -> bool:
    stripped = text.strip()
    lower = stripped.lower().rstrip(".")
    if not stripped:
        return True
    if lower in _VAGUE_PHRASES:
        return True
    if item and item.answer_type == "boolean":
        return False
    if item and item.answer_type in ("enum", "multi_enum", "tool_registry", "document_upload"):
        return len(stripped) < 8
    return len(stripped) < VAGUE_ANSWER_MIN_CHARS


def _parse_yes_no(text: str) -> bool | None:
    lower = text.strip().lower().rstrip(".")
    if lower in _YES or lower.startswith("yes"):
        return True
    if lower in _NO or lower.startswith("no"):
        return False
    return None


def _normalize_tool_entry(raw: Any) -> dict[str, Any] | None:
    if not isinstance(raw, dict):
        return None
    name = str(raw.get("tool_name") or raw.get("name") or "").strip()
    if not name:
        return None
    return {
        "tool_name": name,
        "tool_description": str(raw.get("tool_description") or raw.get("description") or "").strip(),
        "access_required": str(raw.get("access_required") or "").strip(),
        "access_currently_has": str(
            raw.get("access_currently_has") or raw.get("access_granted") or ""
        ).strip(),
    }


def _merge_tool_registry(existing: Any, new_tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    seen: set[str] = set()
    if isinstance(existing, list):
        for entry in existing:
            norm = _normalize_tool_entry(entry)
            if norm and norm["tool_name"].lower() not in seen:
                merged.append(norm)
                seen.add(norm["tool_name"].lower())
    for entry in new_tools:
        norm = _normalize_tool_entry(entry)
        if norm and norm["tool_name"].lower() not in seen:
            merged.append(norm)
            seen.add(norm["tool_name"].lower())
    return merged


def _extract_tools_via_llm(user_answer: str, state: SessionState) -> list[dict[str, Any]]:
    if not discovery_llm_available():
        return []
    prompt = (
        f"User message: {user_answer}\n"
        "Extract every agent tool or API integration mentioned.\n"
        'Return JSON: {"tools":[{"tool_name":"exact_name","tool_description":"what it does",'
        '"access_required":"permissions needed","access_currently_has":"permissions granted"}]}'
    )
    data = generate_json(
        prompt,
        system="Extract structured tool registry entries. Use exact tool names from the user.",
    )
    tools: list[dict[str, Any]] = []
    for raw in data.get("tools") or []:
        norm = _normalize_tool_entry(raw)
        if norm:
            tools.append(norm)
    return tools


def _policy_needs_detail(current_key: str | None, user_answer: str) -> tuple[bool, str | None]:
    if not current_key or not current_key.startswith("policies."):
        return False, None
    if current_key == "policies.policy_document_refs":
        return False, None
    if len(user_answer.strip()) < POLICY_MIN_DETAIL_CHARS:
        return True, (
            "Please expand on scope, who must comply, key obligations, "
            "exceptions, and how this policy is enforced."
        )
    return False, None


def _rule_patches(state: SessionState, user_answer: str, current_key: str | None) -> list[FactPatch]:
    patches: list[FactPatch] = []
    text = user_answer.strip()
    lower = text.lower()

    if current_key:
        item = queue_item_by_key(state.queue, current_key)
        if item and item.answer_type == "boolean":
            yn = _parse_yes_no(text)
            if yn is not None:
                patches.append(
                    FactPatch(key=current_key, value=yn, confidence=0.92, source="customer_stated")
                )
                return patches

        if current_key == TOOL_REGISTRY_KEY:
            tools = _extract_tools_via_llm(user_answer, state)
            if tools:
                existing = state.discovered.get(TOOL_REGISTRY_KEY)
                existing_val = existing.value if existing else None
                merged = _merge_tool_registry(existing_val, tools)
                patches.append(
                    FactPatch(
                        key=TOOL_REGISTRY_KEY,
                        value=merged,
                        confidence=0.9,
                        source="customer_stated",
                    )
                )
                return patches

    if "langgraph" in lower:
        patches.append(
            FactPatch(key="architecture.framework", value="langgraph", confidence=0.9, source="customer_stated")
        )
    if "langchain" in lower:
        patches.append(
            FactPatch(key="architecture.framework", value="langchain", confidence=0.88, source="customer_stated")
        )
    if current_key != TOOL_REGISTRY_KEY and re.search(r"\b(CRM|KYC|payment|AML)\b", text, re.I):
        for m in re.findall(r"\b(CRM|KYC|payment|AML)\b", text, re.I):
            patches.append(
                FactPatch(key=TOOL_REGISTRY_KEY, value=m.upper(), confidence=0.75, source="customer_stated")
            )
    if "rag" in lower or "retrieval" in lower:
        patches.append(
            FactPatch(key="knowledge_sources.uses_rag", value=True, confidence=0.85, source="customer_stated")
        )

    if current_key and not patches and len(text) > 3:
        item = queue_item_by_key(state.queue, current_key)
        conf = 0.88 if item and item.answer_type == "free_text" else 0.8
        patches.append(
            FactPatch(key=current_key, value=text, confidence=conf, source="customer_stated")
        )

    return patches


def _detect_risk_flags(patches: list[FactPatch], user_answer: str) -> list[str]:
    flags: list[str] = []
    lower = user_answer.lower()
    for p in patches:
        if p.key == "data_assets.pii_sent_to_external_llm" and p.value is True:
            flags.append("pii_to_llm")
        if p.key == "architecture.agentic.is_agentic" and p.value is True:
            flags.append("autonomous_actions")
    if any(k in lower for k in _PAYMENT_KW):
        flags.append("payment_api")
    if any(k in lower for k in _PII_KW):
        flags.append("kyc_data_exposure")
    if "write" in lower or "approve" in lower:
        flags.append("write_operations")
    return list(dict.fromkeys(flags))


def parse_answer_tool(
    user_answer: str,
    state: SessionState,
) -> ParseAnswerResult:
    """ADK tool: extract fact patches from user message."""
    current_key = state.current_key
    patches = _rule_patches(state, user_answer, current_key)

    policy_cross, policy_reason = _policy_needs_detail(current_key, user_answer)

    if discovery_llm_available() and (not patches or len(user_answer) > 80):
        item = queue_item_by_key(state.queue, current_key) if current_key else None
        known = already_known_summary(state)
        prompt = (
            f"Current field: {current_key}\n"
            f"Answer type: {item.answer_type if item else 'free_text'}\n"
            f"Allowed values: {item.allowed_values if item else None}\n"
            f"Known: {known}\n"
            f"User answer: {user_answer}\n"
            'Return JSON: {"patches":[{"key":"...","value":...,"confidence":0.0-1.0,"source":"customer_stated"}],'
            '"needs_cross_question":false,"cross_question_reason":null}'
        )
        if current_key == TOOL_REGISTRY_KEY:
            prompt += (
                ' For tooling.tools use value as array of objects with tool_name, '
                "tool_description, access_required, access_currently_has."
            )
        data = generate_json(
            prompt,
            system="Extract governance discovery facts. Only include high-confidence fields.",
        )
        for raw in data.get("patches") or []:
            if not raw.get("key"):
                continue
            value = raw.get("value")
            if raw["key"] == TOOL_REGISTRY_KEY:
                if isinstance(value, list):
                    existing = state.discovered.get(TOOL_REGISTRY_KEY)
                    existing_val = existing.value if existing else None
                    normalized = [_normalize_tool_entry(v) for v in value]
                    normalized = [t for t in normalized if t]
                    value = _merge_tool_registry(existing_val, normalized)
                elif isinstance(value, dict):
                    norm = _normalize_tool_entry(value)
                    if norm:
                        existing = state.discovered.get(TOOL_REGISTRY_KEY)
                        existing_val = existing.value if existing else None
                        value = _merge_tool_registry(existing_val, [norm])
            patches.append(
                FactPatch(
                    key=raw["key"],
                    value=value,
                    confidence=float(raw.get("confidence", 0.8)),
                    source=raw.get("source", "customer_stated"),
                )
            )
        if data.get("needs_cross_question"):
            return ParseAnswerResult(
                patches=patches,
                risk_flags_detected=_detect_risk_flags(patches, user_answer),
                needs_cross_question=True,
                cross_question_reason=data.get("cross_question_reason"),
            )

    needs_cross = policy_cross
    reason = policy_reason
    item = queue_item_by_key(state.queue, current_key) if current_key else None
    if item and _is_vague_answer(user_answer, item):
        needs_cross = True
        reason = reason or VAGUE_ANSWER_NUDGE
    if current_key and current_key in state.discovered:
        entry = state.discovered[current_key]
        if entry.confidence < 0.75 and len(user_answer.strip()) < VAGUE_ANSWER_MIN_CHARS:
            needs_cross = True
            reason = reason or VAGUE_ANSWER_NUDGE

    for p in patches:
        if p.confidence < 0.75:
            needs_cross = True
            reason = reason or f"Low confidence on {p.key}"

    return ParseAnswerResult(
        patches=patches,
        risk_flags_detected=_detect_risk_flags(patches, user_answer),
        needs_cross_question=needs_cross,
        cross_question_reason=reason,
    )
