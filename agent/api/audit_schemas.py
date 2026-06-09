from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AuditStatus = Literal["draft", "generating", "ready", "failed"]

TestCaseStrategy = Literal[
    "governance",
    "ai_risk",
    "tool_abuse",
    "data_leakage",
    "control_bypass",
]

TestCaseStatus = Literal[
    "pending", "ready", "running", "evaluating", "passed", "failed", "error"
]

EvaluationStatus = Literal[
    "pending_trace", "tracing", "evaluating", "complete", "error"
]

ReportVerdict = Literal["pass", "fail"]


class StepFinding(BaseModel):
    step_type: str = ""
    tool: str | None = None
    issue: str = ""


class TestCaseReport(BaseModel):
    verdict: ReportVerdict
    reasoning: str = ""
    failure_summary: str | None = None
    problematic_tools: list[str] = Field(default_factory=list)
    step_findings: list[StepFinding] = Field(default_factory=list)
    recommendations: str | None = None


class TestCaseExecutionResponse(BaseModel):
    status_code: int = 0
    response_preview: str | None = None
    executed_at: str | None = None
    passed: bool | None = None
    message: str | None = None
    execution_id: str | None = None
    phoenix_trace_id: str | None = None
    phoenix_span_id: str | None = None
    phoenix_span_global_id: str | None = None
    evaluation_status: EvaluationStatus | None = None
    report: TestCaseReport | None = None
    trace_linked_at: str | None = None
    evaluated_at: str | None = None


class AuditTestCaseResponse(BaseModel):
    test_case_id: str
    strategy: TestCaseStrategy
    title: str
    description: str = ""
    user_prompt: str
    category: str = ""
    pass_condition: str = ""
    fail_condition: str = ""
    severity: str = "MEDIUM"
    tool_name: str | None = None
    source_node_type: str | None = None
    source_node_name: str | None = None
    status: TestCaseStatus = "ready"
    execution: TestCaseExecutionResponse | None = None


class AuditSandboxUpsertRequest(BaseModel):
    session_id: str
    system_url: str = Field(..., min_length=1, description="Client system base URL or endpoint")
    auth_token: str | None = Field(default=None, description="Sample bearer/API token for sandbox calls")
    sample_request_body: dict[str, Any] | str | None = None
    sample_response_body: dict[str, Any] | str | None = None
    test_sandbox: bool = Field(
        default=False,
        description="When true, probe system_url after save and require HTTP 200",
    )


class SandboxTestResponse(BaseModel):
    audit_id: str
    passed: bool
    status_code: int
    response_preview: str | None = None
    message: str


class AuditSandboxResponse(BaseModel):
    audit_id: str
    session_id: str
    customer_id: str | None = None
    system_url: str
    auth_token_set: bool = False
    sample_request_body: dict[str, Any] | str | None = None
    sample_response_body: dict[str, Any] | str | None = None
    sandbox_test_passed: bool = False
    sandbox_test_status_code: int | None = None
    status: AuditStatus = "draft"
    test_cases: list[AuditTestCaseResponse] = Field(default_factory=list)
    created_at: str
    updated_at: str


class StartAuditResponse(BaseModel):
    audit_id: str
    status: AuditStatus
    test_cases_generated: int
    message: str
    strategies_generated: list[str] = Field(default_factory=list)


class ExecuteTestCaseResponse(BaseModel):
    audit_id: str
    test_case_id: str
    status: TestCaseStatus
    execution: TestCaseExecutionResponse


class AuditReportResponse(BaseModel):
    audit_id: str
    generated_at: str
    executive_summary: dict[str, Any] = Field(default_factory=dict)
    system_understanding: dict[str, Any] = Field(default_factory=dict)
    asset_inventory: dict[str, Any] = Field(default_factory=dict)
    policy_coverage: dict[str, Any] = Field(default_factory=dict)
    risk_assessment: dict[str, Any] = Field(default_factory=dict)
    test_execution: dict[str, Any] = Field(default_factory=dict)
    policy_violations: list[dict[str, Any]] = Field(default_factory=list)
    control_effectiveness: dict[str, Any] = Field(default_factory=dict)
    tool_governance: list[dict[str, Any]] = Field(default_factory=list)
    trace_evidence: list[dict[str, Any]] = Field(default_factory=list)
    remediation_plan: dict[str, Any] = Field(default_factory=dict)
    maturity_assessment: dict[str, Any] = Field(default_factory=dict)
    final_verdict: dict[str, Any] = Field(default_factory=dict)
