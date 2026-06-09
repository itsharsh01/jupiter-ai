from __future__ import annotations

import re
import uuid
from datetime import datetime, timezone
from typing import Any

STRATEGY_CATEGORIES = {
    "governance": "governance",
    "ai_risk": "ai_risk",
    "tool_abuse": "tool_abuse",
    "data_leakage": "data_leakage",
    "control_bypass": "control_bypass",
}

_MIN_PROMPT_WORDS = 10
_MIN_PROMPT_CHARS = 50


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first_str(*values: Any) -> str:
    for value in values:
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def _word_count(text: str) -> int:
    return len(re.findall(r"\b\w+\b", text))


def _is_valid_user_prompt(text: str) -> bool:
    """Reject role labels and scenario summaries masquerading as chat prompts."""
    if len(text) < _MIN_PROMPT_CHARS or _word_count(text) < _MIN_PROMPT_WORDS:
        return False
    lowered = text.lower().strip()
    # Single-token or "noun phrase" labels
    if _word_count(lowered) <= 3:
        return False
    weak_prefixes = (
        "an attacker",
        "a malicious user",
        "a customer",
        "the attacker",
        "the customer",
        "attacker posing",
        "malicious user",
    )
    if any(lowered.startswith(prefix) for prefix in weak_prefixes) and _word_count(lowered) < 12:
        return False
    return True


def _resolve_user_prompt(item: dict[str, Any]) -> str:
    for key in ("user_prompt", "query", "prompt", "session_confusion_prompt"):
        candidate = _first_str(item.get(key))
        if _is_valid_user_prompt(candidate):
            return candidate
    return ""


def _extract_cases(raw: dict[str, Any] | list[Any]) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        for key in ("test_cases", "cases", "results"):
            nested = raw.get(key)
            if isinstance(nested, list):
                return [item for item in nested if isinstance(item, dict)]
        return [raw]
    return []


def _lineage_from_context(strategy: str, context_bundle: list[dict[str, Any]]) -> tuple[str | None, str | None]:
    if not context_bundle:
        return None, None
    row = context_bundle[0]
    if strategy == "governance":
        return "BankingRegulation", _first_str(row.get("regulation_name"))
    if strategy == "ai_risk":
        return "AISecurityRisk", _first_str(row.get("risk_name"))
    if strategy == "tool_abuse":
        return "AgentTool", _first_str(row.get("tool_name"))
    if strategy == "data_leakage":
        return _first_str(row.get("data_class"), "PersonalInformation"), _first_str(row.get("data_name"))
    if strategy == "control_bypass":
        return "ComplianceControl", _first_str(row.get("control_name"))
    return None, None


def normalize_test_cases(
    strategy: str,
    raw: dict[str, Any] | list[Any],
    context_bundle: list[dict[str, Any]],
    limit: int = 5,
) -> list[dict[str, Any]]:
    source_type, source_name = _lineage_from_context(strategy, context_bundle)
    category = STRATEGY_CATEGORIES.get(strategy, strategy)
    cases: list[dict[str, Any]] = []

    for item in _extract_cases(raw)[:limit]:
        user_prompt = _resolve_user_prompt(item)
        if not user_prompt:
            continue

        title = _first_str(item.get("title"), item.get("objective"), user_prompt[:80])
        description = _first_str(
            item.get("description"),
            item.get("objective"),
            item.get("attack_variation"),
            item.get("leakage_vector"),
            item.get("bypass_technique"),
            item.get("abuse_scenario"),
        )
        tool_name = _first_str(item.get("tool_name"), item.get("tool"))
        if not tool_name and strategy == "tool_abuse" and context_bundle:
            tool_name = _first_str(context_bundle[0].get("tool_name"))

        cases.append(
            {
                "test_case_id": str(uuid.uuid4()),
                "strategy": strategy,
                "title": title,
                "description": description,
                "user_prompt": user_prompt,
                "category": _first_str(item.get("category"), category) or category,
                "pass_condition": _first_str(
                    item.get("pass_condition"),
                    item.get("expected_behavior"),
                    item.get("expected_agent_behavior"),
                ),
                "fail_condition": _first_str(
                    item.get("fail_condition"),
                    item.get("violation_indicator"),
                    item.get("what_should_not_appear_in_response"),
                ),
                "severity": _first_str(item.get("severity"), "MEDIUM").upper(),
                "tool_name": tool_name or None,
                "source_node_type": source_type,
                "source_node_name": source_name,
                "status": "ready",
                "execution": None,
            }
        )

    return cases
