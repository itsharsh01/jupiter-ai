from __future__ import annotations

import os


def _env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if value:
        return value
    for key, val in os.environ.items():
        if key.strip() == name:
            return (val or "").strip()
    return ""


def groq_api_key() -> str:
    return _env("GROQ_API_KEY")


def discovery_llm_model() -> str:
    """Default: Llama 4 Scout on Groq (fast)."""
    return _env("DISCOVERY_LLM_MODEL") or "meta-llama/llama-4-scout-17b-16e-instruct"


def discovery_llm_fallback_models() -> list[str]:
    raw = os.getenv(
        "DISCOVERY_LLM_FALLBACK_MODELS",
        "llama-3.3-70b-versatile",
    )
    return [m.strip() for m in raw.split(",") if m.strip()]


def discovery_llm_models() -> list[str]:
    """Primary model first, then fallbacks (deduplicated)."""
    seen: set[str] = set()
    ordered: list[str] = []
    for name in (discovery_llm_model(), *discovery_llm_fallback_models()):
        if name and name not in seen:
            seen.add(name)
            ordered.append(name)
    return ordered


def discovery_collection() -> str:
    return os.getenv("MONGO_DISCOVERY_COLLECTION", "discovery_sessions_v2")


def llm_enabled() -> bool:
    if os.getenv("DISCOVERY_DISABLE_LLM", "").lower() in {"1", "true", "yes"}:
        return False
    return bool(groq_api_key())


CONFIDENCE_POP_THRESHOLD = 0.75
MAX_CROSS_QUESTIONS = 2
MIN_AVG_CONFIDENCE_COMPLETE = 0.80
DISCOVERY_JUDGE_THRESHOLD = 80.0
VAGUE_ANSWER_MIN_CHARS = 25
