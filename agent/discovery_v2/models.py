from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

AnswerType = Literal[
    "boolean",
    "enum",
    "multi_enum",
    "free_text",
    "number",
    "url",
    "tool_registry",
    "document_upload",
]
RiskLevel = Literal["CRITICAL", "HIGH", "MEDIUM", "LOW"]


class RiskQueueItem(BaseModel):
    key: str
    label: str
    section: str
    priority_score: int = 0
    risk_level: RiskLevel = "MEDIUM"
    required: bool = True
    answer_type: AnswerType = "free_text"
    allowed_values: list[str] | None = None
    unlocks_on: dict[str, list[str]] | None = None
    context_hint: str | None = None


class DiscoveredEntry(BaseModel):
    value: Any
    confidence: float
    source: str = "customer_stated"
    turn_discovered: int = 0


class TurnHistoryEntry(BaseModel):
    turn: int
    question_asked: str
    user_answer: str
    keys_filled: list[str] = Field(default_factory=list)


class CompletionCriteria(BaseModel):
    all_required_filled: bool = False
    all_critical_gaps_resolved: bool = False
    confidence_met: bool = False
    minimum_confidence: float = 0.80
    llm_completeness_score: float = 0.0
    llm_judge_met: bool = False


class GapAnalysisSnapshot(BaseModel):
    analyzed_at_turn: int = 0
    completeness_score: float = 0.0
    missing_keys: list[str] = Field(default_factory=list)
    missing_required: list[str] = Field(default_factory=list)
    priority_missing: list[str] = Field(default_factory=list)
    judge_reasoning: str = ""
    raw: dict[str, Any] = Field(default_factory=dict)


class SessionState(BaseModel):
    session_id: str
    started_at: str
    last_updated_at: str
    queue: list[RiskQueueItem] = Field(default_factory=list)
    discovered: dict[str, DiscoveredEntry] = Field(default_factory=dict)
    current_key: str | None = None
    cross_question_count: int = 0
    max_cross_questions: int = 2
    total_keys: int = 0
    filled_keys: int = 0
    remaining_keys: int = 0
    completion_pct: float = 0.0
    high_risk_flags_triggered: list[str] = Field(default_factory=list)
    turn_history: list[TurnHistoryEntry] = Field(default_factory=list)
    max_history_turns: int = 6
    discovery_complete: bool = False
    completion_criteria: CompletionCriteria = Field(default_factory=CompletionCriteria)
    gap_analysis: GapAnalysisSnapshot | None = None
    conversation_turns: int = 0


class FactPatch(BaseModel):
    key: str
    value: Any
    confidence: float
    source: str = "customer_stated"


class ParseAnswerResult(BaseModel):
    patches: list[FactPatch] = Field(default_factory=list)
    risk_flags_detected: list[str] = Field(default_factory=list)
    needs_cross_question: bool = False
    cross_question_reason: str | None = None


class PeekQueueResult(BaseModel):
    next_item: RiskQueueItem | None = None
    remaining_count: int = 0
    section_changed: bool = False
    section_intro_needed: str | None = None


class CheckConfidenceResult(BaseModel):
    should_pop: bool = False
    should_cross_question: bool = False
    discovery_complete: bool = False
    completion_pct: float = 0.0


class UIHint(BaseModel):
    interaction_type: Literal[
        "text",
        "boolean",
        "single_select",
        "multi_select",
        "tool_registry",
        "document_upload",
    ]
    field_key: str
    label: str
    allowed_values: list[str] | None = None
    min_selections: int = 0
    max_selections: int | None = None


class TurnResponse(BaseModel):
    session_id: str
    assistant_message: str
    current_key: str | None = None
    completion_pct: float = 0.0
    remaining_keys: int = 0
    discovery_complete: bool = False
    ui_hint: UIHint | None = None
    response_type: Literal["discovery", "clarification", "complete"] = "discovery"
    notices: list[str] = Field(default_factory=list)


class CompletionOutputs(BaseModel):
    system_summary: str
    discovered: dict[str, DiscoveredEntry]
    discovered_risks: list[dict[str, Any]]
    governance_readiness_report: dict[str, Any]
